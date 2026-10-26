# -*- coding: utf-8 -*-
"""
港股领航指标 Web 看板
========================
- 数据源：akshare（免费宏观数据） + 香港金管局官方 Excel（港元M2）
- 指标口径（与抖音视频「文主任·港股顶底信号」对齐）：
    领航指标 = 0.25*港元M2同比 + 0.25*PPI当月同比 + 0.25*社零当月同比 + 0.25*信用脉冲
    信用脉冲 = (近6月社融合计 - 去年同期6月社融合计) / 最近两个季度名义GDP之和 * 100
    展示曲线 = 领航指标原始值（左轴黑线） + 恒生指数月末收盘（右轴橙线）
    （原始值版无需 36 个月滚动预热，与 Excel 表格口径一致）
- 启动：python hk_lead_index_web.py   →  浏览器打开 http://127.0.0.1:8000
"""
import re
import io
import os
import requests
import akshare as ak
import pandas as pd
import plotly.graph_objects as go
from plotly.io import to_html
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

app = FastAPI(title="港股领航指标Web看板")
templates = Jinja2Templates(directory="templates")

DEFAULT_START_DATE = "2014-01-01"   # 默认数据起点（最早受限于社融源2015-01，信用脉冲2016-06起才有值）
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "start_date.conf")


def load_start_date():
    """从配置文件读取数据起点；文件缺失或非法时回退默认值"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            v = f.read().strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            return v
    except OSError:
        pass
    return DEFAULT_START_DATE


def save_start_date(v):
    """持久化数据起点到配置文件"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(v)


class StartDateIn(BaseModel):
    start_date: str

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
HKMA_XLS = "https://www.hkma.gov.hk/media/eng/doc/market-data-and-statistics/monthly-statistical-bulletin/T020201.xls"


# ====================== 通用工具 ======================

def parse_cn_month(s):
    """'2026年09月份' / '2026年9月份' -> 2026-09-30（月末）"""
    m = re.match(r"(\d{4})年(\d{1,2})月份?", str(s).strip())
    if not m:
        return pd.NaT
    return pd.Timestamp(int(m.group(1)), int(m.group(2)), 1) + pd.offsets.MonthEnd(0)


def to_month_end(series):
    return pd.to_datetime(series).dt.to_period("M").dt.to_timestamp("M")


# ====================== 数据获取 ======================

def get_hsi_monthly():
    """恒生指数月末收盘（新浪港股指数日线 -> 重采样月K）"""
    df = ak.stock_hk_index_daily_sina(symbol="HSI")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    m = df["close"].resample("ME").last().reset_index()
    return m.rename(columns={"close": "hsi_close"})


def get_ppi():
    """内地 PPI 当月同比（%），国家统计局"""
    df = ak.macro_china_ppi()
    out = pd.DataFrame({
        "date": to_month_end(df["月份"].map(parse_cn_month)),
        "ppi_yoy": pd.to_numeric(df["当月同比增长"], errors="coerce"),
    }).dropna(subset=["date"])
    return out.sort_values("date").reset_index(drop=True)


def get_retail():
    """内地社零当月同比（%）。1-2月官方合并发布：接口只有2月行(带累计同比)，
    用2月的累计同比(即1-2月合并同比)填充1月、2月；1月行缺失时显式创建。"""
    df = ak.macro_china_consumer_goods_retail()
    out = pd.DataFrame({
        "date": to_month_end(df["月份"].map(parse_cn_month)),
        "retail_yoy": pd.to_numeric(df["同比增长"], errors="coerce"),
        "cum_yoy": pd.to_numeric(df["累计-同比增长"], errors="coerce"),
    }).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    new_rows = []
    for year, grp in out.groupby(out["date"].dt.year):
        feb = grp[(grp["date"].dt.month == 2) & grp["cum_yoy"].notna()]
        if feb.empty:
            continue
        val = float(feb["cum_yoy"].iloc[0])
        # 2月 = 合并同比
        out.loc[(out["date"].dt.year == year) & (out["date"].dt.month == 2), "retail_yoy"] = val
        # 1月 = 合并同比（缺失则创建行）
        jan = out[(out["date"].dt.year == year) & (out["date"].dt.month == 1)]
        if jan.empty:
            new_rows.append({"date": pd.Timestamp(year, 1, 1) + pd.offsets.MonthEnd(0), "retail_yoy": val})
        else:
            out.loc[(out["date"].dt.year == year) & (out["date"].dt.month == 1), "retail_yoy"] = val
    if new_rows:
        out = pd.concat([out[["date", "retail_yoy"]], pd.DataFrame(new_rows)])
    out = out.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    return out[["date", "retail_yoy"]]


