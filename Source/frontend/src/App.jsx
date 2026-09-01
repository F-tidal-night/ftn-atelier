import React, { useEffect, useState } from 'react'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Settings from './pages/Settings'
import Models from './pages/Models'
import Versions from './pages/Versions'
import Changelog from './pages/Changelog'
import Theme from './pages/Theme'
import Troubleshoot from './pages/Troubleshoot'
import Tools from './pages/Tools'
import ConsolePage from './pages/Console'
import Downloads from './pages/Downloads'
import About from './pages/About'
import SelfCheckModal from './pages/SelfCheckModal'
import { useApp } from './state/AppContext'
import { backendApi } from './services/apiClient'

export default function App() {
  const { backendStatus, setBackendStatus, setTheme, setAmbientEffect } = useApp()
  const [view, setView] = useState('home')
  const [settingsTab, setSettingsTab] = useState(null)   // 设置页直达子 Tab（如 api）
  const [consoleFocus, setConsoleFocus] = useState(null) // 控制台直达会话（如引擎启动后自动选中）
  const [gate, setGate] = useState('pending') // pending | check | ready
  const [gateCheckUpdate, setGateCheckUpdate] = useState(true)

  // 初始化健康检查 + 恢复已保存主题/外观动画 + 决定是否启动前自检（仅启动时一次）
  useEffect(() => {
    let cancel = false
    // 主窗口由 Electron 加载时带 ?main=1：启动自检已由独立小窗完成，不再重复
    const isMainWindow = new URLSearchParams(window.location.search).get('main') === '1'
    const check = async () => {
      try {
        await backendApi.health()
        if (!cancel) setBackendStatus('online')
        const cfg = await backendApi.getConfig()
        if (!cancel && cfg?.preference?.theme) setTheme(cfg.preference.theme)
        if (!cancel && cfg?.preference?.ambient_effect) setAmbientEffect(cfg.preference.ambient_effect)
      } catch {
        if (!cancel) setBackendStatus('offline')
      }
    }
    // 首次：健康检查 + 启动自检门控判定（仅做一次，之后不重复弹出自检）
    const startup = async () => {
      try {
        await backendApi.health()
        setBackendStatus('online')
        const cfg = await backendApi.getConfig()
        if (cfg?.preference?.theme) setTheme(cfg.preference.theme)
        if (cfg?.preference?.ambient_effect) setAmbientEffect(cfg.preference.ambient_effect)
        const runSelf = cfg?.selfcheck ? cfg.selfcheck.run_on_startup !== false : true
        const checkUpd = cfg?.selfcheck ? cfg.selfcheck.check_update_on_startup !== false : true
        setGateCheckUpdate(checkUpd)
        setGate(isMainWindow || !runSelf ? 'ready' : 'check')
      } catch {
        setBackendStatus('offline')
        setGate('ready')
      }
    }
    startup()
    // 仅做常规健康轮询，不再触碰启动自检门控（避免自检反复弹出）
    const interval = setInterval(check, 5000)
    return () => {
      cancel = true
      clearInterval(interval)
    }
  }, [setBackendStatus, setTheme, setAmbientEffect])

  // 视图切换：仅已实现的页面可打开
  const handleNavigate = (key, sub) => {
    if (['home', 'settings', 'models', 'versions', 'theme', 'troubleshoot', 'tools', 'console', 'downloads', 'changelog', 'about'].includes(key)) {
      setView(key)
      if (key === 'settings') setSettingsTab(sub || null)
      if (key === 'console') setConsoleFocus(sub || null)
    }
  }

  const page =
    view === 'settings' ? <Settings initialTab={settingsTab} />
    : view === 'models' ? <Models onNavigate={handleNavigate} />
    : view === 'versions' ? <Versions />
    : view === 'theme' ? <Theme />
    : view === 'troubleshoot' ? <Troubleshoot />
    : view === 'tools' ? <Tools />
    : view === 'console' ? <ConsolePage initialFocus={consoleFocus} />
    : view === 'downloads' ? <Downloads onNavigate={handleNavigate} />
    : view === 'changelog' ? <Changelog />
    : view === 'about' ? <About />
    : <Dashboard onNavigate={handleNavigate} />

  // 自检互斥门控：gate 为 check 时先显示自检（startup 模式），完成后置 ready 恢复主界面
  return gate === 'check' ? (
    <SelfCheckModal mode="startup" checkUpdate={gateCheckUpdate} onEnter={() => setGate('ready')} />
  ) : (
    <Layout active={view} onNavigate={handleNavigate}>
      {page}
    </Layout>
  )
}
