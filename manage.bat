@echo off
:: PeachTrees Media Studio 服务管理脚本
:: 本脚本以 GBK/ANSI 编码保存，确保中文在 Windows 控制台正常显示
title PeachTrees 服务管理工具

:: 检查 Python 是否安装
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未在系统 PATH 中检测到 python 可执行工具。
    echo 请确认已激活对应的 conda 环境（含 fastapi 依赖）或 python 已加入系统环境变量。
    pause
    exit /b 1
)

:: 检查 manage.py 是否在同级目录
if not exist "%~dp0\manage.py" (
    echo [错误] 未在同级目录中找到 manage.py 脚本。
    pause
    exit /b 1
)

:: 如果未带参数启动，进入交互式菜单；带参数则直接执行对应操作
if "%~1"=="" (
    goto MENU
)

:: 带参数直接执行对应操作
python "%~dp0\manage.py" %*
set "rc=%errorlevel%"
if /i "%~1"=="start" if "%rc%"=="0" (
    start "" "http://localhost:5173"
)
if /i "%~1"=="restart" if "%rc%"=="0" (
    start "" "http://localhost:5173"
)
exit /b %rc%

:MENU
cls
echo =================================================
echo        PeachTrees 服务管理工具
echo =================================================
echo  [1] 启动前后端服务
echo  [2] 关闭前后端服务
echo  [3] 重启前后端服务
echo  [4] 查看服务运行状态
echo  [5] 退出管理器
echo =================================================
echo.
set "choice="
set /p choice=请输入你的选择 [1-5] 然后回车:

if "%choice%"=="1" (
    echo.
    python "%~dp0\manage.py" start
    if "%errorlevel%"=="0" start "" "http://localhost:5173"
    echo.
    echo 操作完成，返回主菜单...
    pause >nul
    goto MENU
)
if "%choice%"=="2" (
    echo.
    python "%~dp0\manage.py" stop
    echo.
    echo 操作完成，返回主菜单...
    pause >nul
    goto MENU
)
if "%choice%"=="3" (
    echo.
    python "%~dp0\manage.py" restart
    if "%errorlevel%"=="0" start "" "http://localhost:5173"
    echo.
    echo 操作完成，返回主菜单...
    pause >nul
    goto MENU
)
if "%choice%"=="4" (
    echo.
    python "%~dp0\manage.py" status
    echo.
    echo 操作完成，返回主菜单...
    pause >nul
    goto MENU
)
if "%choice%"=="5" (
    exit /b 0
)

echo.
echo [错误] 输入无效，请输入 1 到 5。
timeout /t 2 >nul
goto MENU
