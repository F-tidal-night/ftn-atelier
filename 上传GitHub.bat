@echo off
chcp 65001 >nul
setlocal EnableExtensions
REM ============================================
REM FTN Atelier · 一键上传 GitHub
REM
REM 双击运行，跟着提示走就行：
REM   查看改动 → 确认新文件 → 写提交说明 → 上传到 GitHub
REM 用法：上传GitHub.bat [仓库目录]（可选，默认本脚本所在文件夹）
REM
REM 安全约定（本脚本绝不执行）：
REM   - 不用 git push --force / reset --hard / clean
REM   - 不上传大文件（zip/exe/db 等会直接拦截）
REM   - 不创建 Tag / Release / 不修改版本号
REM   - 依赖 .gitignore（Database/ Logs/ Portable/ zip 已忽略）
REM 任何一步失败都会立即停止，绝不硬来。
REM ============================================

if "%~1"=="" ( set "REPO=%~dp0" ) else ( set "REPO=%~1" )
cd /d "%REPO%"
set "GIT=git -c core.quotepath=false"

REM ---------- 0) 检查 Git 是否安装 ----------
where git >nul 2>nul
if errorlevel 1 (
    echo.
    echo [提示] 没有找到 Git，无法上传。
    echo        请先安装 Git for Windows：https://git-scm.com/download/win
    echo        安装完成后重新运行本脚本。
    pause
    exit /b 1
)

if not exist ".git\" (
    echo.
    echo [提示] 这个文件夹还不是 Git 仓库，无法上传。
    echo        请在仓库根目录（包含 .git 文件夹）运行本脚本。
    pause
    exit /b 1
)

echo ============================================
echo   FTN Atelier · 一键上传 GitHub
echo ============================================
echo.

REM ---------- 1) 检查 / 自动配置远程仓库 ----------
set "ORIGIN="
%GIT% remote get-url origin > "%TEMP%\ftn_up_origin.tmp" 2>nul
set /p ORIGIN=<"%TEMP%\ftn_up_origin.tmp"
del "%TEMP%\ftn_up_origin.tmp" >nul 2>nul
if "%ORIGIN%"=="" (
    echo [1/6] 还没配置远程仓库，自动为你补上…
    %GIT% remote add origin https://github.com/F-tidal-night/ftn-atelier.git >nul 2>nul
    if errorlevel 1 (
        echo [错误] 自动配置失败，请手动执行下面这行再重试：
        echo   git remote add origin https://github.com/F-tidal-night/ftn-atelier.git
        pause
        exit /b 1
    )
    echo   ✓ 已配置：https://github.com/F-tidal-night/ftn-atelier.git
    set "ORIGIN=https://github.com/F-tidal-night/ftn-atelier.git"
) else (
    echo %ORIGIN% | findstr /i "F-tidal-night/ftn-atelier" >nul
    if errorlevel 1 (
        echo [1/6] 远程仓库指向的不是 ftn-atelier：
        echo   %ORIGIN%
        echo.
        echo 如果要上传到 FTN Atelier 仓库，请手动执行：
        echo   git remote set-url origin https://github.com/F-tidal-night/ftn-atelier.git
        pause
        exit /b 1
    )
    echo [1/6] 远程仓库：%ORIGIN%
)

set "BRANCH="
%GIT% rev-parse --abbrev-ref HEAD > "%TEMP%\ftn_up_branch.tmp" 2>nul
set /p BRANCH=<"%TEMP%\ftn_up_branch.tmp"
del "%TEMP%\ftn_up_branch.tmp" >nul 2>nul
if "%BRANCH%"=="" set "BRANCH=main"
echo         当前分支：%BRANCH%（将上传 main 分支到 GitHub）
echo.

REM ---------- 2) 查看改动 ----------
echo [2/6] 当前改动（下面的列表里，M=改过，D=删除，??=新文件）：
%GIT% status --short
echo.
%GIT% status --porcelain > "%TEMP%\ftn_up_status.tmp" 2>nul
findstr /r /c:".*" "%TEMP%\ftn_up_status.tmp" >nul 2>nul
if errorlevel 1 (
    echo   没有任何改动，无需上传。再见！
    del "%TEMP%\ftn_up_status.tmp" >nul 2>nul
    pause
    exit /b 0
)
del "%TEMP%\ftn_up_status.tmp" >nul 2>nul
echo.
%GIT% diff --stat
echo.

