# -*- coding: utf-8 -*-
"""解析页面数据表，验证2021-01行领航指标数值"""
import requests, re
import pandas as pd
r = requests.get("http://127.0.0.1:8000", timeout=150)
c = r.text
m = re.search(r'<table[^>]*class="[^"]*data-table[^"]*"[^>]*>.*?</table>', c, re.S)
if m:
    df = pd.read_html(m.group(0))[0]
    print("表格行数:", len(df))
    cols = list(df.columns)
    print("列:", cols)
    for y in ["2021", "2024", "2026"]:
        sub = df[df["月份"].astype(str).str.startswith(y)]
        print(sub.head(3).to_string())
else:
    print("未找到数据表")
