import React, { useEffect, useState, useCallback, useRef } from 'react'
import { backendApi } from '../services/apiClient'
import LoraDetailModal from './LoraDetailModal'


// 模型分类（中文 + 类型，大气规范）
const CATS = [
  { key: 'all', label: '全部模型', sub: 'ALL' },
  { key: 'checkpoint', label: '底模 Checkpoint', sub: 'BASE' },
  { key: 'lora', label: '原生 LoRA', sub: 'LoRA' },
  { key: 'lora_plugin', label: '插件 LoRA', sub: 'P·LoRA' },
  { key: 'embedding', label: '嵌入式 Embedding', sub: 'EMBED' },
  { key: 'vae', label: '编码器 VAE', sub: 'VAE' },
]
const CAT_COLORS = {
  checkpoint: 'bg-purple-500/15 text-purple-300 border-purple-400/30',
  lora: 'bg-emerald-500/15 text-emerald-300 border-emerald-400/30',
  lora_plugin: 'bg-cyan-500/15 text-cyan-300 border-cyan-400/30',
  embedding: 'bg-amber-500/15 text-amber-300 border-amber-400/30',
  vae: 'bg-pink-500/15 text-pink-300 border-pink-400/30',
}

// 只有底模 / LoRA 需要预览图功能；其余类型用简单占位图标
const PREVIEW_TYPES = ['checkpoint', 'lora', 'lora_plugin']

