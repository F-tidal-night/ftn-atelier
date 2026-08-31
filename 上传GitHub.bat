@echo off
chcp 65001 >nul
setlocal EnableExtensions
REM ============================================
REM FTN Atelier · 一键上传 GitHub
REM
REM 双击运行：检查变更 → 确认 → git add → 确认暂存 → commit → push origin main
REM 用法：上传GitHub.bat [仓库目录]（可选参数，默认脚本所在目录；测试用）
REM
REM 安全约定（本脚本绝不执行）：
REM   - 不使用 git push --force
REM   - 不执行 git reset --hard / git clean
REM   - 不自动处理 merge/rebase 冲突
REM   - 不上传 Release ZIP / 大文件 / 数据库 / 打包产物
REM   - 不创建 Tag / Release / 不修改版本号
REM   - 依赖现有 .gitignore（Database/ Logs/ Portable/ zip 均已忽略）
REM 任意一步失败立即停止，不继续后续操作。
REM ============================================

if "%~1"=="" ( set "REPO=%~dp0" ) else ( set "REPO=%~1" )
if not exist "%REPO%\.git\" (
    echo [错误] 不是 Git 仓库：%REPO%
    exit /b 1
)
cd /d "%REPO%"
set "GIT=git -c core.quotepath=false"

echo ============================================
echo   FTN Atelier · 上传 GitHub
echo   仓库：%REPO%
echo ============================================
echo.

REM ---------- 1) 检查 origin 是否指向 ftn-atelier ----------
set "ORIGIN="
%GIT% remote get-url origin > "%TEMP%\ftn_upload_origin.tmp" 2>nul
set /p ORIGIN=<"%TEMP%\ftn_upload_origin.tmp"
del "%TEMP%\ftn_upload_origin.tmp" >nul 2>nul
if "%ORIGIN%"=="" (
    echo [错误] 未配置远程仓库 origin。请先执行：
    echo   git remote add origin https://github.com/F-tidal-night/ftn-atelier.git
    exit /b 1
)
echo %ORIGIN% | findstr /i "F-tidal-night/ftn-atelier" >nul
if errorlevel 1 (
    echo [错误] origin 指向的不是 ftn-atelier 仓库：%ORIGIN%
    echo 期望：https://github.com/F-tidal-night/ftn-atelier.git
    exit /b 1
)
echo [1/7] 远程仓库检查通过：%ORIGIN%

REM ---------- 2) 当前分支 ----------
set "BRANCH="
%GIT% rev-parse --abbrev-ref HEAD > "%TEMP%\ftn_upload_branch.tmp" 2>nul
set /p BRANCH=<"%TEMP%\ftn_upload_branch.tmp"
del "%TEMP%\ftn_upload_branch.tmp" >nul 2>nul
if "%BRANCH%"=="" set "BRANCH=未知"
echo [2/7] 当前分支：%BRANCH%（将推送到 origin/main）

REM ---------- 3) 显示变更 ----------
echo.
echo [3/7] 当前变更（git status --short）：
%GIT% status --short
echo.
set "HAS_CHANGE="
%GIT% status --porcelain > "%TEMP%\ftn_upload_status.tmp" 2>nul
findstr /r /c:".*" "%TEMP%\ftn_upload_status.tmp" >nul 2>nul
if not errorlevel 1 set "HAS_CHANGE=1"
del "%TEMP%\ftn_upload_status.tmp" >nul 2>nul
if not defined HAS_CHANGE (
    echo.
    echo 没有需要上传的修改。
    exit /b 0
)

echo [4/7] 变更统计（git diff --stat）：
%GIT% diff --stat
echo.
echo 未跟踪文件（受 .gitignore 约束）：
%GIT% ls-files --others --exclude-standard

choice /c YN /m "确认继续上传以上变更？[Y/N]"
if errorlevel 2 exit /b 0

REM ---------- 5) git add . ----------
REM 默认只暂存「已被 Git 跟踪的文件」的修改和删除（git add -u）；
REM 未跟踪的新文件必须单独列出、用户明确确认后才加入。
%GIT% add -u
if errorlevel 1 (
    echo [错误] git add -u 失败，已停止。
    exit /b 1
)
echo.
echo [5/7] 已暂存：已被跟踪文件的修改 / 删除。

