import React, { createContext, useContext, useEffect, useState } from 'react'
import { applyTheme, DEFAULT_THEME } from '../themes'

const AppContext = createContext(null)

// 后端 FastAPI 服务地址（由 Electron 主进程启动，端口固定）
export const BACKEND_URL = 'http://127.0.0.1:19000'
export const WS_URL = 'ws://127.0.0.1:19000/ws'

// 兼容旧格式：'dark'/'light' → 默认主色主题
function normalizeTheme(id) {
  if (id === 'dark') return 'dark-purple'
  if (id === 'light') return 'light-purple'
  return id || DEFAULT_THEME
}

export function AppProvider({ children }) {
  const [theme, setTheme] = useState(DEFAULT_THEME)       // themeId：'dark-purple' 等
  const [backendConnected, setBackendConnected] = useState(false)
  const [backendStatus, setBackendStatus] = useState('connecting') // connecting | online | offline
  const [platform, setPlatform] = useState('win32')
  const [ambientEffect, setAmbientEffect] = useState('none')   // 外观动画: none|particles|light|breath
  const [windowActive, setWindowActive] = useState(true)       // 窗口是否活动（非活动暂停动画）
  const [isElectron, setIsElectron] = useState(
    typeof window !== 'undefined' && !!window.ftn?.isElectron
  )

  // 初始化时读取 Electron preload 暴露的信息
  useEffect(() => {
    if (window.ftn?.platform) setPlatform(window.ftn.platform)
    if (window.ftn?.isElectron) setIsElectron(true)
  }, [])

  // 窗口活动性：Document hidden + 窗口 blur/focus（用于非活动暂停外观动画）
  useEffect(() => {
    const onVis = () => setWindowActive(!document.hidden)
    const onBlur = () => setWindowActive(false)
    const onFocus = () => setWindowActive(true)
    document.addEventListener('visibilitychange', onVis)
    window.addEventListener('blur', onBlur)
    window.addEventListener('focus', onFocus)
    return () => {
      document.removeEventListener('visibilitychange', onVis)
      window.removeEventListener('blur', onBlur)
      window.removeEventListener('focus', onFocus)
    }
  }, [])

  // 应用主题：写 CSS 变量到 :root
  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  return (
    <AppContext.Provider
      value={{
        theme,
        setTheme: (id) => setTheme(normalizeTheme(id)),
        backendConnected,
        backendStatus,
        setBackendStatus,
        platform,
        ambientEffect,
        setAmbientEffect,
        windowActive,
        isElectron,
        setPlatform,
        setIsElectron,
      }}
    >
      {children}
    </AppContext.Provider>
  )
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp 必须在 <AppProvider> 内使用')
  return ctx
}
