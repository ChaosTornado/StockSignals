# -*- coding: utf-8 -*-
"""验证社零1-2月填充 + 2021-01起领航指标/Z值"""
import warnings
warnings.filterwarnings("ignore")
import hk_lead_index_web as m
import pandas as pd

r = m.get_retail()
print("社零 2020-2022 首季度:")
print(r[(r["date"]>="2020-12-01")&(r["date"]<="2022-03-31")].to_string())

h = m.get_hsi_monthly(); p = m.get_ppi(); m2 = m.get_hkd_m2_yoy()
s = m.get_social_finance(); g = m.get_gdp_nominal()
cp = m.calc_credit_pulse(s, g)
df_all = p
for d in [r, m2, cp, h]:
    df_all = pd.merge(df_all, d, on="date", how="outer")
df_all = df_all.sort_values("date").reset_index(drop=True)
df_all = df_all[df_all["date"] >= m.START_DATE].copy()
df_all["lead_raw"] = (0.25*df_all["m2_hkd_yoy"] + 0.25*df_all["ppi_yoy"]
                      + 0.25*df_all["retail_yoy"] + 0.25*df_all["credit_pulse"])
df_all["lead_z"] = m.rolling_zscore(df_all["lead_raw"])
print()
print("总行数:", len(df_all), df_all["date"].min().date(), "→", df_all["date"].max().date())
print("2021年首3行:")
print(df_all[df_all["date"]>="2021-01-01"].head(3)[["date","m2_hkd_yoy","ppi_yoy","retail_yoy","credit_pulse","lead_raw","lead_z","hsi_close"]].round(2).to_string())
print()
print("Z值有效区:", df_all.dropna(subset=["lead_z"])["date"].min().date(), "→", df_all.dropna(subset=["lead_z"])["date"].max().date(), "| 有效行数:", df_all["lead_z"].notna().sum())
print("lead_raw有效区:", df_all.dropna(subset=["lead_raw"])["date"].min().date(), "→", df_all.dropna(subset=["lead_raw"])["date"].max().date())
