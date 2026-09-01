// ============================================
// FTN Studio Python 后端进程管理 (Electron 主进程)
//
// 职责：
// - 拉起 FastAPI 常驻服务
// - 检测端口占用（复用已运行的实例）
// - 健康检查等待就绪
// - 随 Electron 退出优雅关闭、清理孤儿进程
// - 多开保护
// ============================================

const { spawn, exec } = require('child_process')
const { app } = require('electron')
const path = require('path')
const fs = require('fs')
const net = require('net')

// 后端服务端口（与 frontend 的 BACKEND_URL 对应）
const BACKEND_PORT = 19000
const BACKEND_HOST = '127.0.0.1'

// 后端 Python 解释器解析顺序：内置运行时（开箱即用）→ venv → 系统 python
const BACKEND_DIR = path.join(__dirname, '..', '..', 'backend')
// 应用数据根目录（对齐绘世：数据跟程序走，便携文件夹拷走即带走设置/引擎/模型索引）：
//   打包后优先跟随 exe 所在目录；仅当 exe 目录不可写（如被放进 Program Files）
//   才回退到用户数据目录（%APPDATA%），避免启动即崩溃。
//   开发模式沿用源码根目录（Logs/Database 与源码同层）。
function resolveAppDataDir() {
  if (!app.isPackaged) return path.join(__dirname, '..', '..', '..')
  const exeDir = path.dirname(app.getPath('exe'))
  try {
    const probe = path.join(exeDir, 'Database')
    fs.mkdirSync(probe, { recursive: true })
    fs.accessSync(probe, fs.constants.W_OK)
    return exeDir
  } catch {
    return app.getPath('userData')
  }
}
const APP_DATA_DIR = resolveAppDataDir()

/**
 * 一次性迁移：旧版本打包后数据写在 %APPDATA% 用户目录，新版本改为
 * “数据跟程序走”（便携根目录）。检测到 exe 旁还没有数据、而旧用户目录
 * 有数据库时，把旧数据搬过来，避免“更新后设置/引擎全没了”的观感。
 * 仅在目标目录无数据时执行；逐目录迁移，失败单个不阻塞其余。
 */
function migrateLegacyData(targetDir) {
  if (!app.isPackaged) return
  try {
    if (fs.existsSync(path.join(targetDir, 'Database', 'ftn.db'))) return
    const legacy = app.getPath('userData')
    if (!legacy || legacy.toLowerCase() === targetDir.toLowerCase()) return
    if (!fs.existsSync(path.join(legacy, 'Database', 'ftn.db'))) return
    for (const d of ['Database', 'Logs', 'Data', 'Core', 'Backup']) {
      const src = path.join(legacy, d)
      const dst = path.join(targetDir, d)
      if (!fs.existsSync(src)) continue
      try {
        const dstNonEmpty = fs.existsSync(dst) && fs.readdirSync(dst).length > 0
        if (dstNonEmpty) continue
        if (fs.existsSync(dst)) {
          // 目标只有探测/启动产生的空目录：先移除，让旧目录整体瞬移
          try { fs.rmdirSync(dst) } catch { /* 非空则走复制分支 */ }
        }
        try {
          fs.renameSync(src, dst) // 同盘瞬移；跨盘失败自动回退复制
        } catch {
          fs.cpSync(src, dst, { recursive: true })
        }
      } catch {
        /* 单个目录迁移失败不阻塞 */
      }
    }
    console.log('[FTN] 已把旧版数据迁移到便携根目录:', legacy, '->', targetDir)
  } catch (err) {
    console.error('[FTN] 迁移旧版数据失败:', err.message)
  }
}
migrateLegacyData(APP_DATA_DIR)
const EMBED_PYTHON = path.join(BACKEND_DIR, 'runtime', 'python.exe')
const VENV_PYTHON = path.join(BACKEND_DIR, 'venv', 'Scripts', 'python.exe')
const GLOBAL_PYTHON = 'python'

let backendProcess = null // 当前由本实例拉起的后端进程
let pidLockPath = null // 单实例锁文件

/**
 * 检查端口是否已被占用（有进程监听则返回连接成功）
 * @returns {Promise<boolean>}
 */
function isPortInUse(port) {
  return new Promise((resolve) => {
    const socket = new net.Socket()
    socket.setTimeout(500)
    socket.once('connect', () => {
      socket.destroy()
      resolve(true)
    })
    socket.once('timeout', () => {
      socket.destroy()
      resolve(false)
    })
    socket.once('error', () => {
      resolve(false)
    })
    socket.connect(port, BACKEND_HOST)
  })
}

