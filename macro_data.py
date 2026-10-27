"""Network adapters and calculations for the monthly leading indicator."""

import datetime as dt
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from datetime import datetime


class DataUpdateError(Exception):
    pass


HKMA_XLS = os.environ.get(
    "HKMA_M2_URL",
    "https://www.hkma.gov.hk/media/eng/doc/market-data-and-statistics/monthly-statistical-bulletin/T020201.xls",
)
MOFCOM_SOCIAL_FINANCING_URL = "https://data.mofcom.gov.cn/datamofcom/front/gnmy/shrzgmQuery"
MOFCOM_SOCIAL_FINANCING_COLUMNS = (
    "月份",
    "其中-未贴现银行承兑汇票",
    "其中-委托贷款",
    "其中-委托贷款外币贷款",
    "其中-人民币贷款",
    "其中-企业债券",
    "社会融资规模增量",
    "其中-非金融企业境内股票融资",
    "其中-信托贷款",
)
PBC_SHRZGM_PAGE = os.environ.get(
    "PBC_SHRZGM_PAGE",
    "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/2026ntjsj/shrzgm/index.html",
)
NBS_GDP_PAGE = os.environ.get("NBS_GDP_PAGE", "https://www.stats.gov.cn/sj/zxfb/")
NBS_QUARTER_TITLE = re.compile(r"(\d{4})年(?:第)?([一二三四1-4])季度(?:和(?:上半年|全年))?国内生产总值初步核算结果")
MONTH_RE = re.compile(r"^(\d{2}|\d{4})[-/](\d{1,2})$")


def parse_month(value):
    if not isinstance(value, str):
        raise ValueError("月份必须是 YY/M 或 YYYY-MM 格式")
    match = MONTH_RE.fullmatch(value.strip())
    if not match:
        raise ValueError("月份格式无效，请使用 YY/M 或 YYYY-MM")
    year, month = int(match.group(1)), int(match.group(2))
    if year < 100:
        year += 2000 if year <= 79 else 1900
    if month < 1 or month > 12:
        raise ValueError("月份必须在 1 至 12 之间")
    return "%04d-%02d" % (year, month)


def parse_month_range(start, end):
    first, last = parse_month(start), parse_month(end)
    if first > last:
        raise ValueError("起始月份不能晚于结束月份")
    return first, last


def months_between(start, end):
    year, month = map(int, start.split("-"))
    end_year, end_month = map(int, end.split("-"))
    result = []
    while (year, month) <= (end_year, end_month):
        result.append("%04d-%02d" % (year, month))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return result


def month_of(value):
    if isinstance(value, (dt.date, dt.datetime)):
        return value.strftime("%Y-%m")
    text = str(value).strip()
    match = re.search(r"(\d{4})[-年/.](\d{1,2})", text)
    if match:
        return "%04d-%02d" % (int(match.group(1)), int(match.group(2)))
    match = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", text)
    if match:
        return "%04d-%02d" % (int(match.group(1)), int(match.group(2)))
    for pattern in ("%Y %b", "%Y %B", "%b-%y", "%b %y", "%Y/%m", "%Y%m"):
        try:
            return datetime.strptime(text, pattern).strftime("%Y-%m")
        except ValueError:
            continue
    raise ValueError("无法识别月份: %s" % text)


def quarter_of(value):
    text = str(value).strip()
    match = re.search(r"(\d{4})年\s*第?1\s*[-~至]\s*([1-4])\s*季度", text, re.I)
    if not match:
        match = re.search(r"(\d{4}).*?([1-4])\s*季度", text, re.I)
    if not match:
        match = re.search(r"(\d{4})\s*[Qq]([1-4])", text)
    if not match:
        raise ValueError("无法识别季度: %s" % text)
    return int(match.group(1)) * 4 + int(match.group(2)) - 1


def number(value):
    if value is None:
        return None
    try:
        if value != value:
            return None
    except Exception:
        pass
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text in ("-", "--", "—", "N/A"):
        return None
    return float(text)


