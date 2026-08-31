// ============================================
// 生成「应用更新」的 PowerShell 脚本（由独立进程在主程序退出后执行）。
//
// 安全顺序：
//   1) 立即写 updater-started.log（Electron 握手用，确认更新器已真正启动）
//   2) 等待 FTN Atelier.exe 进程完全退出（最多 90 秒），退出后再等 2 秒释放文件句柄
//   3) 备份旧程序文件（排除 Core/Data/Database/Logs；个别文件偶发占用自动重试 6 次）
//   4) 解压新版 → 校验 FTN Atelier.exe
//   5) 成功：清理临时备份 / pending.json，启动新版
//   6) 失败：只删除「解压产生的文件」，再从备份恢复旧程序；
//      恢复失败时保留备份并明确提示。等待主程序退出超时则不做任何改动。
// ============================================

const psq = (s) => "'" + String(s).replace(/'/g, "''") + "'"

function buildUpdateScript({ zip, appRoot, backup }) {
  return [
    "$ErrorActionPreference = 'Continue'",
    `$root = ${psq(appRoot)}`,
    `$zip = ${psq(zip)}`,
    `$backup = ${psq(backup)}`,
    `$keep = @('Core','Data','Database','Logs')`,
    `$exe = Join-Path $root 'FTN Atelier.exe'`,
    `$log = Join-Path $root 'Data\\updates\\apply.log'`,
    `$stageLog = Join-Path $root 'Data\\updates\\updater-started.log'`,
    "function Write-Stage(\$m) { Add-Content -LiteralPath \$stageLog -Value (\"[{0}] {1}\" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), \$m) -Encoding UTF8 -ErrorAction SilentlyContinue }",
    "Write-Stage 'updater 开始'",
    // ---- 等待主程序完全退出（90 秒超时，超时则不做任何改动） ----
    "Write-Stage '等待主程序退出（最多 90 秒）'",
    "$exited = $false",
    "$deadline = (Get-Date).AddSeconds(90)",
    "while ((Get-Date) -lt $deadline) {",
    "  $running = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -eq 'FTN Atelier' -or $_.Path -eq $exe })",
    "  if ($running.Count -eq 0) { $exited = $true; break }",
    "  Start-Sleep -Milliseconds 500",
    "}",
    "if (-not $exited) {",
    "  $msg = '更新失败：等待主程序退出超时（90 秒）。请手动关闭 FTN Atelier 后重试更新。'",
    "  $msg | Out-File -FilePath $log -Encoding utf8",
    "  Write-Stage '等待超时，未做任何改动'",
    "  if ($env:FTN_UPDATE_NO_UI -ne '1') { try { Add-Type -AssemblyName PresentationFramework -ErrorAction Stop; [System.Windows.MessageBox]::Show($msg, 'FTN Atelier 更新', 'OK', 'Warning') | Out-Null } catch {} }",
    "  exit 1",
    "}",
    "Write-Stage '主程序已退出，等待句柄释放'",
    "Start-Sleep -Seconds 2",
    // ---- 备份旧程序（失败可重试，避免偶发句柄占用直接失败） ----
    "$extracted = $false",
    "try {",
    "  Write-Stage '开始备份'",
    "  New-Item -ItemType Directory -Force -Path $backup | Out-Null",
    "  for ($attempt = 1; $attempt -le 6; $attempt++) {",
    "    $failed = $false",
    "    try {",
    "      Get-ChildItem -LiteralPath $root -Force | Where-Object { $_.Name -notin $keep } | ForEach-Object {",
    "        $dest = Join-Path $backup $_.Name",
    "        if (-not (Test-Path -LiteralPath $dest)) { Move-Item -LiteralPath $_.FullName -Destination $backup -Force -ErrorAction Stop }",
    "      }",
    "    } catch { $failed = $true; Start-Sleep -Seconds 1 }",
    "    if (-not $failed) { break }",
    "  }",
    "  $left = @(Get-ChildItem -LiteralPath $root -Force | Where-Object { $_.Name -notin $keep })",
    "  if ($left.Count -gt 0) { throw ('备份失败，仍有文件被占用：' + ($left.Name -join ', ')) }",
    "  Write-Stage '备份完成'",
    "  Write-Stage 'tar 开始'",
    "  & tar.exe -xf $zip -C $root",
    "  Write-Stage ('tar 退出码: ' + $LASTEXITCODE)",
    "  if ($LASTEXITCODE -ne 0) { throw \"ZIP 解压失败（exit=$LASTEXITCODE）\" }",
    "  $extracted = $true",
    "  Write-Stage 'exe 校验'",
    "  if (-not (Test-Path -LiteralPath $exe)) { throw '更新包缺少主程序 FTN Atelier.exe' }",
    "  Write-Stage '启动新版'",
    "  try { Start-Process -FilePath $exe -WorkingDirectory $root -ErrorAction SilentlyContinue } catch {}",
    "  Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue",
    "  Remove-Item -LiteralPath (Join-Path $root 'Data\\updates\\pending.json') -Force -ErrorAction SilentlyContinue",
    "  Write-Stage '清理完成'",
    "  'OK' | Out-File -FilePath $log -Encoding utf8",
    "  Write-Stage '更新成功'",
    "  exit 0",
    "} catch {",
    "  Write-Stage ('失败原因: ' + $_.Exception.Message)",
    "  $err = $_.Exception.Message",
    // 只有解压确实开始过，根目录里未保留项才都是新解压的文件，才允许删除
    "  if ($extracted) {",
    "    Get-ChildItem -LiteralPath $root -Force | Where-Object { $_.Name -notin $keep } | ForEach-Object {",
    "      Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue",
    "    }",
    "  }",
    "  $restored = $true",
    "  if (Test-Path -LiteralPath $backup) {",
    "    Get-ChildItem -LiteralPath $backup -Force | ForEach-Object {",
    "      try { Move-Item -LiteralPath $_.FullName -Destination $root -Force -ErrorAction Stop }",
    "      catch { $restored = $false; Write-Stage ('恢复失败: ' + $_.Exception.Message) }",
    "    }",
    "  }",
    "  $msg = \"更新失败：$err`n备份位置：$backup`n恢复旧版本：$(if ($restored) {'成功'} else {'失败（备份已保留，请勿删除）'})\"",
    "  $msg | Out-File -FilePath $log -Encoding utf8",
    "  Write-Stage ('恢复旧版本: ' + $(if ($restored) {'成功'} else {'失败'}))",
    "  if ($env:FTN_UPDATE_NO_UI -ne '1') {",
    "    try { Add-Type -AssemblyName PresentationFramework -ErrorAction Stop; [System.Windows.MessageBox]::Show($msg, 'FTN Atelier 更新', 'OK', 'Warning') | Out-Null } catch {}",
    "  }",
    "  if ($restored -and (Test-Path -LiteralPath $exe)) {",
    "    try { Start-Process -FilePath $exe -WorkingDirectory $root -ErrorAction SilentlyContinue } catch {}",
    "  }",
    "  if ($restored -and (Test-Path -LiteralPath $backup)) { Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue }",
    "  exit 1",
    "}",
  ].join('\r\n')
}

module.exports = { buildUpdateScript }