REM ---------- 3) 处理新文件（逐个确认） ----------
%GIT% ls-files --others --exclude-standard > "%TEMP%\ftn_up_new.tmp" 2>nul
findstr /r /c:".*" "%TEMP%\ftn_up_new.tmp" >nul 2>nul
if not errorlevel 1 (
    echo [3/6] 下面这些是「新文件」（比如新写的代码或 README），默认不上传：
    type "%TEMP%\ftn_up_new.tmp"
    echo.
    for /f "usebackq delims=" %%F in ("%TEMP%\ftn_up_new.tmp") do (
        choice /c YN /m "把「%%F」一起上传吗？按 Y 上传，N 跳过 [Y/N]"
        if not errorlevel 2 (
            %GIT% add -- "%%F" >nul 2>nul
            if errorlevel 1 (
                echo [错误] 加入「%%F」失败
                del "%TEMP%\ftn_up_new.tmp" >nul 2>nul
                pause
                exit /b 1
            )
            echo   ✓ 已加入：%%F
        ) else (
            echo   - 跳过：%%F
        )
    )
) else (
    echo [3/6] 没有需要确认的新文件。
)
del "%TEMP%\ftn_up_new.tmp" >nul 2>nul

REM 暂存已跟踪的修改 / 删除
%GIT% add -u
if errorlevel 1 (
    echo [错误] 暂存修改失败
    pause
    exit /b 1
)

REM ---------- 4) 大文件检查 + 最终确认 ----------
set "BIG_HIT="
%GIT% diff --cached --name-only > "%TEMP%\ftn_up_staged.tmp" 2>nul
for /f "usebackq delims=" %%F in ("%TEMP%\ftn_up_staged.tmp") do (
    if /i "%%~xF"==".zip" ( set "BIG_HIT=1" & echo [警告] 发现疑似不该上传的文件：%%F )
    if /i "%%~xF"==".exe" ( set "BIG_HIT=1" & echo [警告] 发现疑似不该上传的文件：%%F )
    if /i "%%~xF"==".db" ( set "BIG_HIT=1" & echo [警告] 发现疑似不该上传的文件：%%F )
    if /i "%%~xF"==".7z" ( set "BIG_HIT=1" & echo [警告] 发现疑似不该上传的文件：%%F )
    if /i "%%~xF"==".rar" ( set "BIG_HIT=1" & echo [警告] 发现疑似不该上传的文件：%%F )
    if /i "%%~xF"==".tar" ( set "BIG_HIT=1" & echo [警告] 发现疑似不该上传的文件：%%F )
    if /i "%%~xF"==".gz" ( set "BIG_HIT=1" & echo [警告] 发现疑似不该上传的文件：%%F )
    if /i "%%~xF"==".pak" ( set "BIG_HIT=1" & echo [警告] 发现疑似不该上传的文件：%%F )
    if /i "%%~xF"==".dat" ( set "BIG_HIT=1" & echo [警告] 发现疑似不该上传的文件：%%F )
    if /i "%%~xF"==".bin" ( set "BIG_HIT=1" & echo [警告] 发现疑似不该上传的文件：%%F )
)
del "%TEMP%\ftn_up_staged.tmp" >nul 2>nul
if defined BIG_HIT (
    echo.
    echo [错误] 上面这些文件（压缩包 / 程序 / 数据库等）不应该上传，已停止。
    echo        请检查 .gitignore，或先手动移走这些文件再重试。
    pause
    exit /b 1
)

echo.
echo [4/6] 即将提交并上传的内容：
%GIT% diff --cached --stat
echo.
choice /c YN /m "确认无误？按 Y 开始上传，N 取消 [Y/N]"
if errorlevel 2 (
    echo 已取消，没有上传任何内容。
    pause
    exit /b 0
)

REM ---------- 5) 写提交说明 ----------
echo.
echo [5/6] 写提交说明：
set "DEFAULT_MSG="
powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm'" > "%TEMP%\ftn_up_date.tmp" 2>nul
set /p DEFAULT_MSG=<"%TEMP%\ftn_up_date.tmp"
del "%TEMP%\ftn_up_date.tmp" >nul 2>nul
set "DEFAULT_MSG=Update: %DEFAULT_MSG%"
echo   默认说明：%DEFAULT_MSG%
set /p "MSG=直接回车用默认，或输入你自己的说明："
REM 防御：剥离可能混入的行尾回车/换行（个别输入方式会带 \r）
if defined MSG ( for /f "delims=" %%M in ("%MSG%") do set "MSG=%%M" )
if "%MSG%"=="" set "MSG=%DEFAULT_MSG%"

