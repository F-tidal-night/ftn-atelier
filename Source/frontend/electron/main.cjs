// ============================================
// FTN Studio Electron 主进程入口
//
// 生命周期流程：
// Electron 启动
//   → 检查单实例锁（多开保护）
//   → 拉起/连接 FastAPI 后端
//   → 创建主窗口
//   → 建立 WebSocket(由渲染进程发起)
// Electron 退出
//   → 通知后端关闭
//   → 释放 pid/lock
//   → 清理异常残留进程
// ============================================

const electron = require('electron')
const { app, BrowserWindow, ipcMain, dialog, screen, nativeImage } = electron
const path = require('path')
const fs = require('fs')
const { execFile, spawn } = require('child_process')

const { ensureBackendUp, shutdownBackend, forceCleanupOrphan, BACKEND_PORT, BACKEND_HOST } = require('./backendManager.cjs')
const { buildUpdateScript } = require('./updateScript.cjs')

const isDev = !!process.env.VITE_DEV_SERVER_URL

// 启动日志探针（仅当设置 FTN_BOOT_LOG 时写文件，用于打包排障）
const bootLogPath = process.env.FTN_BOOT_LOG || ''
const bl = (...args) => {
  if (!bootLogPath) return
  try {
    require('fs').appendFileSync(bootLogPath, `[${new Date().toISOString()}] ${args.join(' ')}\n`)
  } catch { /* 忽略 */ }
}

let mainWindow = null
let startupCheckWindow = null   // 启动自检独立小窗（游戏启动器式）
// 关闭拦截：用户确认「停止引擎并退出」后置位，允许真正关闭
let allowClose = false

// ============================================
// 启用 Electron 自身单实例锁（多开保护）
// ============================================
const gotTheLock = app.requestSingleInstanceLock()

if (!gotTheLock) {
  app.quit()
} else {
  // 允许单实例：即使已有一个实例运行（如用户手动再开），也把焦点给已运行的实例
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })

  main()
}

/**
 * 主流程
 */
async function main() {
  bl('main() start, isPackaged=', app.isPackaged)
  await app.whenReady()
  bl('app ready')

  // 1. 拉起/连接后端
  try {
    bl('ensureBackendUp...')
    await ensureBackendUp()
    bl('ensureBackendUp ok')
  } catch (err) {
    // 后端拉起失败不应阻止窗口打开，但要记录
    console.error('[FTN] 后端未就绪:', err.message)
    bl('ensureBackendUp FAILED:', String((err && err.stack) || err))
  }

  // 2. 是否走「独立小窗启动自检」（配置 selfcheck.run_on_startup，默认开）
  let runStartupCheck = false
  try {
    const cfg = await httpGetJson(`http://${BACKEND_HOST}:${BACKEND_PORT}/api/config`)
    bl('config fetched, run_on_startup=', cfg && cfg.selfcheck ? cfg.selfcheck.run_on_startup : 'n/a')
    runStartupCheck = cfg?.selfcheck ? cfg.selfcheck.run_on_startup !== false : true
  } catch {
    // 后端配置读取失败：直接进主界面，避免卡在自检窗
    runStartupCheck = false
    bl('config fetch failed -> show main directly')
  }

  // 3. 创建窗口：自检时主窗口先隐藏，独立小窗负责引导
  if (runStartupCheck) {
    bl('create hidden main + startup check window')
    createWindow({ show: false })
    createStartupCheckWindow()
  } else {
    bl('create main window (show)')
    createWindow({ show: true })
  }
  bl('windows created')

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
}

process.on('uncaughtException', (err) => {
  bl('uncaughtException:', String((err && err.stack) || err))
  console.error('[FTN] 未捕获异常:', err)
})
process.on('unhandledRejection', (reason) => {
  bl('unhandledRejection:', String((reason && reason.stack) || reason))
  console.error('[FTN] 未处理的 Promise 拒绝:', reason)
})

/**
 * 创建主窗口（启动自检场景下先隐藏，检测完成后由 IPC 显示）
 */