/**
 * 定位可用的 Python 解释器路径
 */
function resolvePython() {
  // 内置嵌入式 Python（随包分发，免装环境）优先；其次 venv；最后系统 python
  if (fs.existsSync(EMBED_PYTHON)) return EMBED_PYTHON
  if (fs.existsSync(VENV_PYTHON)) return VENV_PYTHON
  return GLOBAL_PYTHON
}

/**
 * 检查 FastAPI 后端是否已就绪（健康接口）
 */
function isBackendReady() {
  return new Promise((resolve) => {
    const http = require('http')
    const req = http
      .get(`http://${BACKEND_HOST}:${BACKEND_PORT}/api/health`, (res) => {
        let data = ''
        res.on('data', (c) => (data += c))
        res.on('end', () => {
          try {
            const json = JSON.parse(data)
            resolve(json && json.status === 'ok')
          } catch {
            resolve(false)
          }
        })
      })
      .on('error', () => resolve(false))
    req.setTimeout(800, () => {
      req.destroy()
      resolve(false)
    })
  })
}

/**
 * 写单实例锁文件（记录由谁启动后端）
 */
function writePidLock(pid) {
  const lockDir = path.join(APP_DATA_DIR, 'Database')
  try {
    fs.mkdirSync(lockDir, { recursive: true })
    pidLockPath = path.join(lockDir, 'backend.lock')
    fs.writeFileSync(
      pidLockPath,
      JSON.stringify({ pid, port: BACKEND_PORT, startTime: Date.now() }),
      'utf-8'
    )
  } catch (err) {
    console.error('[FTN] 写入锁文件失败:', err.message)
  }
}

/**
 * 清理单实例锁文件
 */
function cleanupPidLock() {
  if (pidLockPath && fs.existsSync(pidLockPath)) {
    try {
      fs.unlinkSync(pidLockPath)
    } catch {
      /* 忽略 */
    }
  }
  pidLockPath = null
}

/**
 * 启动（或连接）FastAPI 后端
 * @returns {Promise<boolean>} 是否就绪
 */
async function ensureBackendUp() {
  // 1. 若端口已占用，尝试健康检查，成功则视为复用已有实例
  if (await isPortInUse(BACKEND_PORT)) {
    console.log('[FTN] 检测到端口已占用，尝试复用已有后端实例')
    if (await isBackendReady()) {
      global.__ftn_uses_existing_backend = true
      return true
    }
    // 端口被占用但非 FTN 后端：无法启动，返回错误
    throw new Error(
      `端口 ${BACKEND_PORT} 已被其他程序占用，且无法识别为 FTN Studio 后端服务。`
    )
  }

  // 2. 端口空闲：拉起新的后端进程
  const python = resolvePython()
  const scriptPath = path.join(BACKEND_DIR, 'main.py')
  const logDir = path.join(APP_DATA_DIR, 'Logs')
  fs.mkdirSync(logDir, { recursive: true })
  const logOut = fs.openSync(path.join(logDir, 'backend.out.log'), 'a')
  const logErr = fs.openSync(path.join(logDir, 'backend.err.log'), 'a')

  try {
    backendProcess = spawn(python, [scriptPath], {
      cwd: BACKEND_DIR,
      env: {
        ...process.env,
        FTN_BACKEND_PORT: String(BACKEND_PORT),
        // 注入宿主 (Electron 主进程) PID，供后端 Watchdog 监控；异常退出时后端自清理
        FTN_HOST_PID: String(process.pid),
        FTN_BACKEND_DIR: BACKEND_DIR,
        // 应用数据根目录（打包后指向 %APPDATA%/FTN Atelier）
        FTN_APP_DIR: APP_DATA_DIR,
        // 正式打包标记：后端据此关闭演示数据（版本/引擎不造假）
        FTN_PACKAGED: app.isPackaged ? '1' : '0',
      },
      stdio: ['ignore', logOut, logErr],
      windowsHide: true,
      detached: false,
    })
  } catch (err) {
    console.error('[FTN] 启动后端失败:', err.message)
    throw err
  }

  backendProcess.on('error', (err) => {
    console.error('[FTN] 后端进程错误:', err.message)
  })

  writePidLock(backendProcess.pid)

  // 3. 等待健康检查就绪（最多 15 秒）
  const deadline = Date.now() + 15000
  while (Date.now() < deadline) {
    if (await isBackendReady()) {
      console.log('[FTN] 后端服务已就绪')
      return true
    }
    // 若进程提前退出，停止等待
    if (backendProcess && backendProcess.exitCode !== null) {
      break
    }
    await new Promise((r) => setTimeout(r, 400))
  }

  throw new Error('FTN 后端服务启动超时（15 秒内未就绪），请检查 Logs/backend.err.log')
}

