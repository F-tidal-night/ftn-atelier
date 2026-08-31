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
// 应用数据根目录：打包后写入用户数据目录（%APPDATA%/FTN Atelier），
// 开发模式沿用源码根目录（Logs/Database 与源码同层）
const APP_DATA_DIR = app.isPackaged
  ? path.join(app.getPath('userData'))
  : path.join(__dirname, '..', '..', '..')
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
 * 强制清理遗留孤儿后端进程（用于异常恢复）
 * 遍历系统 python 进程并匹配启动的 main.py
 */
function forceCleanupOrphan() {
  // Windows 下通过 wmic 查找命令行包含 backend 目录的 python 进程
  return new Promise((resolve) => {
    const killMatched = (stdout) => {
      const lines = String(stdout).split(/\r?\n/)
      for (const line of lines) {
        if (line.includes('main.py') && line.includes('backend')) {
          const parts = line.split(',')
          const pid = parts[parts.length - 1]?.trim()
          if (pid && /^\d+$/.test(pid)) {
            try {
              exec(`taskkill /PID ${pid} /F`, { windowsHide: true })
              console.log('[FTN] 清理孤儿后端进程 pid=%s', pid)
            } catch {}
          }
        }
      }
    }
    // 方式一：wmic（部分系统不可用）
    exec(
      `wmic process where "name='python.exe' or name='pythonw.exe'" get processid,commandline /format:csv`,
      { windowsHide: true },
      (err, stdout) => {
        if (err || !stdout || !String(stdout).includes('backend')) {
          // 方式二：PowerShell Get-CimInstance 兜底
          const ps = `powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \\"Name='python.exe' or Name='pythonw.exe'\\" | Where-Object { $_.CommandLine -match 'backend' -and $_.CommandLine -match 'main.py' } | Select-Object -ExpandProperty ProcessId"`
          exec(ps, { windowsHide: true }, (err2, stdout2) => {
            if (!err2 && stdout2) {
              for (const pid of String(stdout2).split(/\r?\n/)) {
                const p = pid.trim()
                if (p && /^\d+$/.test(p)) {
                  try {
                    exec(`taskkill /PID ${p} /F`, { windowsHide: true })
                    console.log('[FTN] 清理孤儿后端进程 pid=%s', p)
                  } catch {}
                }
              }
            }
            resolve()
          })
          return
        }
        killMatched(stdout)
        resolve()
      }
    )
  })
}

module.exports = {
  BACKEND_PORT,
  BACKEND_HOST,
  ensureBackendUp,
  shutdownBackend,
  isBackendReady,
  isPortInUse,
  forceCleanupOrphan,
}