function createWindow({ show = true } = {}) {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 640,
    backgroundColor: '#141120',
    show,
    title: 'FTN Atelier',
    autoHideMenuBar: true,
    icon: path.join(__dirname, 'assets', 'logo1.ico'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true,
    },
  })

  // 关闭默认菜单
  mainWindow.setMenuBarVisibility(false)

  // ============================================
  // 关闭拦截：引擎仍在运行时，阻止关闭并弹窗确认
  //   「是」→ 先停止引擎进程再退出；「否」→ 取消关闭，留在应用
  // ============================================
  mainWindow.on('close', async (event) => {
    if (allowClose) return
    event.preventDefault()

    let snap = null
    try {
      snap = await httpGetJson(`http://${BACKEND_HOST}:${BACKEND_PORT}/api/engine/status`)
    } catch { snap = null }

    const instances = (snap && Array.isArray(snap.instances)) ? snap.instances : []
    const running = !!snap && ['starting', 'running', 'stopping'].includes(snap.status)
    if (!running && instances.length === 0) {
      allowClose = true
      mainWindow.close()
      return
    }

    const count = Math.max(1, instances.length)
    const choice = await dialog.showMessageBox(mainWindow, {
      type: 'warning',
      title: 'FTN Atelier',
      message: '引擎仍在运行中',
      detail: `当前有 ${count} 个引擎实例正在运行。关闭应用将先停止引擎进程。是否继续？`,
      buttons: ['是，停止引擎并退出', '否，继续使用'],
      defaultId: 1,
      cancelId: 1,
      noLink: true,
    })

    if (choice.response === 0) {
      // 先停止全部引擎实例，再关闭窗口（/api/shutdown 也会兜底清理）
      try {
        await httpGetJson(`http://${BACKEND_HOST}:${BACKEND_PORT}/api/engine/stop-all`)
      } catch { /* 忽略 */ }
      allowClose = true
      mainWindow.close()
    }
    // 选择「否」：不关闭，继续留在应用
  })

  if (isDev) {
    mainWindow.loadURL(`${process.env.VITE_DEV_SERVER_URL}?main=1`)
    mainWindow.webContents.openDevTools({ mode: 'detach' })
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'), {
      query: { main: '1' },
    })
  }

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

/**
 * 启动自检独立小窗（游戏启动器式：无边框、居中、小尺寸、带进度条）
 */
function createStartupCheckWindow() {
  const W = 520
  const H = 700
  let startupCheckShown = false
  startupCheckWindow = new BrowserWindow({
    width: W,
    height: H,
    frame: false,
    resizable: false,
    show: false,
    alwaysOnTop: true,          // 自检/更新提示窗置顶，避免被其他窗口遮挡
    backgroundColor: '#141120',
    title: 'FTN Atelier 自检',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true,
    },
  })
  startupCheckWindow.setMenuBarVisibility(false)
  // 屏幕居中
  try {
    const wa = screen.getPrimaryDisplay().workArea
    startupCheckWindow.setPosition(
      Math.round(wa.x + (wa.width - W) / 2),
      Math.round(wa.y + (wa.height - H) / 2)
    )
  } catch { /* 保持默认位置 */ }

  if (isDev) {
    startupCheckWindow.loadURL(`${process.env.VITE_DEV_SERVER_URL}?view=startup`)
  } else {
    startupCheckWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'), {
      query: { view: 'startup' },
    })
  }
  startupCheckWindow.once('ready-to-show', () => {
    startupCheckShown = true
    startupCheckWindow.show()
  })
  startupCheckWindow.on('closed', () => {
    startupCheckWindow = null
    // 用户手动关掉自检窗 → 兜底显示主窗口
    if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.isVisible()) {
      mainWindow.show()
    }
  })
  // 兜底：自检小窗长时间未出现（加载异常）→ 显示主窗口，避免应用卡住。
  // 注意：小窗已正常显示时绝不提前放主窗口（自检未完成前不允许进入）
  setTimeout(() => {
    if (!startupCheckShown && startupCheckWindow && !startupCheckWindow.isDestroyed()) {
      startupCheckWindow.destroy()
    }
    if (!startupCheckShown && mainWindow && !mainWindow.isDestroyed() && !mainWindow.isVisible()) {
      mainWindow.show()
    }
  }, 12000)
}

/**
 * 简化 HTTP GET 并解析 JSON（Electron 主进程侧轮询后端用）。
 */
function httpGetJson(url, timeoutMs = 3000) {
  return new Promise((resolve, reject) => {
    const http = require('http')
    const req = http.get(url, (res) => {
      let data = ''
      res.on('data', (c) => (data += c))
      res.on('end', () => {
        try {
          resolve(JSON.parse(data))
        } catch (e) {
          reject(e)
        }
      })
    })
    req.on('error', reject)
    req.setTimeout(timeoutMs, () => {
      req.destroy()
      reject(new Error('timeout'))
    })
  })
}

