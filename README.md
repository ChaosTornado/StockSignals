# 港股领航指标网页

基于港股领航指标计算模板的指标说明与历史数据制作。页面包含趋势图、阈值信号、指标摘要和可编辑的月度数据表。顶部“数据来源”标签页直接读取 `docs/数据获取来源.md`，展示各指标来源、官方链接和信用脉冲计算步骤；修改文档后再次打开标签页即可看到更新内容。

## 启动

应用需要 Python 3。在项目目录运行：

    python3 server.py --host 0.0.0.0 --port 4174

然后访问 <http://localhost:4174>。如果 4174 已被其他服务占用，可改用 `--port 4175` 并访问对应地址。首次启动会在工程目录的 `data/data.csv` 创建 CSV 文件。

## Nginx 子路径部署

在部署服务器启动 Python 服务：`python3 server.py --host 127.0.0.1 --port 4174`。
前端根据 `app.js` 的地址自动识别应用路径，支持根路径或 `/stocksignals/`。
将下面配置放进现有站点的 `server { ... }` 内（Nginx 与 Python 服务在同一机器时）：

```nginx
location = /stocksignals {
    return 301 /stocksignals/$is_args$args;
}

location ^~ /stocksignals/ {
    proxy_pass http://127.0.0.1:4174/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 10s;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    client_max_body_size 10m;
    proxy_cache off;
}
```

`proxy_pass` 的尾部 `/` 会移除应用前缀，例如 `/stocksignals/api/data` 转发为 `/api/data`。
`proxy_read_timeout` 留足宏观数据自动更新所需时间。
执行 `sudo nginx -t && sudo systemctl reload nginx` 后，通过站点的 `/stocksignals/` 访问。

## 指标逻辑

- 港元 M2 同比、内地 PPI 同比、内地社零同比和信用脉冲各占 25%，四项齐全时计算等权平均。
- 按所有完整月份计算均值和样本标准差。高于“均值 + 阈值系数 × 标准差”显示“警惕顶部”；低于“均值 − 阈值系数 × 标准差”显示“关注底部”；其余为“中性”。
- 图表以标准分呈现领航指标，并与恒生指数月末收盘价双轴对照；另有港元 M2 同比与恒生指数的双轴趋势图。两张图都支持全部、3 年和 1 年视图。
- 月度数据唯一来源为工程目录的 `data/data.csv`。服务通过 GET /api/data 读取，通过 PUT /api/data 原子写入；GET /data/data.csv 可直接查看 CSV 内容。
- 表格中的黄色单元格可编辑；修改后会写入服务端 CSV，其他浏览器刷新后也会读到新值。可筛选信号月份、搜索月份和导出 CSV。
- 如需使用其他 CSV 路径，可设置 HK_INDICATOR_CSV=/your/path/data.csv 后再启动服务。
- 月度数据录入区支持自动更新：输入 `14/6-26/10` 或 `2014-06/2026-10` 后点击“更新数据”。更新范围会重建为完整月份，并覆盖写入 `data/data.csv`；范围外月份会被移除。
- 自动更新需要 Python 3.8+、AkShare 1.x 和表格解析库：`python3 -m pip install -r requirements.txt`。依赖或关键数据源整体不可用时，更新失败且不会修改 CSV；单个月份缺少部分数据时仍会写入该月份，缺失字段保持为空并在备注中标明。香港金管局数据使用官方 `T020201.xls`，可通过 `HKMA_M2_URL` 覆盖下载地址。
- 自动更新的数据源包括 AkShare（PPI、社零、社融、GDP 历史序列、恒生指数）、人民银行社融官方月表、国家统计局季度 GDP 报告，以及香港金管局官方 Excel（港元 M2）。社融按 AkShare、商务部 `shrzgmQuery`、人民银行官方表合并，人民银行数据覆盖重叠月份；国家统计局报告中的 GDP 单季现价绝对额覆盖 AkShare 的近期 GDP 值。信用脉冲按当月及前 5 个月社融增量与去年同期差额，除以当月月底前已发布的最近两个季度名义 GDP 之和，再乘 100 计算。季度 GDP 按季后次月发布处理；无法计算的单月信用脉冲会留空。

当前 CSV 初始化数据覆盖 2021-01 至 2027-12。需要扩展或重抓历史月份时，可在页面输入时间范围自动更新；也可继续在表格中手动编辑个别数据。
