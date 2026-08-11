@echo off
:: PeachTrees Media Studio 快捷管理脚本
:: 设置控制台为 UTF-8 编码，防止中文显示乱码
chcp 65001 >nul
title PeachTrees 声音克隆服务管理器

:: 检查 Python 是否安装
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未在系统 PATH 中检测到 python 命令行工具。
    echo 请确保已激活相应的 conda 环境（如 fastapi），或将 python 添加至系统环境变量。
    pause
    exit /b 1
)

:: 检查 manage.py 是否在同级目录
if not exist "%~dp0\manage.py" (
    echo [错误] 未在同级目录下找到 manage.py 脚本！
    pause
    exit /b 1
)

:: 如果没有传入参数，则进入交互式菜单，方便用户直接双击运行
if "%~1"=="" (
    goto MENU
)

:: 如果传入了参数，则直接执行对应的操作
python "%~dp0\manage.py" %*
exit /b %errorlevel%

:MENU
cls
echo =================================================
echo        PeachTrees 声音克隆服务管理工具
echo =================================================
echo  [1] 启动前后端服务
echo  [2] 关闭前后端服务
echo  [3] 重启前后端服务
echo  [4] 查看服务运行状态
echo  [5] 退出管理器
echo =================================================
echo.
set "choice="
set /p choice=请输入选项序号 [1-5] 并按回车: 

if "%choice%"=="1" (
    echo.
    python "%~dp0\manage.py" start
    echo.
    echo 按任意键返回主菜单...
    pause >nul
    goto MENU
)
if "%choice%"=="2" (
    echo.
    python "%~dp0\manage.py" stop
    echo.
    echo 按任意键返回主菜单...
    pause >nul
    goto MENU
)
if "%choice%"=="3" (
    echo.
    python "%~dp0\manage.py" restart
    echo.
    echo 按任意键返回主菜单...
    pause >nul
    goto MENU
)
if "%choice%"=="4" (
    echo.
    python "%~dp0\manage.py" status
    echo.
    echo 按任意键返回主菜单...
    pause >nul
    goto MENU
)
if "%choice%"=="5" (
    exit /b 0
)

echo.
echo [错误] 输入无效，请输入数字 1 到 5。
timeout /t 2 >nul
goto MENU
