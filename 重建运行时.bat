@echo off
chcp 65001 >nul
REM ============================================
REM 重建内置 Python 运行时（Source\backend\runtime）
REM
REM 何时需要：
REM   - requirements.txt 有变更（新增/升级后端依赖）
REM   - 升级内置 Python 版本
REM   - runtime 缺失或损坏
REM
REM 步骤：下载嵌入式 Python 3.10.11 → 启用 site-packages →
REM       get-pip → 按 requirements.txt 从清华镜像安装依赖
REM 完成后重新运行「打包.bat」即可产出带新运行时的开箱即用包。
REM ============================================

cd /d %~dp0
set "ROOT=%CD%"
set "RT=%ROOT%\Source\backend\runtime"
set "TMPDIR=%TEMP%\ftn_pyembed"
set "EMBED_URL=https://npmmirror.com/mirrors/python/3.10.11/python-3.10.11-embed-amd64.zip"
set "PIP_URL=https://bootstrap.pypa.io/get-pip.py"
set "PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"

echo ============================================
echo   重建 FTN Atelier 内置 Python 运行时
echo ============================================
echo.

if exist "%RT%\python.exe" (
    choice /c YN /m "runtime 已存在，是否强制重建（Y=重建 / N=跳过）"
    if errorlevel 2 goto :EOF
)

echo [1/4] 准备临时目录...
if not exist "%TMPDIR%" mkdir "%TMPDIR%"
set "ZIP=%TMPDIR%\python-3.10.11-embed-amd64.zip"

echo [2/4] 下载嵌入式 Python 3.10.11 ...
if not exist "%ZIP%" (
    powershell -NoProfile -Command "Invoke-WebRequest -Uri '%EMBED_URL%' -OutFile '%ZIP%'"
    if errorlevel 1 goto :FAIL
)

echo [3/4] 解压并启用 site-packages ...
if exist "%RT%" rmdir /s /q "%RT%"
powershell -NoProfile -Command "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%RT%' -Force"
if errorlevel 1 goto :FAIL
for %%F in ("%RT%\python3*._pth") do (
    powershell -NoProfile -Command "$p='%%F'; (Get-Content $p) -replace '^#import site','import site' | Set-Content $p -Encoding ASCII"
)

echo [4/4] 安装 pip 与后端依赖（清华镜像）...
powershell -NoProfile -Command "if (-not (Test-Path '%TMPDIR%\get-pip.py')) { Invoke-WebRequest -Uri '%PIP_URL%' -OutFile '%TMPDIR%\get-pip.py' }"
"%RT%\python.exe" "%TMPDIR%\get-pip.py" --no-warn-script-location -i "%PIP_INDEX%"
if errorlevel 1 goto :FAIL
"%RT%\python.exe" -m pip install -r "%ROOT%\Source\backend\requirements.txt" --no-warn-script-location -i "%PIP_INDEX%"
if errorlevel 1 goto :FAIL

"%RT%\python.exe" -c "import sys, sqlite3, ssl; import fastapi, uvicorn, websockets, pydantic; print('RUNTIME_OK', sys.version.split()[0])"
if errorlevel 1 goto :FAIL

echo.
echo 运行时重建完成。现在运行「打包.bat」即可重新出包。
pause
exit /b 0

:FAIL
echo.
echo 运行时重建失败，请检查网络或上方错误信息。
pause
exit /b 1
