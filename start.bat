@echo off
chcp 65001 >nul
cd /d D:\Projects\StockSignals
echo 正在启动港股领航指标看板...
echo 启动后请勿关闭本窗口，关闭窗口即停止服务。
echo 浏览器将自动打开 http://127.0.0.1:8000
start "" http://127.0.0.1:8000
python hk_lead_index_web.py
pause