REM ---------- 5b) 未跟踪新文件：逐个确认后才加入（含 README 等新文件） ----------
%GIT% ls-files --others --exclude-standard > "%TEMP%\ftn_upload_untracked.tmp" 2>nul
findstr /r /c:".*" "%TEMP%\ftn_upload_untracked.tmp" >nul 2>nul
if not errorlevel 1 (
    echo.
    echo 以下为「未跟踪的新文件」（默认不会加入提交，将逐个确认）：
    type "%TEMP%\ftn_upload_untracked.tmp"
    echo.
    for /f "usebackq delims=" %%F in ("%TEMP%\ftn_upload_untracked.tmp") do (
        choice /c YN /m "是否加入未跟踪文件「%%F」？[Y/N]"
        if not errorlevel 2 (
            %GIT% add -- "%%F"
            if errorlevel 1 (
                echo [错误] 暂存未跟踪文件失败：%%F
                del "%TEMP%\ftn_upload_untracked.tmp" >nul 2>nul
                exit /b 1
            )
            echo   已加入：%%F
        ) else (
            echo   跳过：%%F
        )
    )
)
del "%TEMP%\ftn_upload_untracked.tmp" >nul 2>nul

echo.
echo 已暂存文件列表：
%GIT% diff --cached --name-only

REM ---------- 6) 大文件 / 敏感文件检测（发现即停止） ----------
set "BIG_HIT="
%GIT% diff --cached --name-only > "%TEMP%\ftn_upload_staged.tmp" 2>nul
for /f "usebackq delims=" %%F in ("%TEMP%\ftn_upload_staged.tmp") do (
    if /i "%%~xF"==".zip" ( set "BIG_HIT=1" & echo [警告] 检测到疑似不应上传的文件：%%F )
    if /i "%%~xF"==".exe" ( set "BIG_HIT=1" & echo [警告] 检测到疑似不应上传的文件：%%F )
    if /i "%%~xF"==".db" ( set "BIG_HIT=1" & echo [警告] 检测到疑似不应上传的文件：%%F )
    if /i "%%~xF"==".7z" ( set "BIG_HIT=1" & echo [警告] 检测到疑似不应上传的文件：%%F )
    if /i "%%~xF"==".rar" ( set "BIG_HIT=1" & echo [警告] 检测到疑似不应上传的文件：%%F )
    if /i "%%~xF"==".tar" ( set "BIG_HIT=1" & echo [警告] 检测到疑似不应上传的文件：%%F )
    if /i "%%~xF"==".gz" ( set "BIG_HIT=1" & echo [警告] 检测到疑似不应上传的文件：%%F )
    if /i "%%~xF"==".pak" ( set "BIG_HIT=1" & echo [警告] 检测到疑似不应上传的文件：%%F )
    if /i "%%~xF"==".dat" ( set "BIG_HIT=1" & echo [警告] 检测到疑似不应上传的文件：%%F )
    if /i "%%~xF"==".bin" ( set "BIG_HIT=1" & echo [警告] 检测到疑似不应上传的文件：%%F )
)
del "%TEMP%\ftn_upload_staged.tmp" >nul 2>nul
if defined BIG_HIT (
    echo.
    echo [错误] 暂存列表中包含大文件 / 数据库 / 打包产物，已停止提交。
    echo 请检查 .gitignore，或取消暂存后重试（git reset 仅取消暂存，不影响文件）。
    exit /b 1
)

choice /c YN /m "确认暂存内容无误，继续提交？[Y/N]"
if errorlevel 2 exit /b 0

REM ---------- 7) commit message（默认：Update: yyyy-MM-dd HH:mm） ----------
echo.
set "DEFAULT_MSG="
powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm'" > "%TEMP%\ftn_upload_date.tmp" 2>nul
set /p DEFAULT_MSG=<"%TEMP%\ftn_upload_date.tmp"
del "%TEMP%\ftn_upload_date.tmp" >nul 2>nul
set "DEFAULT_MSG=Update: %DEFAULT_MSG%"
echo 默认提交信息：%DEFAULT_MSG%
set /p "MSG=请输入自定义提交信息（直接回车用默认）："
if "%MSG%"=="" set "MSG=%DEFAULT_MSG%"

%GIT% commit -m "%MSG%"
if errorlevel 1 (
    echo [错误] git commit 失败（可能是没有用户信息或提交被拒绝），已停止。
    exit /b 1
)

REM ---------- 8) push origin main ----------
echo.
echo [6/7] 推送至 origin/main ...
%GIT% push origin main
if errorlevel 1 (
    echo [错误] git push 失败（网络 / 认证 / 冲突），未上传成功。请检查后重试。
    exit /b 1
)

REM ---------- 9) 成功 ----------
set "SHORT_HASH="
%GIT% rev-parse --short HEAD > "%TEMP%\ftn_upload_hash.tmp" 2>nul
set /p SHORT_HASH=<"%TEMP%\ftn_upload_hash.tmp"
del "%TEMP%\ftn_upload_hash.tmp" >nul 2>nul
echo.
echo [7/7] 上传成功！最新 commit：%SHORT_HASH%
echo 提交信息：%MSG%
echo.
pause
exit /b 0
