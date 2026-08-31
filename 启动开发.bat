@echo off
chcp 65001 >nul
REM ============================================
REM FTN Studio 开发启动脚本 (Windows)
REM
REM 自动处理 ELECTRON_RUN_AS_NODE 环境变量问题，
REM 该变量若存在会导致 electron.exe 以纯 Node 运行，
REM 而非 Electron 主进程（app 未定义错误）。
REM ============================================

cd /d %~dp0
set "ROOT=%CD%"
cd /d "%ROOT%\Source\frontend"

REM 移除可能导致 electron 以纯 Node 运行的环境变量
set "ELECTRON_RUN_AS_NODE="
set "ELECTRON_ENABLE_LOGGING="

echo ============================================
echo   FTN Studio 开发模式启动
echo ============================================
echo.

REM 检查依赖是否已安装
if not exist "node_modules" (
    echo [1/3] 正在安装前端依赖...
    call npm install
) else (
    echo [1/3] 前端依赖已就绪
)

echo [2/3] 构建前端...
call npm run build

echo [3/3] 启动 Electron...
start "" "%ROOT%\Source\frontend\node_modules\electron\dist\electron.exe" "%ROOT%\Source\frontend"

echo.
echo 已启动。关闭 FTN Studio 窗口即可退出。
echo 后端服务会随窗口关闭自动清理。
echo.
pause
