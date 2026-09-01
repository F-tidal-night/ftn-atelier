import React, { useEffect, useState } from 'react'
import { backendApi } from '../services/apiClient'

// ============================================
// 更新日志：展示后端随包分发的 更新说明.md
// 极简 Markdown 渲染（版本 / 日期 / 列表 / 加粗），无第三方依赖
// ============================================

function fmt(s) {
  // **加粗**
  const parts = String(s).split(/\*\*(.+?)\*\*/g)
  return parts.map((p, j) => (j % 2 === 1 ? <b key={j} className="text-txt-primary">{p}</b> : p))
}

function renderBlocks(lines) {
  const out = []
  let i = 0
  while (i < lines.length) {
    const t = String(lines[i] ?? '').trim()
    // 版本号 + 紧随的日期 → 同一行紧挨（视为一组）
    if (/^v?\d+\.\d+(\.\d+)?(\s|$)/.test(t)) {
      const next = String(lines[i + 1] ?? '').trim()
      const isDate = /^\d{4}[./-]\d{1,2}[./-]\d{1,2}/.test(next)
      out.push(
        <div key={`v${i}`} className="flex items-baseline gap-3 mt-8 mb-4">
          <span className="font-extrabold text-lg text-accent shrink-0">{t}</span>
          {isDate && <span className="text-xs text-txt-muted">{next}</span>}
        </div>
      )
      i += isDate ? 2 : 1
      continue
    }
    if (!t) { i++; continue }
    if (/^#{3}\s+/.test(t)) {
      out.push(<h4 key={i} className="font-semibold text-sm text-txt-primary mt-4 mb-1">{t.replace(/^#{3}\s+/, '')}</h4>)
    } else if (/^#{1,2}\s+/.test(t)) {
      out.push(<h3 key={i} className="font-bold text-base text-txt-primary mt-6 mb-2 border-b border-base-border pb-1">{t.replace(/^#{1,2}\s+/, '')}</h3>)
    } else if (/^[-·]/.test(t)) {
      out.push(<li key={i} className="ml-4 list-disc text-sm text-txt-secondary leading-relaxed mb-1.5">{fmt(t.replace(/^[-·]\s*/, ''))}</li>)
    } else {
      out.push(<p key={i} className="text-sm text-txt-secondary leading-relaxed mb-2">{fmt(t)}</p>)
    }
    i++
  }
  return out
}

export default function Changelog() {
  const [content, setContent] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    backendApi.changelog()
      .then((r) => {
        if (r?.ok) setContent(r.content || '')
        else setErr(r?.error || '读取失败')
      })
      .catch((e) => setErr(e.message))
  }, [])

  return (
    <div className="p-8 max-w-3xl">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">更新日志</h1>
        <p className="text-sm text-txt-muted mt-1">FTN Atelier 各版本迭代说明</p>
      </header>
      <div className="rounded-2xl border border-base-border bg-base-surface p-6">
        {err ? (
          <p className="text-sm text-rose-400">读取更新日志失败：{err}</p>
        ) : content === null ? (
          <p className="text-sm text-txt-muted">加载中...</p>
        ) : (
          <div>{renderBlocks(content.split('\n'))}</div>
        )}
      </div>
    </div>
  )
}