def records(frame):
    if hasattr(frame, "to_dict"):
        return frame.to_dict("records")
    return list(frame)


def find_column(rows, patterns, required=True):
    if not rows:
        if required:
            raise DataUpdateError("数据源没有记录")
        return None
    columns = list(rows[0].keys())
    normalized_columns = {column: str(column).lower().replace(" ", "") for column in columns}
    normalized_patterns = [pattern.lower().replace(" ", "") for pattern in patterns]
    for pattern in normalized_patterns:
        for column in columns:
            if normalized_columns[column] == pattern:
                return column
    for column in columns:
        if any(pattern in normalized_columns[column] for pattern in normalized_patterns):
            return column
    if required:
        raise DataUpdateError("无法识别数据列: %s" % ", ".join(map(str, columns)))
    return None


def indexed_values(frame, value_patterns, month_patterns=("月份", "日期", "季度", "时间")):
    rows = records(frame)
    date_col = find_column(rows, month_patterns)
    value_col = find_column(rows, value_patterns)
    result = {}
    for row in rows:
        try:
            value = number(row[value_col])
        except (ValueError, TypeError):
            continue
        if value is not None:
            label = str(row[date_col]).strip()
            combined = re.search(r"(\d{4})\s*年\s*1\s*[-~至]\s*2\s*月", label)
            if combined:
                result["%04d-01" % int(combined.group(1))] = value
                result["%04d-02" % int(combined.group(1))] = value
                continue
            result[month_of(row[date_col])] = value
    return result


def quarterly_values(frame, value_patterns):
    rows = records(frame)
    quarter_col = find_column(rows, ("季度", "quarter", "时间", "日期"))
    value_col = find_column(rows, value_patterns)
    result = {}
    for row in rows:
        try:
            result[quarter_of(row[quarter_col])] = number(row[value_col])
        except (ValueError, TypeError):
            continue
    return {key: value for key, value in result.items() if value is not None}


def retail_values(frame):
    rows = records(frame)
    date_col = find_column(rows, ("月份", "时间", "日期"))
    yoy_col = find_column(rows, ("同比增长", "当月同比"))
    cumulative_col = find_column(rows, ("累计-同比增长", "累计同比增长"), required=False)
    result = {}
    for row in rows:
        try:
            label = str(row[date_col]).strip()
            yoy = number(row[yoy_col])
            cumulative = number(row[cumulative_col]) if cumulative_col else None
            month = month_of(row[date_col])
        except (ValueError, TypeError):
            continue
        combined = re.search(r"(\d{4})\s*年\s*1\s*[-~至]\s*2\s*月", label)
        if combined:
            value = cumulative if cumulative is not None else yoy
            if value is not None:
                result["%04d-01" % int(combined.group(1))] = value
                result["%04d-02" % int(combined.group(1))] = value
        elif month.endswith("-02") and cumulative is not None:
            year = month[:4]
            result[year + "-01"] = cumulative
            result[year + "-02"] = cumulative
        elif yoy is not None:
            result[month] = yoy
    return result


def cumulative_gdp_to_quarters(cumulative):
    quarterly = {}
    for quarter in sorted(cumulative):
        year, quarter_number = divmod(quarter, 4)
        quarter_number += 1
        value = cumulative[quarter]
        if quarter_number == 1:
            quarterly[quarter] = value
        elif quarter - 1 in cumulative:
            quarterly[quarter] = value - cumulative[quarter - 1]
    return quarterly


def _akshare():
    try:
        import akshare
    except ImportError as error:
        raise DataUpdateError("未安装 AkShare。请在服务环境运行：python3 -m pip install akshare pandas openpyxl xlrd") from error
    return akshare


def _call_akshare(label, function, attempts=2):
    """Call one AkShare endpoint and retain its identity in upstream errors."""
    last_error = None
    for attempt in range(attempts):
        try:
            value = function()
            if value is None or (hasattr(value, "empty") and value.empty):
                raise ValueError("返回为空")
            return value
        except DataUpdateError:
            raise
        except Exception as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(0.8)
    detail = str(last_error).strip() or repr(last_error)
    if isinstance(last_error, json.JSONDecodeError) or "Expecting value" in detail:
        detail = "上游返回空响应或非 JSON 内容（可能是网络/接口限流）"
    raise DataUpdateError("AkShare %s 接口失败（重试 %d 次）：%s" % (label, attempts, detail))