/**
 * 关闭由本实例拉起的后端（始终由"本实例启动的进程"才关闭，避免误杀复用的实例）
 */
async function shutdownBackend() {
  // 若复用了外部已有实例，则不负责关闭它（外部拥有者管理）
  if (global.__ftn_uses_existing_backend) {
    console.log('[FTN] 复用了已有后端实例，不主动关闭')
    cleanupPidLock()
    return
  }

  if (backendProcess && backendProcess.exitCode === null) {
    console.log('[FTN] 优雅关闭后端进程 (pid=%s)', backendProcess.pid)
    // 尝试通过 API 优雅退出
    try {
      await new Promise((resolve) => {
        const http = require('http')
        const req = http.get(
          `http://${BACKEND_HOST}:${BACKEND_PORT}/api/shutdown`,
          (res) => {
            res.resume()
            res.on('end', resolve)
          }
        )
        req.on('error', resolve)
        req.setTimeout(3000, () => {
          req.destroy()
          resolve()
        })
      })
    } catch {
      /* 忽略 */
    }

    // 兜底：等待退出，超时强制杀死
    await new Promise((resolve) => {
      const timer = setTimeout(() => {
        try {
          backendProcess.kill()
        } catch {}
        resolve()
      }, 3000)
      backendProcess.once('exit', () => {
        clearTimeout(timer)
        resolve()
      })
    })
  }

  cleanupPidLock()
  backendProcess = null
}

/**
 * 强制清理遗留孤儿进程（用于异常恢复）
 * 1) 孤儿后端：只匹配「本程序实际的 main.py」路径（精确路径，防误杀其它应用）
 * 2) 孤儿引擎：只处理 Database/engine_pids.json 注册表标记过的 PID（进程标记），
 *    并校验该 PID 的进程命令行仍指向注册时的引擎根目录（防 PID 复用），整树强杀
 */
function forceCleanupOrphan() {
  return new Promise((resolve) => {
    const killPid = (pid) => {
      try {
        exec(`taskkill /PID ${pid} /T /F`, { windowsHide: true })
        console.log('[FTN] 清理孤儿进程 pid=%s', pid)
      } catch {}
    }
    const escRe = (s) => String(s).replace(/\\/g, '\\\\').replace(/'/g, "''")
    const psFind = (filterExpr, done) => {
      const ps =
        'powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \\"Name=\'python.exe\' or Name=\'pythonw.exe\'\\" ' +
        `| Where-Object { $_.CommandLine -match ${filterExpr} } ` +
        '| Select-Object -ExpandProperty ProcessId"'
      exec(ps, { windowsHide: true }, (err, stdout) => {
        if (!err && stdout) {
          for (const pid of String(stdout).split(/\r?\n/)) {
            const p = pid.trim()
            if (p && /^\d+$/.test(p)) killPid(p)
          }
        }
        done()
      })
    }
    // 1) 孤儿后端：精确 main.py 路径
    const mainPy = escRe(path.join(BACKEND_DIR, 'main.py'))
    psFind(`'${mainPy}'`, () => {
      // 2) 孤儿引擎：注册表标记过的 PID
      const regPath = path.join(APP_DATA_DIR, 'Database', 'engine_pids.json')
      fs.readFile(regPath, 'utf8', (err, data) => {
        let entries = []
        if (!err) {
          try {
            const parsed = JSON.parse(data)
            if (Array.isArray(parsed)) entries = parsed
          } catch {}
        }
        const next = () => {
          if (entries.length === 0) {
            resolve()
            return
          }
          const e = entries.shift()
          const pid = e && /^\d+$/.test(String(e.pid)) ? String(e.pid) : null
          const root = (e && e.root) || ''
          if (!pid || !root) {
            next()
            return
          }
          const ps = `powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter \\"ProcessId=${pid}\\" | Where-Object { $_.CommandLine -match '${escRe(root)}' } | Select-Object -ExpandProperty ProcessId"`
          exec(ps, { windowsHide: true }, (e2, stdout) => {
            const p = String(stdout || '').trim()
            if (/^\d+$/.test(p)) killPid(p)
            next()
          })
        }
        next()
      })
    })
  })
}

module.exports = {
  BACKEND_PORT,
  BACKEND_HOST,
  APP_DATA_DIR,
  ensureBackendUp,
  shutdownBackend,
  isBackendReady,
  isPortInUse,
  forceCleanupOrphan,
}