REM 先检查 Git 用户名 / 邮箱（不配好一定提交失败；缺了就当场引导设置一次）
set "GNAME="
%GIT% config user.name > "%TEMP%\ftn_up_name.tmp" 2>nul
set /p GNAME=<"%TEMP%\ftn_up_name.tmp"
del "%TEMP%\ftn_up_name.tmp" >nul 2>nul
set "GEMAIL="
%GIT% config user.email > "%TEMP%\ftn_up_email.tmp" 2>nul
set /p GEMAIL=<"%TEMP%\ftn_up_email.tmp"
del "%TEMP%\ftn_up_email.tmp" >nul 2>nul
set "NEED_USER="
if "%GNAME%"=="" set "NEED_USER=1"
if "%GEMAIL%"=="" set "NEED_USER=1"
if defined NEED_USER (
    echo.
    echo [提示] 还没有设置 Git 用户名/邮箱，现在设置一下（只需一次，会保存在这个仓库里）：
    set "NEW_NAME=FTN Studio"
    set /p "NEW_NAME=你的名字（直接回车用 FTN Studio）："
    set "NEW_EMAIL=ftn-studio@users.noreply.github.com"
    set /p "NEW_EMAIL=你的邮箱（直接回车用 GitHub 匿名邮箱）："
    %GIT% config user.name "%NEW_NAME%" >nul 2>nul
    %GIT% config user.email "%NEW_EMAIL%" >nul 2>nul
    REM 保存后校验一次，避免静默失败
    set "VERIFY="
    %GIT% config user.name > "%TEMP%\ftn_up_verify.tmp" 2>nul
    set /p VERIFY=<"%TEMP%\ftn_up_verify.tmp"
    del "%TEMP%\ftn_up_verify.tmp" >nul 2>nul
    if "%VERIFY%"=="" (
        echo [错误] 用户名/邮箱保存失败，请手动执行下面两条：
        echo   git config user.name "%NEW_NAME%"
        echo   git config user.email "%NEW_EMAIL%"
        pause
        exit /b 1
    )
    set "GNAME=%NEW_NAME%"
    set "GEMAIL=%NEW_EMAIL%"
    echo   ✓ 已保存：%NEW_NAME% ^< %NEW_EMAIL% ^>
    echo.
)

%GIT% commit -m "%MSG%" >nul 2>"%TEMP%\ftn_up_commit_err.tmp"
if errorlevel 1 (
    echo.
    echo [错误] 提交失败，GitHub 上不会有任何变化。
    type "%TEMP%\ftn_up_commit_err.tmp"
    del "%TEMP%\ftn_up_commit_err.tmp" >nul 2>nul
    pause
    exit /b 1
)
del "%TEMP%\ftn_up_commit_err.tmp" >nul 2>nul

REM ---------- 6) 推送到 GitHub ----------
echo.
echo [6/6] 正在上传到 GitHub（第一次会弹出 GitHub 登录窗口，按提示登录即可）…
%GIT% push origin main 2>"%TEMP%\ftn_up_push_err.tmp"
if errorlevel 1 (
    echo.
    echo [提示] 上传失败，GitHub 暂时没有收到你的改动。
    echo.
    type "%TEMP%\ftn_up_push_err.tmp"
    del "%TEMP%\ftn_up_push_err.tmp" >nul 2>nul
    echo.
    echo 常见解决办法：
    echo   - 如果弹出登录窗口：按提示登录即可（用户名 + 密码/令牌）；
    echo   - 如果提示 rejected / fetch first：说明 GitHub 上有新内容，先拉取再上传：
    echo       git pull origin main
    echo     然后重新运行本脚本；
    echo   - 如果提示认证失败：到 Windows「凭据管理器 → Windows 凭据」检查 GitHub 凭据。
    pause
    exit /b 1
)
del "%TEMP%\ftn_up_push_err.tmp" >nul 2>nul

set "SHORT_HASH="
%GIT% rev-parse --short HEAD > "%TEMP%\ftn_up_hash.tmp" 2>nul
set /p SHORT_HASH=<"%TEMP%\ftn_up_hash.tmp"
del "%TEMP%\ftn_up_hash.tmp" >nul 2>nul

echo.
echo ============================================
echo   ✅ 上传成功！
echo   提交说明：%MSG%
echo   最新版本号：%SHORT_HASH%
echo   现在 GitHub 上已经有你的代码了。
echo ============================================
echo.
pause
exit /b 0
