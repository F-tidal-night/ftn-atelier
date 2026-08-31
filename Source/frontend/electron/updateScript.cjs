// ============================================
// 生成「应用更新」的 PowerShell 脚本（由独立进程在主程序退出后执行）。
// 逻辑：备份旧程序（排除 Core/Data/Database/Logs）→ 解压新版 → 校验关键 exe
//       → 成功清理备份并启动新版；失败删除半成品、恢复旧程序并弹窗提示；
//       恢复失败时保留备份。测试可设环境变量 FTN_UPDATE_NO_UI=1 跳过弹窗。
// ============================================

const psq = (s) => "'" + String(s).replace(/'/g, "''") + "'"

function buildUpdateScript({ zip, appRoot, backup }) {
  return [
    "$ErrorActionPreference = 'Continue'",
    'Start-Sleep -Seconds 3',
    `$root = ${psq(appRoot)}`,
    `$zip = ${psq(zip)}`,
    `$backup = ${psq(backup)}`,
    `$keep = @('Core','Data','Database','Logs')`,
    `$log = Join-Path $root 'Data\\updates\\apply.log'`,
    'try {',
    '  New-Item -ItemType Directory -Force -Path $backup | Out-Null',
    '  # 1) 备份旧程序文件（排除用户数据目录）',
    '  Get-ChildItem -LiteralPath $root -Force | Where-Object { $_.Name -notin $keep } | ForEach-Object {',
    '    Move-Item -LiteralPath $_.FullName -Destination $backup -Force -ErrorAction Stop',
    '  }',
    '  # 2) 解压新版（Windows 自带 tar 支持 zip；包内为顶层文件）',
    '  & tar.exe -xf $zip -C $root',
    '  if ($LASTEXITCODE -ne 0) { throw "ZIP 解压失败（exit=$LASTEXITCODE）" }',
    '  # 3) 校验新版关键文件',
    "  $exe = Join-Path $root 'FTN Atelier.exe'",
    "  if (-not (Test-Path -LiteralPath $exe)) { throw '更新包缺少主程序 FTN Atelier.exe' }",
    '  # 4) 成功：启动新版，清理临时备份 / 待应用标记（脚本自身保留，下次更新前清理）',
    '  try { Start-Process -FilePath $exe -WorkingDirectory $root -ErrorAction SilentlyContinue } catch {}',
    '  Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue',
    "  Remove-Item -LiteralPath (Join-Path $root 'Data\\updates\\pending.json') -Force -ErrorAction SilentlyContinue",
    `  'OK' | Out-File -FilePath $log -Encoding utf8`,
    '  exit 0',
    '} catch {',
    '  $err = $_.Exception.Message',
    '  # 失败：删除不完整的新程序，恢复旧程序',
    '  Get-ChildItem -LiteralPath $root -Force | Where-Object { $_.Name -notin $keep } | ForEach-Object {',
    '    Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue',
    '  }',
    '  $restored = $true',
    '  if (Test-Path -LiteralPath $backup) {',
    '    Get-ChildItem -LiteralPath $backup -Force | ForEach-Object {',
    '      try { Move-Item -LiteralPath $_.FullName -Destination $root -Force -ErrorAction Stop }',
    '      catch { $restored = $false }',
    '    }',
    '  }',
    "  $msg = \"更新失败：$err`n备份位置：$backup`n恢复旧版本：$(if ($restored) {'成功'} else {'失败（备份已保留，请勿删除）'})\"",
    '  $msg | Out-File -FilePath $log -Encoding utf8',
    "  if ($env:FTN_UPDATE_NO_UI -ne '1') {",
    '    try { Add-Type -AssemblyName PresentationFramework -ErrorAction Stop; [System.Windows.MessageBox]::Show($msg, "FTN Atelier 更新", "OK", "Warning") | Out-Null } catch {}',
    '  }',
    "  if ($restored -and (Test-Path -LiteralPath (Join-Path $root 'FTN Atelier.exe'))) {",
    '    try { Start-Process -FilePath (Join-Path $root "FTN Atelier.exe") -WorkingDirectory $root -ErrorAction SilentlyContinue } catch {}',
    '  }',
    '  exit 1',
    '}',
  ].join('\r\n')
}

module.exports = { buildUpdateScript }
