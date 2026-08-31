import React, { useCallback, useEffect, useRef, useState } from 'react'
import { backendApi } from '../services/apiClient'

// ============================================
// 网络下载页（独立菜单）
//  - CivitAI：搜索模型 → 选版本 → 直接下载
//  - HuggingFace：搜索模型库 → 选文件 → 下载
//  下载落入主引擎对应分类目录并自动重新索引（后台任务 + 进度）。
// ============================================

// FTN 模型类型（下载入库目标分类）：HF 文件选择/手动选择用
const DL_TYPES = [
  { key: 'checkpoint', label: 'Checkpoint' },
  { key: 'lora', label: 'LoRA' },
  { key: 'lora_plugin', label: '插件 LoRA' },
  { key: 'embedding', label: 'Embedding' },
  { key: 'vae', label: 'VAE' },
]

// CivitAI 分类筛选（搜索时过滤，下载类型仍自动检测）
const TYPE_OPTIONS = [
  { key: '', label: '全部类型' },
  { key: 'checkpoint', label: 'Checkpoint' },
  { key: 'lora', label: 'LoRA' },
  { key: 'embedding', label: 'Embedding' },
  { key: 'vae', label: 'VAE' },
]

export default function Downloads({ onNavigate }) {
  const [sources, setSources] = useState(null)      // {civitai:{configured},huggingface:{configured}}
  const [tab, setTab] = useState('civitai')         // civitai | huggingface
  const [type, setType] = useState('')              // CivitAI 分类筛选
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)      // {items, count} 或 null
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)
  const [tasks, setTasks] = useState([])            // 活跃/最近下载任务
  const [hfFiles, setHfFiles] = useState(null)      // HF 文件选择弹窗数据
  const [expandedId, setExpandedId] = useState(null) // 手风琴：同一时间只展开一张卡

  // ---- 初始化来源凭据状态 ----
  useEffect(() => {
    backendApi.downloadSources().then(setSources).catch(() => setSources(null))
  }, [])

  // ---- 搜索 ----
  const doSearch = useCallback(async () => {
    setLoading(true)
    setErr(null)
    setResults(null)
    try {
      if (tab === 'civitai') {
        const r = await backendApi.civitaiSearch(query, type, 24)
        if (!r?.ok) { setErr(r?.error || '搜索失败'); setResults([]) } else setResults(r)
      } else {
        const r = await backendApi.hfSearch(query, 24)
        if (!r?.ok) { setErr(r?.error || '搜索失败'); setResults([]) } else setResults(r)
      }
    } catch (e) {
      setErr(`搜索失败：${e.message}（请检查网络或使用科学上网）`)
      setResults([])
    } finally {
      setLoading(false)
    }
  }, [tab, query, type])

  // ---- 下载启动 ----
  const startDownload = async (source, url, filename, mtype) => {
    setErr(null)
    try {
      const r = await backendApi.downloadStart(source, url, filename, mtype)
      if (!r?.ok) { setErr(r?.msg || '下载启动失败'); return }
      setTasks((prev) => [{ id: r.task_id, label: filename || '模型', source, type: r.type_label || '', status: 'running', progress: 0, log: [] }, ...prev])
    } catch (e) {
      setErr(`下载启动失败：${e.message}`)
    }
  }

  // ---- 下载进度轮询 ----
  useEffect(() => {
    if (!tasks.some((t) => t.status === 'running')) return
    const timer = setInterval(async () => {
      let anyRunning = false
      const updated = await Promise.all(tasks.map(async (t) => {
        if (t.status !== 'running') return t
        try {
          const s = await backendApi.downloadStatus(t.id)
          if (s?.ok) {
            anyRunning = true
            return { ...t, status: s.status, progress: s.progress ?? 0, log: s.log || [], error: s.error }
          }
          return t
        } catch { return t }
      }))
      setTasks(updated)
      if (!anyRunning) clearInterval(timer)
    }, 1200)
    return () => clearInterval(timer)
  }, [tasks])

  const goSettingsApi = () => {
    if (onNavigate) onNavigate('settings', 'api')
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-5">
      <header>
        <h1 className="text-2xl font-bold">网络下载</h1>
        <p className="text-sm text-txt-muted mt-1">从 CivitAI / HuggingFace 搜索并下载模型，已下载文件自动加入「模型」库。</p>
      </header>

      {/* 来源标签 */}
      <div className="flex items-center gap-2 border-b border-base-border pb-3">
        {[
          { key: 'civitai', label: 'CivitAI', icon: '🌐' },
          { key: 'huggingface', label: 'Hugging Face', icon: '🤗' },
        ].map((s) => {
          const on = tab === s.key
          const configured = sources?.[s.key]?.configured
          return (
            <button key={s.key} onClick={() => { setTab(s.key); setResults(null); setErr(null) }}
              className={`px-4 py-2 rounded-lg text-sm flex items-center gap-2 transition-colors ${on ? 'bg-accent text-white' : 'bg-base-surface-2 text-txt-muted hover:text-txt-primary'}`}>
              <span>{s.icon}</span>{s.label}
              {configured
                ? <span className={`text-[10px] px-1.5 py-0.5 rounded ${on ? 'bg-white/20' : 'bg-emerald-500/10 text-emerald-400'}`}>已配置</span>
                : <span className={`text-[10px] px-1.5 py-0.5 rounded ${on ? 'bg-white/20' : 'bg-amber-500/10 text-amber-400'}`}>未配置</span>}
            </button>
          )
        })}
        <button onClick={goSettingsApi}
          className="ml-auto px-3 py-1.5 rounded-lg border border-accent/40 text-accent text-xs hover:bg-accent-soft">
          ⚙️ 设置 · 网站API
        </button>
      </div>

      {/* 搜索栏 */}
      <div className="flex items-center gap-2 flex-wrap">
        <input
          value={query} onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !loading && doSearch()}
          placeholder={tab === 'civitai' ? '搜索 CivitAI 模型（名称 / 关键词 / 作者）…' : '搜索 HuggingFace 模型库（名称 / 关键词）…'}
          className="flex-1 min-w-[220px] px-3.5 py-2.5 rounded-lg border border-base-border bg-base-surface-2 text-sm focus:outline-none focus:border-accent"
        />
        {tab === 'civitai' && (
          <select value={type} onChange={(e) => setType(e.target.value)}
            className="px-3 py-2.5 rounded-lg border border-base-border bg-base-surface-2 text-sm">
            {TYPE_OPTIONS.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
          </select>
        )}
        <button onClick={doSearch} disabled={loading}
          className="px-5 py-2.5 rounded-lg bg-accent text-white text-sm hover:opacity-90 disabled:opacity-50">
          {loading ? '搜索中…' : '🔍 搜索'}
        </button>
      </div>

      {/* 错误提示 */}
      {err && (
        <div className="px-4 py-2.5 rounded-lg bg-red-500/10 border border-red-400/30 text-red-400 text-sm">{err}</div>
      )}

      {/* 结果区 */}
      {results && (
        <div>
          <div className="text-sm text-txt-muted mb-3">共找到 {results.count ?? results.items?.length ?? 0} 个结果</div>
          {results.items && results.items.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {results.items.map((it, i) =>
                tab === 'civitai' ? (
                  <CivitCard key={i} it={it} onDownload={startDownload}
                    expanded={expandedId === i} onToggle={() => setExpandedId(expandedId === i ? null : i)} />
                ) : (
                  <HfCard key={i} it={it} onPick={() => setHfFiles(it)}
                    expanded={expandedId === i} onToggle={() => setExpandedId(expandedId === i ? null : i)} />
                )
              )}
            </div>
          ) : (
            <div className="text-txt-muted text-center py-16 rounded-xl border border-dashed border-base-border">
              无结果，换个关键词试试。
            </div>
          )}
        </div>
      )}

      {/* 正在下载 / 最近下载 */}
      {tasks.length > 0 && (
        <section>
          <h2 className="text-base font-semibold mb-2">下载任务</h2>
          <div className="space-y-2">
            {tasks.map((t) => {
              const statusTxt = t.status === 'error' ? '失败' : t.status === 'done' ? '已完成，已加入模型库' : '下载中'
              return (
                <div key={t.id} className="rounded-xl border border-base-border bg-base-surface p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium truncate text-txt-primary">{t.label}</span>
                    <span className={`text-xs shrink-0 ${t.status === 'error' ? 'text-red-400' : t.status === 'done' ? 'text-emerald-400' : 'text-accent'}`}>
                      {statusTxt} · {Math.round(t.progress || 0)}%
                    </span>
                  </div>
                  <div className="h-2 rounded-full bg-base-surface-2 overflow-hidden">
                    <div className="h-full transition-all rounded-full" style={{ width: `${t.progress || 0}%`, background: 'var(--color-accent)' }} />
                  </div>
                  {t.log && t.log.length > 0 && (
                    <div className="mt-2 text-[11px] text-txt-muted font-mono whitespace-pre-wrap max-h-24 overflow-y-auto">
                      {t.log[t.log.length - 1]}
                    </div>
                  )}
                  {t.error && <div className="mt-1 text-xs text-red-400">{t.error}</div>}
                  {t.status === 'done' && onNavigate && (
                    <button onClick={() => onNavigate('models')}
                      className="mt-2 px-3 py-1 rounded-md bg-emerald-500/15 text-emerald-400 text-xs hover:bg-emerald-500/25">
                      去「模型」页查看 →
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* HF 文件选择弹窗 */}
      {hfFiles && (
        <HfFilePicker repo={hfFiles} sources={sources}
          onClose={() => setHfFiles(null)}
          onDownload={(url, filename, mtype) => startDownload('huggingface', url, filename, mtype)} />
      )}

      {/* 来源凭据提示 */}
      {!sources?.civitai?.configured && tab === 'civitai' && (
        <div className="rounded-lg bg-base-surface-2/50 border border-base-border px-4 py-3 text-xs text-txt-muted">
          未配置 CivitAI API Key：公开搜索仍可用，但请求限额较低。建议到 <button onClick={goSettingsApi} className="text-accent underline">设置 → 网站API</button> 填写以提高限额。
        </div>
      )}
      {!sources?.huggingface?.configured && tab === 'huggingface' && (
        <div className="rounded-lg bg-base-surface-2/50 border border-base-border px-4 py-3 text-xs text-txt-muted">
          未配置 HuggingFace Token：匿名访问当前可用；如需下载受限仓库请到 <button onClick={goSettingsApi} className="text-accent underline">设置 → 网站API</button> 填写。
        </div>
      )}
    </div>
  )
}

// ===== CivitAI 结果卡（类型自动检测，含下载量/点赞/底模） =====
const CIVIT_TYPE_MAP = {
  Checkpoint: 'checkpoint',
  LORA: 'lora',
  LoRA: 'lora',
  Embedding: 'embedding',
  TextualInversion: 'embedding',
  VAE: 'vae',
}
const FTN_TYPE_LABEL = { checkpoint: 'Checkpoint', lora: 'LoRA', embedding: 'Embedding', vae: 'VAE' }

function civitToFtn(type) {
  return CIVIT_TYPE_MAP[type]
    || (String(type || '').toLowerCase().includes('lora') ? 'lora' : 'checkpoint')
}

function CivitCard({ it, onDownload, expanded, onToggle }) {
  const autoType = civitToFtn(it.type)
  const typeLabel = FTN_TYPE_LABEL[autoType] || it.type || '模型'
  const [pickVers, setPickVers] = useState(null)   // 版本选择弹窗
  const vers = it.versions && it.versions.length ? it.versions : null
  return (
    <div className="rounded-xl border border-base-border bg-base-surface p-4 flex flex-col gap-3">
      <div className="flex gap-3">
        {it.image ? (
          <img src={it.image} alt="" loading="lazy"
            className="w-20 h-20 rounded-lg object-cover bg-base-surface-2 shrink-0" />
        ) : (
          <div className="w-20 h-20 rounded-lg shrink-0 flex items-center justify-center text-[10px] font-medium tracking-wide text-txt-secondary"
            style={{ background: 'linear-gradient(135deg, var(--color-surface-2), color-mix(in srgb, var(--color-accent) 16%, var(--color-surface-2)))' }}>
            {typeLabel}
          </div>
        )}
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-sm truncate text-txt-primary">{it.name}</div>
          <div className="text-[11px] text-txt-secondary truncate">by {it.creator || '—'}</div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            <span className="px-1.5 py-0.5 rounded bg-base-surface-2 text-[10px] text-txt-secondary border border-base-border">{typeLabel}（自动检测）</span>
            {it.base && <span className="px-1.5 py-0.5 rounded bg-base-surface-2 text-[10px] text-txt-secondary border border-base-border">底模 {it.base}</span>}
            {it.nsfw && <span className="px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 text-[10px] border border-red-400/30">NSFW</span>}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            <span className="px-1.5 py-0.5 rounded bg-base-surface-2 text-[10px] text-txt-secondary border border-base-border">⬇ {fmtNum(it.downloads)}</span>
            <span className="px-1.5 py-0.5 rounded bg-base-surface-2 text-[10px] text-txt-secondary border border-base-border">♥ {fmtNum(it.likes)}</span>
            {it.version_count > 0 && <span className="px-1.5 py-0.5 rounded bg-base-surface-2 text-[10px] text-txt-secondary border border-base-border">{it.version_count} 版本</span>}
          </div>
        </div>
      </div>
      {it.description && (
        <button onClick={onToggle}
          className="text-left text-[11px] text-txt-secondary hover:text-txt-primary transition-colors cursor-pointer">
          <span className={expanded ? '' : 'line-clamp-2'}>{it.description}</span>
          <span className="text-accent ml-1">{expanded ? '▲ 收起' : '▼ 详情'}</span>
        </button>
      )}
      <button
        onClick={() => {
          if (!it.download_url) return
          if (vers && vers.length > 1) { setPickVers(it); return }
          const fname = it.filename || `${it.name.replace(/\s+/g, '_')}.safetensors`
          onDownload('civitai', it.download_url, fname, autoType)
        }}
        disabled={!it.download_url}
        className="mt-auto px-3 py-2 rounded-lg bg-accent text-white text-xs font-medium hover:opacity-90 disabled:opacity-40">
        ⬇ 下载{it.download_url ? (vers && vers.length > 1 ? ' · 选择版本' : ` · 归入 ${typeLabel}`) : ''}
      </button>

      {/* 版本选择弹窗 */}
      {pickVers && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6" onClick={() => setPickVers(null)}>
          <div className="w-full max-w-md rounded-2xl border border-base-border bg-base-surface shadow-2xl flex flex-col max-h-[80vh]" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-base-border">
              <div className="min-w-0">
                <h2 className="text-base font-bold truncate text-txt-primary">{pickVers.name}</h2>
                <p className="text-[11px] text-txt-muted truncate">by {pickVers.creator || '—'} · 自动归类 {typeLabel}</p>
              </div>
              <button onClick={() => setPickVers(null)} className="w-8 h-8 rounded-lg border border-base-border text-txt-muted hover:bg-base-surface-2 shrink-0">✕</button>
            </div>
            <div className="p-4 overflow-y-auto flex-1 space-y-1.5">
              {pickVers.versions.map((v, i) => (
                <button key={v.id || i}
                  onClick={() => {
                    const fname = v.filename || `${pickVers.name.replace(/\s+/g, '_')}.safetensors`
                    onDownload('civitai', v.download_url, fname, autoType)
                    setPickVers(null)
                  }}
                  className="w-full px-3 py-2.5 rounded-lg border border-base-border hover:border-accent/50 text-left transition-colors">
                  <div className="text-sm font-medium text-txt-primary truncate">{v.name}</div>
                  <div className="text-[11px] text-txt-secondary mt-0.5 flex flex-wrap gap-x-2">
                    {v.base && <span>底模 {v.base}</span>}
                    {v.size > 0 && <span>{fmtNum(v.size)}</span>}
                    {v.filename && <span className="font-mono truncate">{v.filename}</span>}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ===== HuggingFace 结果卡 =====
function HfCard({ it, onPick, expanded, onToggle }) {
  return (
    <div className="rounded-xl border border-base-border bg-base-surface p-4 flex flex-col gap-2.5">
      <div className="font-semibold text-sm truncate text-txt-primary">{it.name}</div>
      <div className="text-[11px] text-txt-muted truncate font-mono">{it.repo}</div>
      <div className="flex flex-wrap gap-1">
        <span className="px-1.5 py-0.5 rounded bg-base-surface-2 text-[10px] text-txt-secondary border border-base-border">⬇ {fmtNum(it.downloads)}</span>
        <span className="px-1.5 py-0.5 rounded bg-base-surface-2 text-[10px] text-txt-secondary border border-base-border">♥ {fmtNum(it.likes)}</span>
        {it.pipeline && <span className="px-1.5 py-0.5 rounded bg-base-surface-2 text-[10px] text-txt-secondary border border-base-border">{it.pipeline}</span>}
        {it.tags && it.tags.length > 0 && (
          <span className="px-1.5 py-0.5 rounded bg-base-surface-2 text-[10px] text-txt-muted border border-base-border">{it.tags.slice(0, 2).join(' · ')}</span>
        )}
      </div>
      {it.description && (
        <button onClick={onToggle}
          className="text-left text-[11px] text-txt-secondary hover:text-txt-primary transition-colors cursor-pointer">
          <span className={expanded ? '' : 'line-clamp-2'}>{it.description}</span>
          <span className="text-accent ml-1">{expanded ? '▲ 收起' : '▼ 详情'}</span>
        </button>
      )}
      <button onClick={onPick} className="mt-auto px-3 py-1.5 rounded-lg border border-accent/40 text-accent text-xs hover:bg-accent-soft">
        📂 选择文件下载
      </button>
    </div>
  )
}

// ===== HF 文件选择弹窗 =====
function HfFilePicker({ repo, onClose, onDownload }) {
  const [files, setFiles] = useState(null)
  const [loading, setLoading] = useState(true)
  const [pick, setPick] = useState(null)     // {path,size,name}
  const [dlType, setDlType] = useState('checkpoint')

  useEffect(() => {
    let alive = true
    setLoading(true)
    backendApi.hfFiles(repo.repo)
      .then((r) => { if (alive) setFiles(r.ok ? r.files : []) })
      .catch(() => { if (alive) setFiles([]) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [repo])

  const ext = pick ? (pick.extension || '').toLowerCase() : ''
  const autoType = { '.safetensors': 'checkpoint', '.ckpt': 'checkpoint', '.pt': 'lora', '.pth': 'lora' }[ext] || 'checkpoint'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6" onClick={onClose}>
      <div className="w-full max-w-lg rounded-2xl border border-base-border bg-base-surface shadow-2xl flex flex-col max-h-[80vh]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-base-border">
          <div className="min-w-0">
            <h2 className="text-base font-bold truncate">{repo.name}</h2>
            <p className="text-[11px] text-txt-muted truncate font-mono">{repo.repo}</p>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-lg border border-base-border text-txt-muted hover:bg-base-surface-2 shrink-0">✕</button>
        </div>

        <div className="p-4 overflow-y-auto flex-1">
          <div className="text-xs text-txt-muted mb-2">选择要下载的文件（按推荐度排序，safetensors 优先）</div>
          {loading ? (
            <div className="text-sm text-txt-muted py-8 text-center">加载文件列表…</div>
          ) : files && files.length > 0 ? (
            <ul className="space-y-1.5">
              {files.map((f, i) => (
                <li key={i}
                  onClick={() => setPick(f)}
                  className={`px-3 py-2.5 rounded-lg border cursor-pointer transition-colors ${pick?.path === f.path ? 'border-accent bg-accent/10' : 'border-base-border hover:border-accent/40'}`}>
                  <div className="flex items-center gap-2 text-sm">
                    <span className={`font-mono ${pick?.path === f.path ? 'text-accent' : 'text-txt-primary'}`}>{f.name}</span>
                    <span className="ml-auto text-[10px] text-txt-muted">{fmtNum(f.size)}</span>
                  </div>
                  <div className="text-[10px] text-txt-muted truncate font-mono mt-0.5">{f.path}</div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-sm text-txt-muted text-center py-8">该模型库没有可直接下载的文件</div>
          )}
        </div>

        <div className="px-4 py-3 border-t border-base-border">
          <div className="flex items-center gap-2">
            <select value={pick ? autoType : dlType} onChange={(e) => setDlType(e.target.value)}
              className="px-2 py-2 rounded-lg border border-base-border bg-base-surface-2 text-xs flex-1">
              {DL_TYPES.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
            </select>
            <button
              onClick={() => {
                if (!pick) return
                onDownload(pick.download_url || `https://huggingface.co/${repo.repo}/resolve/main/${pick.path}`, pick.name, dlType || autoType)
                onClose()
              }}
              disabled={!pick}
              className="px-4 py-2 rounded-lg bg-accent text-white text-sm hover:opacity-90 disabled:opacity-40 shrink-0">
              ⬇ 下载所选
            </button>
          </div>
          {pick && <div className="text-[10px] text-txt-muted mt-1.5">将保存为「{dlType || autoType}」分类 · {fmtNum(pick.size)}</div>}
        </div>
      </div>
    </div>
  )
}

function fmtNum(n) {
  if (n == null) return '—'
  n = Number(n)
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'G'
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return String(n)
}
