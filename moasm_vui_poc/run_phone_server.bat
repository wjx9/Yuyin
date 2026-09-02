@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==================================================
echo   moasm_vui 手机互通 - 服务端一键启动
echo   (本机 = 服务端，手机 App 连这个地址)
echo ==================================================
echo.

REM ---- 1. 检测并请求管理员权限（放行防火墙需要）----
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [1/3] 需要管理员权限放行防火墙，正在弹出提权窗口...
    echo        请在 UAC 弹窗点"是"，然后在弹出的新窗口里会自动继续。
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" >nul
    echo        已请求提权。若没有新窗口弹出，请右键本脚本"以管理员身份运行"。
    pause
    exit /b
)

REM ---- 2. 放行防火墙 8000 入站 ----
echo [1/3] 放行 Windows 防火墙 8000 端口入站...
netsh advfirewall firewall delete rule name="moasm_vui_server_8000" >nul 2>&1
netsh advfirewall firewall add rule name="moasm_vui_server_8000" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1
if %errorlevel% equ 0 (
    echo        完成。手机连不上时可再确认防火墙"专用网络"已勾选。
) else (
    echo        [警告] 防火墙规则添加失败，请手动放行 TCP 8000 入站。
)
echo.

REM ---- 3. 显示局域网地址 ----
echo [2/3] 本机局域网地址（手机 App 设置页填下面的地址）：
powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | ForEach-Object { Write-Host ('    http://' + $_.IPAddress + ':8000') })"
echo.

REM ---- 4. 启动服务端 ----
echo [3/3] 启动服务端（监听 0.0.0.0:8000），Ctrl+C 停止 ...
echo.
.venv\Scripts\python.exe server_py\serve.py

echo.
echo 服务端已退出。
pause
endlocal