def fetch_social_financing_direct():
    """Fallback for AkShare's MOFCOM-backed endpoint, which can intermittently return an empty body."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://data.mofcom.gov.cn",
        "Referer": "https://data.mofcom.gov.cn/gnmy/shrzgm.shtml",
    }
    last_error = None
    for attempt in range(2):
        try:
            request = urllib.request.Request(MOFCOM_SOCIAL_FINANCING_URL, data=b"", headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
            if not body or not body.strip():
                raise ValueError("商务部返回空响应")
            payload = json.loads(body.decode("utf-8-sig"))
            while isinstance(payload, str):
                payload = json.loads(payload)
            if isinstance(payload, dict):
                for key in ("data", "rows", "result", "list"):
                    if isinstance(payload.get(key), list):
                        payload = payload[key]
                        break
            if not isinstance(payload, list) or not payload:
                raise ValueError("商务部响应中没有社融记录")
            if isinstance(payload[0], dict):
                normalized = []
                for item in payload:
                    if "月份" in item and "社会融资规模增量" in item:
                        normalized.append(item)
                    elif "date" in item and "tiosfs" in item:
                        normalized.append({"月份": item["date"], "社会融资规模增量": item["tiosfs"]})
                if not normalized:
                    raise ValueError("商务部响应缺少 date/tiosfs 社融字段")
                return normalized
            return [dict(zip(MOFCOM_SOCIAL_FINANCING_COLUMNS, row)) for row in payload if isinstance(row, (list, tuple))]
        except Exception as error:
            last_error = error
            if attempt == 0:
                time.sleep(0.8)
    detail = str(last_error).strip() or repr(last_error)
    if isinstance(last_error, json.JSONDecodeError) or "Expecting value" in detail:
        detail = "商务部返回空响应或非 JSON 内容"
    raise DataUpdateError("商务部社融直连接口失败（重试 2 次）：%s" % detail)


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.link = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.link = dict(attrs)
            self.text = []

    def handle_data(self, data):
        if self.link is not None:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.link is not None:
            title = self.link.get("title") or " ".join("".join(self.text).split())
            self.links.append((self.link.get("href", ""), title))
            self.link = None


def decode_html(content):
    match = re.search(br"charset\s*=\s*[\"']?([\w-]+)", content[:4096], re.I)
    encoding = match.group(1).decode("ascii") if match else "utf-8"
    try:
        return content.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return content.decode("gb18030", "replace")


def parse_pbc_social_financing_html(content):
    parser = _TableParser()
    parser.feed(decode_html(content))
    values = []
    for row in parser.rows:
        if len(row) < 2:
            continue
        match = re.fullmatch(r"(\d{4})[.]?(\d{2})", row[0].strip())
        if not match:
            continue
        value = number(row[1])
        if value is not None:
            values.append({"月份": "%s%s" % (match.group(1), match.group(2)), "社会融资规模增量": value})
    if not values:
        raise DataUpdateError("人民银行社融 HTML 中未找到月度增量数据")
    return values


def parse_nbs_gdp_report(content):
    """Read the current-quarter GDP amount (current prices) from an NBS release."""
    text = decode_html(content)
    title = NBS_QUARTER_TITLE.search(text)
    if not title:
        raise DataUpdateError("国家统计局报告标题中未找到季度")
    quarter_number = "一二三四".index(title.group(2)) + 1 if title.group(2) in "一二三四" else int(title.group(2))
    parser = _TableParser()
    parser.feed(text)
    for row in parser.rows:
        if len(row) >= 2 and row[0].strip().upper() == "GDP":
            amount = number(row[1])
            if amount is not None and amount > 0:
                return int(title.group(1)) * 4 + quarter_number - 1, amount
    raise DataUpdateError("国家统计局 GDP 报告中未找到单季现价绝对额")


def fetch_nbs_gdp():
    """Find recent NBS quarterly releases and return their single-quarter GDP amounts."""
    try:
        reports = {}
        page_limit = 20
        for page_number in range(page_limit):
            page_url = NBS_GDP_PAGE if page_number == 0 else urllib.parse.urljoin(
                NBS_GDP_PAGE, "index_%d.html" % page_number
            )
            try:
                page_content, final_url, _ = _urlopen(page_url)
            except Exception:
                if reports:
                    break
                raise
            text = decode_html(page_content)
            links = _LinkParser()
            links.feed(text)
            for href, title in links.links:
                match = NBS_QUARTER_TITLE.search(title)
                if not match:
                    continue
                quarter_number = "一二三四".index(match.group(2)) + 1 if match.group(2) in "一二三四" else int(match.group(2))
                key = int(match.group(1)) * 4 + quarter_number - 1
                reports.setdefault(key, urllib.parse.urljoin(final_url, href))
            count = re.search(r"createPageHTML\(\s*(\d+)\s*,", text)
            if len(reports) >= 2 or (count and page_number + 1 >= int(count.group(1))):
                break
        result = {}
        for quarter in sorted(reports, reverse=True)[:2]:
            try:
                content, _, _ = _urlopen(reports[quarter])
                parsed_quarter, amount = parse_nbs_gdp_report(content)
                if parsed_quarter == quarter:
                    result[parsed_quarter] = amount
            except Exception:
                # One broken attachment must not discard another valid release.
                continue
        if not result:
            raise DataUpdateError("国家统计局发布目录中未找到季度 GDP 报告")
        return result
    except DataUpdateError:
        raise
    except Exception as error:
        raise DataUpdateError("国家统计局季度 GDP 抓取失败：%s" % error)


def fetch_pbc_social_financing():
    try:
        page, final_url, _ = _urlopen(PBC_SHRZGM_PAGE)
        text = decode_html(page)
        flow_rows = [row for row in re.findall(r"<tr\b[^>]*>.*?</tr>", text, re.I | re.S)
                     if "社会融资规模增量统计表" in row and "地区社会融资" not in row]
        links = re.findall(r"href=[\"']([^\"']+\.htm(?:\?[^\"']*)?)[\"']", " ".join(flow_rows), re.I)
        if not links:
            raise DataUpdateError("人民银行社融页面未找到全国社融增量 HTML 表格链接")
        table_url = urllib.parse.urljoin(final_url, links[0])
        content, _, _ = _urlopen(table_url)
        return parse_pbc_social_financing_html(content)
    except DataUpdateError:
        raise
    except Exception as error:
        raise DataUpdateError("人民银行社融官方表抓取失败：%s" % error)


def merge_social_financing(*sources):
    """Merge monthly financing records, letting later official sources override."""
    merged = {}
    for source in sources:
        if not source:
            continue
        values = indexed_values(source, ("社会融资规模增量",), ("月份", "时间", "日期"))
        merged.update(values)
    return merged


def fetch_akshare(start, end):
    ak = _akshare()
    try:
        ppi_frame = _call_akshare("PPI（macro_china_ppi）", lambda: ak.macro_china_ppi())
        retail_frame = _call_akshare("社零（macro_china_consumer_goods_retail）", lambda: ak.macro_china_consumer_goods_retail())
        financing_sources = []
        source_errors = []
        financing_status = {}
        try:
            financing_sources.append(_call_akshare("社融（macro_china_shrzgm）", lambda: ak.macro_china_shrzgm()))
            financing_status["akshare"] = "ok"
        except DataUpdateError as error:
            source_errors.append(str(error))
            financing_status["akshare"] = "unavailable"
        try:
            financing_sources.append(fetch_social_financing_direct())
            financing_status["mofcom"] = "ok"
        except DataUpdateError as error:
            source_errors.append(str(error))
            financing_status["mofcom"] = "unavailable"
        try:
            # PBC data is the latest official release and should replace overlapping values.
            financing_sources.append(fetch_pbc_social_financing())
            financing_status["pbc"] = "ok"
        except DataUpdateError as error:
            source_errors.append(str(error))
            financing_status["pbc"] = "unavailable"
        financing = merge_social_financing(*financing_sources)
        if not financing:
            raise DataUpdateError("社融来源暂时不可用。" + "；".join(source_errors))
        ppi = indexed_values(ppi_frame, ("当月同比增长", "同比增长", "当月同比"), ("月份", "时间", "日期"))
        retail = retail_values(retail_frame)
        gdp = {}
        gdp_errors = []
        try:
            gdp_frame = _call_akshare("GDP（macro_china_gdp）", lambda: ak.macro_china_gdp())
            gdp_cumulative = quarterly_values(gdp_frame, ("国内生产总值-绝对值", "国内生产总值", "GDP"))
            gdp = cumulative_gdp_to_quarters(gdp_cumulative)
        except DataUpdateError as error:
            gdp_errors.append(str(error))
        try:
            official_gdp = fetch_nbs_gdp()
            if not official_gdp:
                raise DataUpdateError("国家统计局报告没有 GDP 记录")
            gdp_source = "国家统计局季度报告" + ("（AkShare 补充历史）" if gdp else "")
            gdp.update(official_gdp)
        except DataUpdateError as error:
            gdp_errors.append(str(error))
            gdp_source = "AkShare macro_china_gdp（国家统计局报告暂不可用）"
        if not gdp:
            raise DataUpdateError("GDP 数据源暂时不可用。" + "；".join(gdp_errors))
        hsi_frame = _call_akshare("恒生指数（stock_hk_index_daily_sina）", lambda: ak.stock_hk_index_daily_sina(symbol="HSI"))
        hsi_rows = records(hsi_frame)
        date_col = find_column(hsi_rows, ("date", "日期", "时间"))
        close_col = find_column(hsi_rows, ("close", "收盘"))
        hsi = {}
        for row in hsi_rows:
            try:
                month = month_of(row[date_col])
                close = number(row[close_col])
            except (ValueError, TypeError):
                continue
            if close is not None and (month not in hsi or str(row[date_col]) >= str(hsi.get(month + "_date", ""))):
                hsi[month] = close
                hsi[month + "_date"] = str(row[date_col])
        hsi = {key: value for key, value in hsi.items() if re.fullmatch(r"\d{4}-\d{2}", key)}
        return {
            "ppi": ppi,
            "retail": retail,
            "financing": financing,
            "gdp": gdp,
            "hsi": hsi,
            "sources": {
                "social_financing": financing_status,
                "gdp": gdp_source,
            },
        }
    except DataUpdateError:
        raise
    except Exception as error:
        raise DataUpdateError("AkShare 数据抓取失败：%s" % error)


def _urlopen(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; HKLeadingIndicator/1.0)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read(), response.geturl(), response.headers.get("Content-Type", "")


def fetch_hkma_m2():
    try:
        content, _, _ = _urlopen(HKMA_XLS)
        import pandas as pd
        raw = pd.read_excel(io.BytesIO(content), sheet_name=0, header=None, engine="xlrd")
        frame = raw[[0, 1, 8]].copy()
        frame.columns = ["year", "month", "m2"]
        frame = frame.dropna(subset=["month", "m2"])
        frame["year"] = frame["year"].ffill()
        frame = frame[pd.to_numeric(frame["year"], errors="coerce").notna()]
        frame["m2"] = pd.to_numeric(frame["m2"], errors="coerce")
        frame["date"] = pd.to_datetime(
            frame["year"].astype(int).astype(str) + "-" + frame["month"].astype(str) + "-01",
            errors="coerce",
        ) + pd.offsets.MonthEnd(0)
        frame = frame.dropna(subset=["date", "m2"]).sort_values("date").drop_duplicates("date")
        frame["m2_yoy"] = frame["m2"].pct_change(12) * 100
        return {
            row.date.strftime("%Y-%m"): float(row.m2_yoy)
            for row in frame.itertuples()
            if pd.notna(row.m2_yoy)
        }
    except DataUpdateError:
        raise
    except Exception as error:
        raise DataUpdateError("金管局 Excel 下载或解析失败：%s" % error)


def _quarter_index(month):
    year, month_number = map(int, month.split("-"))
    return year * 4 + (month_number - 1) // 3


def calculate_credit(financing, gdp, month):
    year, month_number = map(int, month.split("-"))
    current = dt.date(year, month_number, 1)
    six_months = []
    for offset in range(6):
        index = current.year * 12 + current.month - 1 - offset
        item_year, item_month = divmod(index, 12)
        six_months.append("%04d-%02d" % (item_year, item_month + 1))
    prior = []
    for value in six_months:
        item_year, item_month = map(int, value.split("-"))
        prior.append("%04d-%02d" % (item_year - 1, item_month))
    missing_financing = [value for value in six_months + prior if value not in financing]
    if missing_financing:
        raise DataUpdateError("缺少社融月份：%s" % ", ".join(missing_financing))
    # Quarterly GDP is released around the 15th of the following month.
    latest_quarter = _quarter_index(month) - 1
    missing_quarters = [quarter for quarter in (latest_quarter, latest_quarter - 1) if quarter not in gdp]
    if missing_quarters:
        labels = ["%dQ%d" % (quarter // 4, quarter % 4 + 1) for quarter in missing_quarters]
        raise DataUpdateError("缺少最近两个已发布季度 GDP：" + ", ".join(labels))
    denominator = gdp[latest_quarter] + gdp[latest_quarter - 1]
    if denominator <= 0:
        raise DataUpdateError("名义 GDP 分母无效")
    numerator = sum(financing[item] for item in six_months) - sum(financing[item] for item in prior)
    return numerator / denominator * 100


def update_monthly_data(start, end):
    months = months_between(start, end)
    # Credit impulse needs a full prior-year comparison window outside the output interval.
    history_index = int(start[:4]) * 12 + int(start[5:7]) - 1 - 17
    history_year, history_month = divmod(history_index, 12)
    fetch_start = "%04d-%02d" % (history_year, history_month + 1)
    ak_data = fetch_akshare(fetch_start, end)
    m2_levels = fetch_hkma_m2()
    rows = []
    incomplete_months = 0
    for month in months:
        m2_yoy = m2_levels.get(month)
        values = {
            "m2": m2_yoy,
            "ppi": ak_data["ppi"].get(month),
            "retail": ak_data["retail"].get(month),
            "hsi": ak_data["hsi"].get(month),
        }
        missing = [name for name, value in values.items() if value is None]
        try:
            values["credit"] = calculate_credit(ak_data["financing"], ak_data["gdp"], month)
        except DataUpdateError as error:
            values["credit"] = None
            missing.append("credit")
            credit_error = str(error)
        else:
            credit_error = None
        if missing:
            incomplete_months += 1
        note = "自动更新：HKMA + AkShare"
        if ak_data.get("sources", {}).get("social_financing", {}).get("pbc") == "ok":
            note += " + 人民银行"
        if ak_data.get("sources", {}).get("gdp", "").startswith("国家统计局"):
            note += " + 国家统计局"
        if missing:
            note += "；缺少：" + ", ".join(missing)
        if credit_error:
            note += "；信用脉冲未计算：" + credit_error
        rows.append({"month": month, "values": [values["m2"], values["ppi"], values["retail"], values["credit"]], "hsi": values["hsi"], "note": note})
    return {
        "rows": rows,
        "months": len(months),
        "incomplete_months": incomplete_months,
        "sources": {
            "hkma_m2": "ok",
            "ppi": "AkShare macro_china_ppi",
            "retail": "AkShare macro_china_consumer_goods_retail",
            "hsi": "AkShare stock_hk_index_daily_sina",
            "credit": "ok",
            **ak_data.get("sources", {}),
        },
    }
