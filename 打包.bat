@echo off
chcp 65001 >nul
REM ============================================
REM FTN Atelier 打包脚本（Windows）
REM 只生成「开箱即用」便携版：
REM   Source\frontend\release\win-unpacked\FTN Atelier.exe
REM   → 压缩为工作区根目录 FTN-Atelier-Portable-1.0.0.zip
REM
REM 注意事项：
REM   - 打包需联网下载 electron-builder 工具，已配置 npmmirror 镜像
REM     （GitHub 直连不通时走镜像，首次会自动缓存，之后秒过）
REM   - 开箱即用版自带内置 Python 运行时（Source\backend\runtime），
REM     无需目标机安装 Python；若后端依赖有变更，先运行「重建运行时.bat」
REM     再打包
REM   - 运行打包产物（安装版或 win-unpacked）前务必确认
REM     ELECTRON_RUN_AS_NODE 已清空，否则 exe 会以纯 Node 运行、
REM     不开窗口直接退出（本脚本只负责打包，不负责启动）
REM ============================================

cd /d %~dp0
set "ROOT=%CD%"
cd /d "%ROOT%\Source\frontend"

REM 清掉会导致 electron 以纯 Node 运行的环境变量
set "ELECTRON_RUN_AS_NODE="
set "ELECTRON_ENABLE_LOGGING="

REM electron-builder 下载镜像（npmmirror）
set "ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/"
set "ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/"

echo ============================================
echo   FTN Atelier 打包（electron-builder NSIS）
echo ============================================
echo.

if not exist "node_modules" (
    echo [1/3] 正在安装前端依赖...
    call npm install
) else (
    echo [1/3] 前端依赖已就绪
)

echo [2/3] 构建前端 + 打包免安装版...
call npm run build:prod
if errorlevel 1 (
    echo.
    echo 打包失败，请查看上方错误信息。
    pause
    exit /b 1
)

echo [3/3] 生成便携版 zip（解压即用，自带 Python 运行时）...
if exist "%ROOT%\Source\frontend\release\win-unpacked" (
    tar.exe -a -c -f "%ROOT%\FTN-Atelier-Portable-1.0.0.zip" -C "%ROOT%\Source\frontend\release\win-unpacked" .
)
if exist "%ROOT%\Source\frontend\release\win-unpacked" rmdir /s /q "%ROOT%\Source\frontend\release\win-unpacked"

echo.
echo 打包完成。
echo.
echo 便携版已放至工作区根目录：
echo   %ROOT%\FTN-Atelier-Portable-1.0.0.zip
echo   解压后运行 FTN Atelier.exe 即可，无需安装、无需系统 Python。
echo.
echo （win-unpacked 为中间产物，打包后已自动清理）
echo.
echo 提示：打包版数据写入 %%APPDATA%%\ftn-studio-frontend（Database/Logs），
echo       与开发模式的源码目录数据相互独立。
echo.
pause
