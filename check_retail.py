# -*- coding: utf-8 -*-
"""实测社零接口2020-2022年数据，确认1-2月合并结构"""
import warnings
warnings.filterwarnings("ignore")
import akshare as ak
import pandas as pd

df = ak.macro_china_consumer_goods_retail()
print("列:", list(df.columns))
print("总行数:", len(df), "| 起始:", df["月份"].iloc[0], "| 结束:", df["月份"].iloc[-1])
sub = df[df["月份"].str.contains("2020年|2021年|2022年", na=False)]
for _, r in sub.iterrows():
    print(r["月份"], "| 当月:", r["当月"], "| 同比增长:", r["同比增长"], "| 累计-同比增长:", r["累计-同比增长"])
