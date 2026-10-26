# -*- coding: utf-8 -*-
"""验证页面图表黑线Z值序列与表格数值"""
import requests, json, re
r = requests.get("http://127.0.0.1:8000", timeout=150)
c = r.text
m = re.search(r'Plotly\.newPlot\(\s*["\']chart["\']\s*,\s*(\[.*?\])\s*,\s*\{', c, re.S)
if m:
    data = json.loads(m.group(1))
    for t in data:
        name = t.get("name", "")
        y = t.get("y", [])
        non_null = [v for v in y if v is not None]
        print("trace:", name, "| 点数:", len(y), "| 有效点:", len(non_null))
# 表格里2021-01行
i = c.find("2021-01-31")
print("--- 2021-01行上下文 ---")
seg = c[i:i+600]
import html as h
seg = re.sub(r"<[^>]+>", "|", seg)
print(seg[:400])