export default function Models() {
  const [cat, setCat] = useState('all')
  const [query, setQuery] = useState('')
  const [models, setModels] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [scanMsg, setScanMsg] = useState(null)
  const [detail, setDetail] = useState(null)   // 当前打开的 LoRA 详情
  const [addOpen, setAddOpen] = useState(false)  // 添加模型面板
  const [addType, setAddType] = useState('checkpoint')
  const [adding, setAdding] = useState(false)

  const reqRef = useRef(0)
  const catRef = useRef('all')
  const queryRef = useRef('')
  useEffect(() => { catRef.current = cat }, [cat])
  useEffect(() => { queryRef.current = query }, [query])

  // silent：切换分类/自动检测刷新时不闪“加载中”，旧列表保持原位，避免布局跳动
  const load = useCallback(async (type = cat, q = query, opts = {}) => {
    const rid = ++reqRef.current
    if (!opts.silent) setLoading(true)
    try {
      const [list, st] = await Promise.all([
        backendApi.modelsList({ type, q: q || undefined, limit: 300 }),
        backendApi.modelsStats(),
      ])
      if (rid !== reqRef.current) return
      setModels(list || [])
      setStats(st)
    } catch {
      if (rid !== reqRef.current) return
      setModels([])
    } finally {
      if (rid === reqRef.current) setLoading(false)
    }
  }, [cat, query])

  useEffect(() => { load() }, [])

  // 自动检测：进入模型页自动触发后台增量扫描，不阻塞列表；
  // 只有索引为空或超过 60 秒才会真正扫描；扫描结束后静默刷新一次。
  useEffect(() => {
    let cancelled = false
    let timer = null
    let polls = 0
    const stop = () => { if (timer) { clearTimeout(timer); timer = null } }
    backendApi.modelsAutoScan()
      .then((r) => {
        if (!r?.auto_scan || cancelled) return
        const poll = async () => {
          if (cancelled) return
          polls += 1
          try {
            const st = await backendApi.modelsStats()
            if (!st?.scanning || polls >= 30) {
              load(catRef.current, queryRef.current, { silent: true })
              return
            }
          } catch { /* 后端瞬时不可用，等下一轮再试 */ }
          if (!cancelled && polls < 30) timer = setTimeout(poll, 1000)
        }
        timer = setTimeout(poll, 1200)
      })
      .catch(() => {})
    return () => { cancelled = true; stop() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const doScan = async (full, demo) => {
    setScanning(true)
    setScanMsg(null)
    try {
      const r = await backendApi.modelsScan({ full, demo })
      setScanMsg(`扫描完成：新增 ${r.new}，更新 ${r.updated}${r.note ? `（${r.note}）` : ''}`)
      load()
    } catch (e) {
      setScanMsg(`扫描失败: ${e.message}`)
    } finally { setScanning(false) }
  }

  // 打开当前分类对应的模型文件夹（全部 → models/ 根目录，其余 → 分类目录）
  const openFolder = async () => {
    if (!window.ftn?.openPath) {
      setScanMsg('当前非 Electron 环境，无法打开文件夹')
      return
    }
    try {
      const r = await backendApi.modelsFolder(cat)
      if (r?.ok) {
        await window.ftn.openPath(r.path)
      } else {
        setScanMsg(r?.msg || '打开文件夹失败')
      }
    } catch (e) {
      setScanMsg(`打开文件夹失败: ${e.message}`)
    }
  }

  // 添加模型：多选文件 → 剪切到当前分类目录（"全部"则用面板内所选分类）
  const doAdd = async () => {
    if (!window.ftn?.selectModelFiles) {
      setScanMsg('当前非 Electron 环境，无法选择文件')
      return
    }
    const res = await window.ftn.selectModelFiles()
    if (!res || res.canceled || !res.paths?.length) return
    setAdding(true)
    setScanMsg(null)
    try {
      const type = cat === 'all' ? addType : cat
      const r = await backendApi.modelsAdd(res.paths, type)
      setScanMsg(r.ok ? r.note : (`添加失败: ${r.msg}`))
      if (r.ok) setAddOpen(false)
      load(cat)
    } catch (e) {
      setScanMsg(`添加失败: ${e.message}`)
    } finally { setAdding(false) }
  }

  // 这里不自动注入演示数据：真实环境空模型就保持空，避免误导计数。
  // 演示数据仅由「全量扫描」意外失败时的人工「演示」触发，不会自动填充。

  return (
    <div className="p-8 max-w-7xl">
      {/* 头部 */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold">模型管理</h1>
          <p className="text-sm text-txt-muted mt-1">共 {stats?.total ?? 0} 个模型资产</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && load()}
            placeholder="搜索模型..."
            className="px-3 py-2 rounded-lg border border-base-border bg-base-surface text-sm w-56 shrink-0 focus:outline-none focus:border-accent"
          />

          <button onClick={openFolder}
            className="px-3 py-2 rounded-lg border border-base-border text-sm hover:bg-base-surface-2 whitespace-nowrap shrink-0"
            title="打开当前分类对应的模型文件夹">📂 打开文件夹</button>
          <button onClick={() => setAddOpen((v) => !v)}
            className="px-3 py-2 rounded-lg border border-accent/40 text-accent text-sm hover:bg-accent-soft whitespace-nowrap shrink-0">＋ 添加模型</button>
          <button
            onClick={() => doScan(true, false)}
            disabled={scanning}
            className="px-3 py-2 rounded-lg border border-base-border text-sm hover:bg-base-surface-2 disabled:opacity-40 whitespace-nowrap shrink-0"
            title="完整重建索引（重新读取全部模型文件头信息，较慢）"
          >全量扫描</button>
        </div>
      </div>

      {stats?.not_supported && (
        <div className="mb-4 px-4 py-3 rounded-lg border border-amber-400/40 bg-amber-500/10 text-sm text-amber-400">
          {stats.note || '当前主引擎类型不受支持（仅支持启动/停止/重启），模型管理不适用。'}
        </div>
      )}

      {scanMsg && <div className="mb-4 px-4 py-2 rounded-lg bg-emerald-500/10 text-emerald-400 text-sm">{scanMsg}</div>}

      {/* 添加模型面板（仅当 cat=all 时才需手动选分类） */}
      {addOpen && (
        <div className="mb-5 p-4 rounded-xl border border-accent/40 bg-accent-soft/30">
          <div className="flex items-center gap-4 flex-wrap">
            <span className="text-sm font-medium">将所选文件剪切到</span>
            <select value={cat === 'all' ? addType : cat} onChange={(e) => { setAddType(e.target.value); if (cat !== 'all') setCat(e.target.value) }}
              disabled={cat !== 'all'} className="px-3 py-2 rounded-lg border border-base-border bg-base-surface text-sm">
              {CATS.filter((c) => c.key !== 'all').map((c) => (
                <option key={c.key} value={c.key}>{c.label}</option>
              ))}
            </select>
            {cat !== 'all' && <span className="text-xs text-txt-muted">（当前分类已锁定「{CATS.find((c) => c.key === cat)?.label}」）</span>}
            <div className="ml-auto flex gap-2">
              <button onClick={doAdd} disabled={adding}
                className="px-4 py-2 rounded-lg bg-accent text-white text-sm disabled:opacity-50">{adding ? '添加中...' : '选择文件并剪切'}</button>
              <button onClick={() => setAddOpen(false)} className="px-4 py-2 rounded-lg border border-base-border text-sm">取消</button>
            </div>
          </div>
          <p className="text-[11px] text-txt-muted mt-2">支持多选；同名文件自动加序号。把文件「剪切（移动）」到主引擎对应模型目录后自动加入索引。</p>
        </div>
      )}

      {/* 分类 Tab */}
      <div className="flex gap-2.5 flex-wrap mb-6">
        {CATS.map((c) => {
          const count = c.key === 'all' ? stats?.total : stats?.by_type?.[c.key]
          const active = cat === c.key
          return (
            <button
              key={c.key}
              onClick={() => { setCat(c.key); if (c.key !== 'all') setAddType(c.key); load(c.key, query, { silent: true }) }}
              className={[
                'px-4 py-2.5 rounded-xl text-left border transition-all min-w-[120px] shrink-0 whitespace-nowrap',
                active
                  ? 'border-accent/60 bg-accent-soft shadow-lg shadow-accent/10'
                  : 'border-base-border bg-base-surface hover:border-accent/40 hover:bg-base-surface-2',
              ].join(' ')}
            >
              <div className={`text-sm font-semibold leading-tight ${active ? 'text-accent' : 'text-txt-primary'}`}>{c.label}</div>
              <div className="text-[11px] mt-0.5 flex items-center justify-between">
                <span className="text-txt-muted tracking-wider uppercase">{c.sub}</span>
                <span className={active ? 'text-accent' : 'text-txt-muted'}>{count ?? 0}</span>
              </div>
            </button>
          )
        })}
      </div>

      {/* 模型网格 */}
      {(() => {
        const visible = models.filter((m) => !m.dup)
        const dupGroups = models.filter((m) => m.copies > 1 && !m.dup).length
        return (
          <>
            {dupGroups > 0 && (
              <p className="text-[11px] text-txt-muted mb-3">
                ↻ 已合并 {dupGroups} 组重复模型（同一内容的多个副本，仅显示一份；完整列表在哈希计算完成后更新）
              </p>
            )}
            <div className="min-h-[320px]">
              {loading ? (
                <p className="text-txt-muted text-sm">加载中...</p>
              ) : visible.length === 0 ? (
                <div className="text-center py-16 text-txt-muted">
                  <p className="text-4xl mb-3">🗂️</p>
                  <p>暂无模型。已自动检测主引擎模型目录，也可点击「全量扫描」重建索引，或「＋ 添加模型」导入。</p>
                </div>
              ) : (
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5 gap-5">
                  {visible.map((m) => (
                    <ModelCard key={m.id} model={m} onOpen={() => setDetail(m)} />
                  ))}
                </div>
              )}
            </div>
          </>
        )
      })()}

      {detail && (
        <LoraDetailModal
          model={detail}
          onClose={() => setDetail(null)}
          onSaved={() => load()}
        />
      )}
    </div>
  )
}

function ModelCard({ model, onOpen }) {
  const preview = model.preview_path && !model.preview_path.startsWith('demo://')
  const color = CAT_COLORS[model.type] || 'bg-gray-500/15 text-gray-300 border-gray-400/30'
  const label = TYPE_FULL[model.type] || (model.type_label || model.type)
  const isLora = model.type?.includes('lora')
  const hasPreview = PREVIEW_TYPES.includes(model.type)
  const realFile = model.file_path && !model.file_path.startsWith('demo://')

  const openDir = async () => {
    if (!window.ftn?.openPath) return
    const r = await backendApi.modelDir(model.id).catch(() => null)
    if (r?.ok) await window.ftn.openPath(r.path)
  }

  return (
    <div className={`rounded-xl border border-base-border bg-base-surface overflow-hidden hover:border-accent/50 hover:shadow-xl hover:shadow-black/20 transition-all flex flex-col ${hasPreview ? '' : 'p-3.5'}`}>
      {/* 缩略图：仅底模 / LoRA 提供预览图区域（竖版 2:3） */}
      {hasPreview ? (
        <div className="aspect-[2/3] bg-base-surface-2 flex items-center justify-center overflow-hidden relative">
          {preview ? (
            <img src={`file://${model.preview_path.replace(/\\/g, '/')}`} className="w-full h-full object-cover" onError={(e) => e.target.style.display = 'none'} />
          ) : (
            <div className="flex flex-col items-center gap-2 opacity-40">
              <span className="text-5xl">🎨</span>
              <span className="text-xs">{typeIcon(model.type)}</span>
            </div>
          )}
          {model.base_model && (
            <span className="absolute top-2 left-2 px-2 py-0.5 rounded-md bg-black/60 text-white text-[11px] font-medium backdrop-blur">
              {model.base_model}
            </span>
          )}
          {model.copies > 1 && (
            <span className="absolute top-2 right-2 px-2 py-0.5 rounded-md bg-amber-500/85 text-white text-[10px] font-medium backdrop-blur">
              {model.copies} 副本
            </span>
          )}
        </div>
      ) : (
        // 其他类型（embedding/vae）：独立卡片样式，无大图占位，改为顶部图标带
        <div className="mb-2.5 flex items-center justify-between">
          <div className="w-10 h-10 rounded-xl bg-base-surface-2 border border-base-border flex items-center justify-center text-xl opacity-80">
            {typeIcon(model.type)}
          </div>
          <span className={`px-2 py-0.5 rounded-md border ${color}`}>{label}</span>
          {model.base_model && (
            <span className="px-2 py-0.5 rounded-md bg-base-surface-2 border border-base-border text-[11px] text-txt-muted">{model.base_model}</span>
          )}
          {model.copies > 1 && (
            <span className="px-2 py-0.5 rounded-md bg-amber-500/15 text-amber-400 border border-amber-400/30 text-[11px]">{model.copies} 副本</span>
          )}
        </div>
      )}
      {/* 信息 */}
      <div className={`${hasPreview ? 'p-3.5' : ''} flex-1 flex flex-col`}>
        <h3 className="font-semibold text-sm leading-snug line-clamp-2 mb-2.5" title={model.name}>{model.name}</h3>
        {model.base_model && (
          <div className="flex flex-wrap gap-1 mb-2">
            <span className="px-1.5 py-0.5 rounded bg-base-surface-2 border border-base-border text-[10px] text-txt-secondary">{model.base_model}</span>
          </div>
        )}
        <div className="mt-auto space-y-1.5">
          <div className="flex items-center justify-between text-[11px]">
            {hasPreview && (
              <span className={`px-2 py-0.5 rounded-md border ${color}`}>{label}</span>
            )}
            <span className="text-txt-muted ml-auto">{model.file_size ? fmtSize(model.file_size) : '—'}</span>
          </div>
          {model.mtime ? (
            <div className="text-[10px] text-txt-muted/80">更新于 {fmtDate(model.mtime)}</div>
          ) : null}
        </div>
        {/* 操作：LoRA 详情 / 打开所在文件夹 */}
        <div className="mt-3 flex gap-1.5">
          {isLora && onOpen && (
            <button
              onClick={onOpen}
              className="flex-1 px-2 py-1.5 rounded-lg border border-accent/40 text-accent text-xs font-medium hover:bg-accent-soft transition-colors"
            >📖 详情</button>
          )}
          {realFile && (
            <button
              onClick={openDir}
              className={`${isLora && onOpen ? '' : 'flex-1'} px-2 py-1.5 rounded-lg border border-base-border text-[11px] text-txt-muted hover:bg-base-surface-2 transition-colors`}
              title="打开所在文件夹"
            >📂 文件夹</button>
          )}
        </div>
      </div>
    </div>
  )
}

// 类型中文全称映射（与分类 Tab 一致，大气规范）
const TYPE_FULL = {
  checkpoint: '底模 Checkpoint',
  lora: '原生 LoRA',
  lora_plugin: '插件 LoRA',
  embedding: '嵌入式 Embedding',
  vae: '编码器 VAE',
}
function typeIcon(t) {
  return {
    checkpoint: '🖼️',
    lora: '🧩',
    lora_plugin: '🔗',
    embedding: '📝',
    vae: '🎛️',
  }[t] || '🗂️'
}

function fmtSize(n) {
  if (n >= 1e9) return (n / 1e9).toFixed(2) + ' GB'
  if (n >= 1e6) return (n / 1e6).toFixed(1) + ' MB'
  return n + ' B'
}
function fmtDate(ts) {
  try {
    const d = new Date(Number(ts) * 1000)
    if (isNaN(d.getTime())) return '—'
    return d.toLocaleDateString('zh-CN')
  } catch { return '—' }
}
function safeTags(s) {
  try {
    const arr = Array.isArray(s) ? s : JSON.parse(s)
    return Array.isArray(arr) ? arr : []
  } catch { return [] }
}
