import React, { useEffect, useState } from 'react'
import { backendApi } from '../services/apiClient'

// 网络模型下载入口（阶段 A）：尚未接入 CivitAI / HuggingFace API。
// - 未填写 API Key → 提示「请前往设置填写 API」，并提供一键直达设置「网站API」页 + 打开官网。
// - 已填写 API Key → 提示已就绪（实际下载功能待接入 API 后开放）。
// 阶段 B（接入 API 后）：若连接超时，界面显示「网络不佳，请检查或使用科学上网」。

const SOURCES = [
  {
    key: 'civitai',
    label: 'CivitAI',
    icon: '🌐',
    desc: 'LoRA / Checkpoint 模型库',
    apiField: 'civitai_api_key',
    siteUrl: 'https://civitai.com/settings/apikeys',
    help: '前往 CivitAI「Settings → API Keys」创建',
  },
  {
    key: 'huggingface',
    label: 'Hugging Face',
    icon: '🤗',
    desc: '模型 / 数据集 / 脚本',
    apiField: 'huggingface_token',
    siteUrl: 'https://huggingface.co/settings/tokens',
    help: '前往 HuggingFace「Settings → Access Tokens」创建',
  },
]

export default function DownloadModal({ onNavigate, onClose }) {
  const [config, setConfig] = useState(null)

  useEffect(() => {
    backendApi.getConfig().then(setConfig).catch(() => setConfig(null))
  }, [])

  const goSettingsApi = () => {
    // 通知设置页切到「网站API」Tab
    window.dispatchEvent(new CustomEvent('ftn:navigateSettings', { detail: 'api' }))
    if (onNavigate) onNavigate('settings')
  }
  const openUrl = (url) => {
    if (window.ftn?.openPath) window.ftn.openPath(url)
    else window.open(url, '_blank')
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6" onClick={onClose}>
      <div
        className="w-full max-w-2xl rounded-2xl border border-base-border bg-base-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-base-border">
          <div>
            <h2 className="text-lg font-bold">🌐 网络下载</h2>
            <p className="text-xs text-txt-muted mt-0.5">从 CivitAI / HuggingFace 搜索并下载模型</p>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-lg border border-base-border text-txt-muted hover:bg-base-surface-2">✕</button>
        </div>

        <div className="p-6 space-y-4">
          <div className="rounded-lg bg-accent-soft/30 border border-accent/30 px-4 py-3 text-sm text-txt-secondary">
            下载前需先配置对应网站的 <b>API 凭据</b>。尚未配置前提示「前往设置填写 API」；配置后可无缝使用（下载功能随 API 接入开放）。
          </div>

          {SOURCES.map((s) => {
            const key = config?.api_keys?.[s.apiField]
            const has = !!key && key.trim() !== ''
            return (
              <div key={s.key} className="rounded-xl border border-base-border p-4">
                <div className="flex items-center gap-3">
                  <span className="text-3xl">{s.icon}</span>
                  <div className="flex-1">
                    <div className="font-semibold">{s.label}</div>
                    <div className="text-xs text-txt-muted">{s.desc}</div>
                  </div>
                  <span className={`px-2 py-1 rounded-md text-[11px] font-medium ${has ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-400/30' : 'bg-amber-500/10 text-amber-400 border border-amber-400/30'}`}>
                    {has ? '✔ 已配置' : '未配置'}
                  </span>
                </div>

                <div className="mt-3 rounded-lg bg-base-surface-2/40 border border-base-border px-3.5 py-3 text-sm">
                  {has ? (
                    <p className="text-txt-secondary">已填写 API Key（{maskKey(key)}）。勾选模型即可下载（需先接入 API）。</p>
                  ) : (
                    <p className="text-amber-400/90">⚠️ 请前往<a className="mx-1 text-accent underline" onClick={() => onNavigate && onNavigate('settings')}>设置 → 网站API</a>填写 API Key 后使用。</p>
                  )}
                </div>

                <div className="mt-3 flex items-center gap-2 flex-wrap">
                  <button onClick={goSettingsApi}
                    className="px-3 py-1.5 rounded-lg border border-accent/40 text-accent text-xs hover:bg-accent-soft">⚙️ 前往设置 · 网站API</button>
                  <button onClick={() => openUrl(s.siteUrl)}
                    className="px-3 py-1.5 rounded-lg border border-base-border text-xs text-txt-muted hover:bg-base-surface-2">打开官网 API 设置页</button>
                  <a className="ml-auto text-[11px] text-txt-muted">{s.help}</a>
                </div>
              </div>
            )
          })}

          {/* 阶段 B：接入 API 后的网络异常提示（预留文案） */}
          <div className="rounded-lg border border-base-border px-4 py-3 text-xs text-txt-muted">
            小贴士：接入 API 后如遇连接超时，界面会提示「网络不佳，请检查或使用科学上网」。
          </div>
        </div>
      </div>
    </div>
  )
}

function maskKey(k) {
  if (!k) return ''
  if (k.length <= 8) return '••••' + k.slice(-4)
  return k.slice(0, 4) + '••••••' + k.slice(-4)
}
