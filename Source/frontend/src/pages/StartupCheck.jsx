import React, { useEffect, useState } from 'react'
import SelfCheckModal from './SelfCheckModal'
import { backendApi } from '../services/apiClient'

// ============================================
// 启动自检独立小窗（游戏启动器式）
// 仅由 Electron 以 ?view=startup 加载；检测完成后通知主进程显示主窗口
// ============================================
export default function StartupCheck() {
  const [ready, setReady] = useState(false)
  const [checkUpdate, setCheckUpdate] = useState(true)

  useEffect(() => {
    backendApi.getConfig()
      .then((cfg) => {
        setCheckUpdate(cfg?.selfcheck ? cfg.selfcheck.check_update_on_startup !== false : true)
      })
      .catch(() => setCheckUpdate(true))
      .finally(() => setReady(true))
  }, [])

  if (!ready) {
    return (
      <div className="h-screen w-screen flex flex-col items-center justify-center bg-base-bg text-txt-muted text-sm gap-3">
        <span className="text-3xl">🛠️</span>
        <span>正在准备自检…</span>
      </div>
    )
  }

  return (
    <SelfCheckModal
      mode="startup"
      standalone
      checkUpdate={checkUpdate}
      onEnter={() => window.ftn?.startupCheckDone?.()}
    />
  )
}
