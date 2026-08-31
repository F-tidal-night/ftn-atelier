import React, { useEffect, useState } from 'react'
import {
  IconHome, IconModels, IconDownload, IconVersions, IconTheme,
  IconTool, IconLog, IconWidgets, IconSettings, IconAbout,
} from './icons'
import AmbientLayer from '../pages/AmbientLayer'
import { useApp } from '../state/AppContext'

// 侧边导航项
const NAV_ITEMS = [
  { key: 'home', label: '首页', Icon: IconHome },
  { key: 'models', label: '模型', Icon: IconModels },
  { key: 'downloads', label: '网络下载', Icon: IconDownload },
  { key: 'versions', label: '版本', Icon: IconVersions },
  { key: 'theme', label: '主题', Icon: IconTheme },
  { key: 'troubleshoot', label: '疑难解答', Icon: IconTool },
  { key: 'console', label: '控制台', Icon: IconLog },
  { key: 'tools', label: '小工具', Icon: IconWidgets },
  { key: 'settings', label: '设置', Icon: IconSettings },
  { key: 'about', label: '关于', Icon: IconAbout },
]

/**
 * 全局应用外壳：左侧固定导航栏 + 右侧内容区。
 * props: active(当前视图 key) / onNavigate(切换) / children(页面)
 */
export default function Layout({ active, onNavigate, children }) {
  const { ambientEffect, windowActive } = useApp()
  const [ver, setVer] = useState('')
  useEffect(() => {
    let alive = true
    window.ftn?.getAppInfo?.().then((r) => { if (alive && r?.version) setVer(r.version) }).catch(() => {})
    return () => { alive = false }
  }, [])
  return (
    <div className="flex h-screen w-screen overflow-hidden">
      {/* 外观动画层（背景，不拦截点击） */}
      <AmbientLayer effect={ambientEffect} running={windowActive} />
      {/* 侧边导航 */}
      <aside className="relative z-10 w-56 shrink-0 flex flex-col bg-base-surface border-r border-base-border">
        <div className="px-5 py-5 flex items-center">
          <div className="font-bold leading-tight text-[17px] tracking-wide">FTN Atelier</div>
        </div>

        <nav className="flex-1 px-3 space-y-1 overflow-y-auto">
          {NAV_ITEMS.map(({ key, label, Icon }) => {
            const on = active === key
            return (
              <button
                key={key}
                onClick={() => onNavigate && onNavigate(key)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-colors ${
                  on
                    ? 'bg-accent text-white'
                    : 'text-txt-secondary hover:bg-base-surface-2 hover:text-txt-primary'
                }`}
              >
                <span className="text-[17px]"><Icon /></span>
                <span>{label}</span>
              </button>
            )
          })}
        </nav>

        <div className="px-3 py-3 text-[10px] text-txt-muted border-t border-base-border">v{ver} · 生图引擎工作台</div>
      </aside>

      {/* 内容区（半透明底，让外观动画在背后隐约透出） */}
      <main
        className="flex-1 min-w-0 overflow-y-auto relative z-10"
        style={{ background: 'color-mix(in srgb, var(--color-bg) 70%, transparent)' }}
      >
        {children}
      </main>
    </div>
  )
}