// ============================================
// IPC：向渲染进程暴露后端信息与状态
// ============================================
ipcMain.handle('backend:info', () => ({
  url: `http://${BACKEND_HOST}:${BACKEND_PORT}`,
  port: BACKEND_PORT,
  ready: true,
}))

ipcMain.handle('app:info', () => ({
  version: app.getVersion(),
  electron: process.versions.electron,
  isPackaged: app.isPackaged,
}))

// 在线更新（安全版）：
//   1) 校验更新包 ZIP；
//   2) 记录待应用信息 + 生成 detached 更新脚本（写在 Data/updates/ 下）；
//   3) 关闭后端 → 退出主进程（解锁程序文件）；
//   4) 更新脚本（见 updateScript.cjs）在主进程完全退出后执行：
//      备份旧程序（排除 Core/Data/Database/Logs）→ 解压新版 → 校验 → 成功清理并启动新版；
//      失败则删除不完整新程序、恢复旧程序并弹窗提示；恢复失败时保留备份。

ipcMain.handle('update:apply', async (event, zipPath) => {
  const _updLog = (msg) => {
    try {
      const appRoot = path.dirname(app.getPath('exe'))
      const logPath = path.join(appRoot, 'Data', 'updates', 'updater-electron.log')
      fs.mkdirSync(path.dirname(logPath), { recursive: true })
      fs.appendFileSync(logPath, `[${new Date().toISOString()}] ${msg}\n`)
    } catch { /* 日志失败不影响更新 */ }
  }
  try {
    if (!app.isPackaged) {
      _updLog('开发模式，跳过更新替换')
      return { ok: false, msg: '开发模式不支持在线更新替换，请在打包版中使用' }
    }
    if (!zipPath || !fs.existsSync(zipPath)) {
      _updLog('更新包不存在：' + (zipPath || '空'))
      return { ok: false, msg: '更新包不存在：' + (zipPath || '空') }
    }
    const st = fs.statSync(zipPath)
    if (st.size < 1024 * 1024) {
      _updLog('更新包异常（体积过小）')
      return { ok: false, msg: '更新包异常（体积过小），已停止，不会动现有程序' }
    }
    const appRoot = path.dirname(app.getPath('exe'))
    const updatesDir = path.join(appRoot, 'Data', 'updates')
    fs.mkdirSync(updatesDir, { recursive: true })
    const ts = Date.now()
    const backup = path.join(updatesDir, `backup-${ts}`)
    const pendingPath = path.join(updatesDir, 'pending.json')
    const scriptPath = path.join(updatesDir, `apply-${ts}.ps1`)
    const startedMarker = path.join(updatesDir, 'updater-started.log')
    // 记录待应用信息（脚本执行时读取；成功后被清理）
    fs.writeFileSync(pendingPath, JSON.stringify({ zip: zipPath, appRoot, backup, ts }))
    // 生成 detached 更新脚本
    // UTF-8 BOM：Windows PowerShell 5.1 需 BOM 才能正确解析含中文的 .ps1
    fs.writeFileSync(scriptPath, '\uFEFF' + buildUpdateScript({ zip: zipPath, appRoot, backup }), 'utf8')
    // 清掉上次启动标记，便于本次握手确认
    try { fs.unlinkSync(startedMarker) } catch { /* 不存在则忽略 */ }
    _updLog(`update:apply 开始；pending=${pendingPath}`)
    _updLog(`ps1=${scriptPath}`)
    // 优雅关闭后端（会一并停止引擎实例）
    try { await shutdownBackend() } catch { /* 后端可能已不在 */ }

    // 启动独立更新进程：cmd /c start（ShellExecute 分离，脱离本进程生命周期）
    // → powershell -File apply-*.ps1；绝对路径，不依赖工作目录。
    const psExe = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    const cmdArgs = ['/c', 'start', '', '/min', psExe, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', scriptPath]
    _updLog(`启动 updater 命令: cmd.exe ${cmdArgs.join(' ')}`)
    const child = spawn(
      'cmd.exe',
      cmdArgs,
      { detached: true, stdio: 'ignore', windowsHide: true }
    )
    child.unref()
    child.on('error', (e) => _updLog(`cmd start 启动失败: ${e.message}`))
    child.on('spawn', () => _updLog(`cmd start 已启动（pid=${child.pid || '?'}）`))

    // 握手：等待 updater 真正启动（updater-started.log 出现），最多 8s，再退出主进程。
    // 消除「spawn 后立即 app.exit(0)」导致子进程未及初始化就被终止的竞态。
    const deadline = Date.now() + 8000
    while (Date.now() < deadline) {
      try {
        if (fs.existsSync(startedMarker)) break
      } catch { /* 忽略 */ }
      await new Promise((r) => setTimeout(r, 200))
    }
    const started = fs.existsSync(startedMarker)
    _updLog(`updater 启动确认: ${started ? 'YES（updater-started.log 已出现）' : 'NO（8s 内未出现，仍退出主进程以便诊断）'}`)
    _updLog('Electron 准备退出')
    app.exit(0)
    return { ok: true, msg: '正在应用更新并重启…' }
  } catch (e) {
    _updLog(`update:apply 异常: ${e.message}`)
    return { ok: false, msg: `应用更新失败：${e.message}` }
  }
})

// 应用 Logo（ico → dataURL，供启动自检小窗 / 关于页统一展示）
ipcMain.handle('app:logo', () => {
  try {
    const p = path.join(__dirname, 'assets', 'logo1.ico')
    if (fs.existsSync(p)) {
      const b64 = fs.readFileSync(p).toString('base64')
      return { ok: true, dataUrl: `data:image/x-icon;base64,${b64}` }
    }
  } catch { /* 忽略 */ }
  return { ok: false }
})

// 选择目录（用于配置引擎根目录等路径）
ipcMain.handle('dialog:selectDirectory', async () => {
  const win = BrowserWindow.getFocusedWindow() || mainWindow
  if (!win) return { canceled: true, path: null }
  const result = await dialog.showOpenDialog(win, {
    properties: ['openDirectory', 'createDirectory'],
    title: '选择目录',
  })
  if (result.canceled || result.filePaths.length === 0) {
    return { canceled: true, path: null }
  }
  return { canceled: false, path: result.filePaths[0] }
})

// 选择图片（用于首页自定义头图）
ipcMain.handle('dialog:selectImage', async () => {
  const win = BrowserWindow.getFocusedWindow() || mainWindow
  if (!win) return { canceled: true, path: null }
  const result = await dialog.showOpenDialog(win, {
    properties: ['openFile'],
    title: '选择头图',
    filters: [
      { name: '图片', extensions: ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif'] },
    ],
  })
  if (result.canceled || result.filePaths.length === 0) {
    return { canceled: true, path: null }
  }
  return { canceled: false, path: result.filePaths[0] }
})

// 选择任意文件（用于引擎启动入口文件等）
ipcMain.handle('dialog:selectFile', async () => {
  const win = BrowserWindow.getFocusedWindow() || mainWindow
  if (!win) return { canceled: true, path: null }
  const result = await dialog.showOpenDialog(win, {
    properties: ['openFile'],
    title: '选择文件',
  })
  if (result.canceled || result.filePaths.length === 0) {
    return { canceled: true, path: null }
  }
  return { canceled: false, path: result.filePaths[0] }
})

// 选择要添加的模型文件（支持多选，用于「添加模型」剪切式入库）
ipcMain.handle('dialog:selectModelFiles', async () => {
  const win = BrowserWindow.getFocusedWindow() || mainWindow
  if (!win) return { canceled: true, paths: [] }
  const result = await dialog.showOpenDialog(win, {
    properties: ['openFile', 'multiSelections'],
    title: '选择要添加的模型文件（将被剪切到对应分类目录）',
    filters: [
      { name: '模型文件', extensions: ['safetensors', 'ckpt', 'pt', 'pth'] },
      { name: '全部文件', extensions: ['*'] },
    ],
  })
  if (result.canceled || result.filePaths.length === 0) {
    return { canceled: true, paths: [] }
  }
  return { canceled: false, paths: result.filePaths }
})

// 打开本地路径（文件夹 / 图片），返回是否打开成功及提示
ipcMain.handle('shell:openPath', async (_evt, p) => {
  // 若为 http(s) 链接，用外部浏览器打开
  if (/^https?:\/\//i.test(String(p))) {
    await electron.shell.openExternal(p)
    return { ok: true }
  }
  try {
    const err = await electron.shell.openPath(p)
    return { ok: !err, error: err || null }
  } catch (e) {
    return { ok: false, error: String(e) }
  }
})

// 保存文本文件（日志导出）
ipcMain.handle('dialog:saveTextFile', async (_evt, defaultName, content) => {
  const win = BrowserWindow.getFocusedWindow() || mainWindow
  if (!win) return { canceled: true, path: null }
  const result = await dialog.showSaveDialog(win, {
    title: '导出日志',
    defaultPath: defaultName || 'ftn-export.log',
    filters: [{ name: '日志', extensions: ['log', 'txt'] }],
  })
  if (result.canceled || !result.filePath) return { canceled: true, path: null }
  try {
    fs.writeFileSync(result.filePath, content, 'utf-8')
    return { canceled: false, path: result.filePath }
  } catch (e) {
    return { canceled: false, path: result.filePath, error: String(e) }
  }
})

// 读取文本文件（数据导入用）
ipcMain.handle('dialog:readTextFile', async (_evt, p) => {
  try {
    const content = fs.readFileSync(p, 'utf-8')
    return { ok: true, content }
  } catch (e) {
    return { ok: false, error: String(e) }
  }
})

// 首页头图：原生压缩（限宽 1920、JPEG 88%），存到用户数据目录，避免超大图加载失败
ipcMain.handle('image:prepareHero', async (_evt, p) => {
  try {
    const img = nativeImage.createFromPath(p)
    if (img.isEmpty()) return { ok: false, error: '无法读取该图片（格式不支持或文件损坏）' }
    const size = img.getSize()
    const MAX_W = 1920
    let out = img
    if (size.width > MAX_W) out = img.resize({ width: MAX_W })
    const buf = out.toJPEG(88)
    const dir = path.join(app.getPath('userData'), 'hero')
    fs.mkdirSync(dir, { recursive: true })
    const outPath = path.join(dir, 'hero.jpg')
    fs.writeFileSync(outPath, buf)
    return { ok: true, path: outPath, width: out.getSize().width, bytes: buf.length }
  } catch (e) {
    return { ok: false, error: String(e) }
  }
})

// 读取图片为 dataURL（供裁剪弹窗预览）
ipcMain.handle('image:readDataUrl', async (_evt, p) => {
  try {
    const b = fs.readFileSync(p)
    const ext = (path.extname(p) || '').toLowerCase().replace('.', '') || 'png'
    const mime = {
      png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg',
      webp: 'image/webp', gif: 'image/gif', bmp: 'image/bmp',
    }[ext] || 'image/png'
    return { ok: true, dataUrl: `data:${mime};base64,${b.toString('base64')}` }
  } catch (e) {
    return { ok: false, error: String(e) }
  }
})

// 保存裁剪后的头图（dataURL → JPEG，存用户数据目录）
ipcMain.handle('image:saveHeroData', async (_evt, dataUrl) => {
  try {
    const img = nativeImage.createFromDataURL(dataUrl)
    if (img.isEmpty()) return { ok: false, error: '图片编码失败' }
    const buf = img.toJPEG(88)
    const dir = path.join(app.getPath('userData'), 'hero')
    fs.mkdirSync(dir, { recursive: true })
    const out = path.join(dir, 'hero.jpg')
    fs.writeFileSync(out, buf)
    return { ok: true, path: out, width: img.getSize().width }
  } catch (e) {
    return { ok: false, error: String(e) }
  }
})

// 启动自检完成（独立小窗内「进入 FTN Atelier」）→ 显示主窗口并关闭自检窗
ipcMain.on('startup-check-done', () => {
  if (startupCheckWindow && !startupCheckWindow.isDestroyed()) {
    startupCheckWindow.destroy()
  }
  if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.isVisible()) {
    mainWindow.show()
  }
})

// ============================================
// 应用生命周期：退出时关闭后端，清理资源
// ============================================
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', async (event) => {
  // 先阻止默认退出，等后端关闭后再退出
  event.preventDefault()
  // 兜底关闭自检小窗
  if (startupCheckWindow && !startupCheckWindow.isDestroyed()) {
    startupCheckWindow.destroy()
  }
  try {
    // 1. 优雅关闭后端（本实例拉起的进程）
    await shutdownBackend()
  } catch (err) {
    console.error('[FTN] 关闭后端出错:', err.message)
  }
  // 2. 兜底：清理可能残留的孤儿后端进程（防异常残留）
  try {
    await forceCleanupOrphan()
  } catch (err) {
    console.error('[FTN] 清理孤儿进程出错:', err.message)
  }
  // 3. 释放 Electron 单实例锁并真正退出
  app.releaseSingleInstanceLock()
  app.exit(0)
})