def get_social_finance():
    """社融增量（月度，亿元）——需要比 2021 更早以支持信用脉冲 12 个月错位"""
    df = ak.macro_china_shrzgm()
    out = pd.DataFrame({
        "date": to_month_end(pd.to_datetime(df["月份"].astype(str), format="%Y%m")),
        "social_finance": pd.to_numeric(df["社会融资规模增量"], errors="coerce"),
    }).dropna(subset=["date"])
    return out.sort_values("date").reset_index(drop=True)


def get_gdp_nominal():
    """名义GDP单季（亿元）：akshare 返回累计值，做季度差分还原单季"""
    df = ak.macro_china_gdp()
    out = pd.DataFrame({
        "q_label": df["季度"].astype(str),
        "gdp_cum": pd.to_numeric(df["国内生产总值-绝对值"], errors="coerce"),
    }).dropna(subset=["gdp_cum"])
    # 解析季度标签：'2026年第1-3季度' -> 年末月 2026-09；'2026年第1季度' -> 2026-03
    def q_end(s):
        m = re.match(r"(\d{4})年第1(?:-(\d+))?季度", s)
        if not m:
            return pd.NaT
        end_q = int(m.group(2) or "1")
        return pd.Timestamp(int(m.group(1)), 1, 1) + pd.DateOffset(months=3 * end_q - 1) + pd.offsets.MonthEnd(0)
    out["date"] = out["q_label"].map(q_end)
    out = out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    out["gdp_quarter"] = out["gdp_cum"].diff()
    out.loc[out["date"].dt.month == 3, "gdp_quarter"] = out["gdp_cum"]  # Q1 即累计
    return out[["date", "gdp_quarter"]].rename(columns={"gdp_quarter": "gdp_nominal"})


def get_hkd_m2_yoy():
    """港元M2同比（%）：金管局官方 Excel T020201（就外币掉期存款作出调整），第8列=M2港元"""
    r = requests.get(HKMA_XLS, headers=UA, timeout=60)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content), sheet_name=0, header=None,
                       engine="xlrd")
    # 列0=年(仅每年首行有值,需ffill), 列1=月英文, 列8=港元M2（百万港元）
    raw = df[[0, 1, 8]].copy()
    raw.columns = ["year", "mon", "m2_hkd"]
    raw = raw.dropna(subset=["mon", "m2_hkd"])
    raw["year"] = raw["year"].ffill()
    raw = raw[pd.to_numeric(raw["year"], errors="coerce").notna()]
    raw["m2_hkd"] = pd.to_numeric(raw["m2_hkd"], errors="coerce")
    raw["date"] = pd.to_datetime(
        raw["year"].astype(int).astype(str) + "-" + raw["mon"].astype(str) + "-01"
    ) + pd.offsets.MonthEnd(0)
    raw = raw.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    raw["m2_hkd_yoy"] = raw["m2_hkd"].pct_change(12) * 100
    return raw[["date", "m2_hkd_yoy"]]


def calc_credit_pulse(sf_df, gdp_df):
    """信用脉冲（%）= (近6月社融合计 - 去年同期6月社融合计) / 最近两季度名义GDP之和 * 100"""
    sf = sf_df.copy().sort_values("date")
    sf["sf_6sum"] = sf["social_finance"].rolling(window=6).sum()
    sf["sf_6sum_12ago"] = sf["sf_6sum"].shift(12)
    sf["delta_6sf"] = sf["sf_6sum"] - sf["sf_6sum_12ago"]

    gdp = gdp_df.copy().sort_values("date")
    gdp["gdp_2q_sum"] = gdp["gdp_nominal"].rolling(window=2).sum()
    gdp["q"] = gdp["date"].dt.to_period("Q")
    gdp_map = dict(zip(gdp["q"], gdp["gdp_2q_sum"]))

    sf["q"] = sf["date"].dt.to_period("Q")
    sf["gdp_2q"] = sf["q"].map(gdp_map)
    sf["credit_pulse"] = sf["delta_6sf"] / sf["gdp_2q"] * 100
    return sf[["date", "credit_pulse"]]


