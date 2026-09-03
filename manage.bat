@echo off
:: PeachTrees Media Studio ��ݹ����ű�
:: ���ÿ���̨Ϊ UTF-8 ���룬��ֹ������ʾ����
title PeachTrees ������¡���������

:: ��� Python �Ƿ�װ
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [����] δ��ϵͳ PATH �м�⵽ python �����й��ߡ�
    echo ��ȷ���Ѽ�����Ӧ�� conda �������� fastapi������ python ������ϵͳ����������
    pause
    exit /b 1
)

:: ��� manage.py �Ƿ���ͬ��Ŀ¼
if not exist "%~dp0\manage.py" (
    echo [����] δ��ͬ��Ŀ¼���ҵ� manage.py �ű���
    pause
    exit /b 1
)

:: ���û�д������������뽻��ʽ�˵��������û�ֱ��˫������
if "%~1"=="" (
    goto MENU
)

:: ��������˲�������ֱ��ִ�ж�Ӧ�Ĳ���
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
echo        PeachTrees ������¡�����������
echo =================================================
echo  [1] ����ǰ��˷���
echo  [2] �ر�ǰ��˷���
echo  [3] ����ǰ��˷���
echo  [4] �鿴��������״̬
echo  [5] �˳�������
echo =================================================
echo.
set "choice="
set /p choice=������ѡ����� [1-5] �����س�:

if "%choice%"=="1" (
    echo.
    python "%~dp0\manage.py" start
    if "%errorlevel%"=="0" start "" "http://localhost:5173"
    echo.
    echo ��������������˵�...
    pause >nul
    goto MENU
)
if "%choice%"=="2" (
    echo.
    python "%~dp0\manage.py" stop
    echo.
    echo ��������������˵�...
    pause >nul
    goto MENU
)
if "%choice%"=="3" (
    echo.
    python "%~dp0\manage.py" restart
    if "%errorlevel%"=="0" start "" "http://localhost:5173"
    echo.
    echo ��������������˵�...
    pause >nul
    goto MENU
)
if "%choice%"=="4" (
    echo.
    python "%~dp0\manage.py" status
    echo.
    echo ��������������˵�...
    pause >nul
    goto MENU
)
if "%choice%"=="5" (
    exit /b 0
)

echo.
echo [����] ������Ч������������ 1 �� 5��
timeout /t 2 >nul
goto MENU
