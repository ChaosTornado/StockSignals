# -*- coding: utf-8 -*-
"""检查页面表格HTML结构"""
import requests
r = requests.get("http://127.0.0.1:8000", timeout=150)
c = r.text
i = c.find("data-table")
print("data-table at:", i)
if i > 0:
    print(repr(c[i-300:i+500]))
j = c.find("领航指标(原始)")
print("领航指标(原始) at:", j)
print(repr(c[j-200:j+400]))