# ====================== 页面 ======================

@app.post("/api/start_date")
async def set_start_date(payload: StartDateIn):
    """前端修改数据起点（持久化到配置文件）"""
    v = (payload.start_date or "").strip()
    m = re.match(r"^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?$", v)
    if not m:
        return JSONResponse({"ok": False, "error": "格式应为 YYYY-MM 或 YYYY-MM-DD"}, status_code=400)
    y, mo = int(m.group(1)), int(m.group(2))
    if not (2000 <= y <= 2100) or not (1 <= mo <= 12):
        return JSONResponse({"ok": False, "error": "年份或月份非法"}, status_code=400)
    norm = "%04d-%02d-01" % (y, mo)
    save_start_date(norm)
    return {"ok": True, "start_date": norm}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    print("正在拉取数据（akshare + 香港金管局）...")
    start_date = load_start_date()
    df_hsi = get_hsi_monthly()
    df_ppi = get_ppi()
    df_retail = get_retail()
    df_m2 = get_hkd_m2_yoy()
    df_sf = get_social_finance()
    df_gdp = get_gdp_nominal()
    df_cp = calc_credit_pulse(df_sf, df_gdp)

    df_all = df_ppi
    for d in [df_retail, df_m2, df_cp, df_hsi]:
        df_all = pd.merge(df_all, d, on="date", how="outer")
    df_all = df_all.sort_values("date").reset_index(drop=True)
    df_all = df_all[df_all["date"] >= pd.Timestamp(start_date)].copy()

    df_all["lead_raw"] = (
        0.25 * df_all["m2_hkd_yoy"]
        + 0.25 * df_all["ppi_yoy"]
        + 0.25 * df_all["retail_yoy"]
        + 0.25 * df_all["credit_pulse"]
    )

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_all["date"], y=df_all["lead_raw"],
        name="领航指标(原始值)",
        line=dict(color="black", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=df_all["date"], y=df_all["m2_hkd_yoy"],
        name="港元M2同比(%)",
        line=dict(color="#1677ff", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=df_all["date"], y=df_all["hsi_close"],
        name="恒生指数月末收盘",
        line=dict(color="#ff8822", width=2),
        yaxis="y2",
    ))
    fig.update_layout(
        title="恒生指数领航指标（原始值版）",
        xaxis_title="月份",
        yaxis_title="领航指标 / 港元M2同比 (%)",
        yaxis2=dict(title="恒生指数点位", overlaying="y", side="right"),
        height=620,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=60, r=70, t=80, b=40),
    )
    chart_html = to_html(fig, full_html=False)

    show_cols = ["date", "m2_hkd_yoy", "ppi_yoy", "retail_yoy",
                 "credit_pulse", "lead_raw", "hsi_close"]
    last = df_all.dropna(subset=["lead_raw"]).tail(1)
    df_view = df_all[show_cols].copy()
    num_cols = [c for c in show_cols if c != "date"]
    df_view[num_cols] = df_view[num_cols].round(3).fillna("")
    table_html = df_view.rename(columns={
        "date": "月份", "m2_hkd_yoy": "港元M2同比(%)", "ppi_yoy": "PPI同比(%)",
        "retail_yoy": "社零同比(%)", "credit_pulse": "信用脉冲(%)",
        "lead_raw": "领航指标(原始)",
        "hsi_close": "恒指月末收盘",
    }).to_html(index=False, classes="data-table")

    return templates.TemplateResponse(
        request, "index.html",
        {"chart_html": chart_html, "table_html": table_html,
         "data_count": len(df_all), "last_date": str(df_all["date"].iloc[-1].date()),
         "last_lead": None if last.empty else round(float(last["lead_raw"].iloc[0]), 2),
         "start_date": start_date,
         },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("hk_lead_index_web:app", host="127.0.0.1", port=8000, reload=True)
