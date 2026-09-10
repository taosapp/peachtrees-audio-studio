@echo off
:: PeachTrees Media Studio - Windows 依赖自动安装脚本
:: 跨平台安装脚本请使用 install_deps.sh（Linux/macOS）
chcp 65001 >nul
title PeachTrees 依赖安装程序

echo =================================================
echo        PeachTrees 声音克隆依赖一键安装工具
echo =================================================
echo.
echo [提示] 建议在激活的 Conda 环境（例如 fastapi）中运行此脚本。
echo.

:: 1. 检测 Python 和 pip
where python >nul 2>nul
if %errorlevel% neq 0 goto NO_PYTHON

where pip >nul 2>nul
if %errorlevel% neq 0 goto NO_PIP

:: 2. 选择安装模式 (CPU / GPU)
echo =================================================
echo 请选择您的运行硬件：
echo  [1] GPU (英伟达显卡/CUDA，支持极速推理 - 推荐)
echo  [2] CPU (普通处理器，运行较慢)
echo =================================================
set "mode="
set /p mode=请输入选项序号 [1-2] 并按回车: 

if "%mode%"=="1" goto INSTALL_GPU
if "%mode%"=="2" goto INSTALL_CPU
goto UNKNOWN_MODE

:INSTALL_GPU
echo.
echo [1/2] 正在安装 PyTorch 2.6.0 (CUDA 12.6 GPU版本)...
pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu126
if %errorlevel% neq 0 echo [警告] PyTorch GPU 版本安装失败，可能网络连接超时。将尝试安装普通依赖。
goto INSTALL_REQS

:INSTALL_CPU
echo.
echo [1/2] 跳过 PyTorch CUDA 版本安装，将自动安装标准版。
goto INSTALL_REQS

:INSTALL_REQS
echo.
echo [2/2] 正在从清华源安装其他核心业务和 CosyVoice 依赖包...
pip install -r "%~dp0\backend\requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple

if %errorlevel% equ 0 goto INSTALL_SUCCESS
goto INSTALL_FAIL

:INSTALL_SUCCESS
echo.
echo =================================================
echo  🎉 恭喜！PeachTrees 所有运行依赖已成功安装完成！
echo  现在您可以双击运行 [ manage.bat ] 开启您的声音克隆之旅。
echo =================================================
pause
exit /b 0

:INSTALL_FAIL
echo.
echo [错误] 部分依赖包安装失败，请检查上方网络输出或换源重试。
pause
exit /b 1

:NO_PYTHON
echo [错误] 未在系统 PATH 中找到 Python 解释器。
echo 请先安装 Python (推荐 3.10-3.12) 并添加至环境变量，或者激活 Conda 环境。
pause
exit /b 1

:NO_PIP
echo [错误] 未在系统 PATH 中找到 pip 管理工具。
pause
exit /b 1

:UNKNOWN_MODE
echo.
echo [错误] 输入无效，请输入数字 1 或 2。
timeout /t 2 >nul
goto :EOF
