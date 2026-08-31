import React, { useEffect, useState } from 'react'
import { backendApi } from '../services/apiClient'

// 等级标签跟随语言
const LEVEL_INFO = { INFO: '正常', WARN: '警告', ERROR: '错误', DEBUG: '调试', FATAL: '致命' }
const LEVEL_COLOR = { INFO: '#22c55e', WARN: '#f59e0b', ERROR: '#ef4444', DEBUG: '#94a3b8', FATAL: '#dc2626' }

// 疑难解答：所有日志统一列在同一列表，顶部按级别统计数量；可按级别筛选查看；
// 每条日志可勾选，勾选后导出（多选逐条导出）。
export default function Troubleshoot() {
  const [data, setData] = useState(null)        // {counts, logs, normal_logs}
  const [normalLogs, setNormalLogs] = useState([])
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(false)
  const [sources, setSources] = useState([])
  const [levelFilter, setLevelFilter] = useState('全部')   // 全部 / 正常 / 警告 / 错误
  const [selected, setSelected] = useState(new Set())       // 已勾选的导出条目（按 key 标识）
  const [env, setEnv] = useState(null)                      // 环境检测快照
  const [envLoading, setEnvLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [items, src] = await Promise.all([
        backendApi.troubleshootLogs(),
        backendApi.logsSources(),
      ])
      setData(items)
      setLogs(items?.logs || [])
      setNormalLogs(items?.normal_logs || [])
      setSources(src?.sources || [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }
  const loadEnv = async () => {
    setEnvLoading(true)
    try { setEnv(await backendApi.systemEnv()) }
    catch { setEnv(null) }
    finally { setEnvLoading(false) }
  }
  useEffect(() => { load(); loadEnv() }, [])

  const counts = data?.counts || { normal: 0, warn: 0, error: 0 }

  // 合并所有日志，并给每行一个稳定标识
  const all = [
    ...normalLogs.map((l, i) => ({ ...l, key: `n-${l.time}-${i}` })),
    ...logs.map((l, i) => ({ ...l, key: `t-${l.time}-${i}` })),
  ].sort((a, b) => (a.time < b.time ? 1 : -1))  // 最新在上

  // 级别筛选
  const normLevel = (lv) => (lv === 'FATAL' ? 'ERROR' : lv)
  const FILTER_TO_LEVEL = {
    正常: ['INFO', 'DEBUG'],
    警告: ['WARN'],
    错误: ['ERROR', 'FATAL'],
  }
  const filtered = levelFilter === '全部'
    ? all
    : all.filter((l) => {
        const want = FILTER_TO_LEVEL[levelFilter]
        return !!want && want.includes(normLevel(l.level))
      })

  // 打开某条日志对应的源文件
  const openLog = async (name) => {
    if (!window.ftn?.openPath) return
    const src = sources.find((s) => s.name === name)
    if (src?.path) await window.ftn.openPath(src.path)
  }
  const openLogDir = async () => {
    if (!window.ftn?.openPath) return
    const active = sources.find((s) => s.name === 'backend') || sources[0]
    const dir = active?.path?.replace(/[\\/][^\\/]+$/, '')
    if (dir) await window.ftn.openPath(dir)
  }

  // 勾选 / 反选单条
  const toggleOne = (key) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }
  const toggleAll = () => {
    setSelected((prev) => {
      const next = new Set(prev)
      const allVisibleKeys = filtered.map((l) => l.key)
      const allSelected = allVisibleKeys.length > 0 && allVisibleKeys.every((k) => next.has(k))
      if (allSelected) {
        allVisibleKeys.forEach((k) => next.delete(k))
      } else {
        allVisibleKeys.forEach((k) => next.add(k))
      }
      return next
    })
  }

  // 导出已勾选日志
  const doExport = async () => {
    if (!selected.size) return
    const chosen = all.filter((l) => selected.has(l.key))
    let bundle = `# FTN Studio 疑难解答导出  ${new Date().toLocaleString()}\n`
    bundle += `导出条数：${chosen.length}\n\n`
    for (const l of chosen) {
      bundle += `[${l.time}] [${l.level}] [${l.source}] ${l.content}\n`
    }
    if (!window.ftn?.saveTextFile) return
    await window.ftn.saveTextFile(`ftn-troubleshoot-${new Date().toISOString().slice(0, 10)}.log`, bundle)
  }

  return (
    <div className="p-8 max-w-6xl">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h1 className="text-2xl font-bold">疑难解答</h1>
          <p className="text-sm text-txt-muted mt-1">所有日志统一列表展示，可按级别筛选，勾选逐条导出。</p>
        </div>
        <button onClick={openLogDir} className="px-3 py-1.5 rounded-lg border border-base-border text-sm hover:bg-base-surface-2">打开日志目录</button>
      </div>

      {/* 统计（按级别分列数量） */}
      <div className="flex gap-3 mb-4 flex-wrap">
        <StatChip label="正常" color={LEVEL_COLOR.INFO} count={counts.normal} />
        <StatChip label="警告" color={LEVEL_COLOR.WARN} count={counts.warn} />
        <StatChip label="错误" color={LEVEL_COLOR.ERROR} count={counts.error} />
        <span className="text-xs text-txt-muted self-center">（最近 50 条错误 / 警告，正常至多 20 条）</span>
      </div>

      {/* 环境检测链 */}
      <section className="rounded-xl border border-base-border bg-base-surface p-5 mb-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="font-semibold text-txt-secondary">环境检测</h2>
            <p className="text-xs text-txt-muted mt-0.5">一键检测 Python / Git / CUDA 驱动 / 显卡 / 模型路径（只读，启动前环境核验参考）。</p>
          </div>
          <button onClick={loadEnv} className="px-3 py-1.5 rounded-lg text-white text-sm font-medium disabled:opacity-40"
            style={{ background: 'var(--color-accent)' }}>
            {envLoading ? '检测中…' : '重新检测'}
          </button>
        </div>
        {envLoading ? (
          <p className="text-sm text-txt-muted py-4">正在检测环境...</p>
        ) : env ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {env.items.map((it) => (
              <div key={it.key} className="flex items-start gap-3 rounded-lg border border-base-border p-3">
                <span className="w-2.5 h-2.5 rounded-full mt-1 shrink-0"
                  style={{ background: it.status === 'ok' ? '#22c55e' : it.status === 'warn' ? '#f59e0b' : '#ef4444' }} />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>{it.label}</div>
                  <div className="text-xs text-txt-muted break-all mt-0.5">{it.value}{it.hint ? ` ${it.hint}` : ''}</div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-txt-muted py-4">环境检测不可用（后端离线）。</p>
        )}
      </section>

      {/* 查看筛选 + 导出工具 */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <span className="text-xs text-txt-muted">查看：</span>
        {['全部', '正常', '警告', '错误'].map((lvl) => (
          <button key={lvl} onClick={() => setLevelFilter(lvl)}
            className="px-2.5 py-1 rounded text-[11px] border"
            style={{
              borderColor: levelFilter === lvl ? 'var(--color-accent)' : 'var(--color-border)',
              background: levelFilter === lvl ? 'var(--color-accent-soft)' : 'transparent',
              color: levelFilter === lvl ? 'var(--color-accent)' : 'var(--color-text-muted)',
            }}>
            {lvl}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-txt-muted cursor-pointer select-none">
            <input type="checkbox" checked={filtered.length > 0 && filtered.every((l) => selected.has(l.key))}
              onChange={toggleAll} className="accent-current" />
            全选当前
          </label>
          <button onClick={doExport} disabled={!selected.size}
            className="px-3 py-1.5 rounded-lg text-white text-sm font-medium disabled:opacity-40"
            style={{ background: 'var(--color-accent)' }}>
            导出已选（{selected.size}）
          </button>
        </div>
      </div>

      {/* 统一日志列表 */}
      <div className="rounded-xl border border-base-border bg-base-surface overflow-hidden">
        <div className="px-4 py-2.5 border-b border-base-border flex items-center gap-2">
          <span className="w-4" />
          <span className="font-semibold text-sm">日志列表</span>
          <span className="ml-auto text-xs text-txt-muted">共 {filtered.length} 条</span>
        </div>
        {loading ? (
          <p className="px-4 py-8 text-sm text-txt-muted">加载中...</p>
        ) : filtered.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-txt-muted">当前筛选下暂无日志</p>
        ) : (
          <div className="divide-y divide-base-border">
            {filtered.map((l) => {
              const color = LEVEL_COLOR[l.level] || '#94a3b8'
              const checked = selected.has(l.key)
              return (
                <div key={l.key}
                  className={`flex items-start gap-3 px-4 py-2.5 ${checked ? 'bg-accent-soft/40' : ''}`}>
                  <input type="checkbox" checked={checked} onChange={() => toggleOne(l.key)} className="mt-1 accent-current shrink-0" />
                  <div className="flex-1 min-w-0 cursor-pointer" onClick={() => openLog(l.source)}>
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-[9px] px-1 py-0.5 rounded shrink-0" style={{ background: `${color}22`, color }}>
                        {LEVEL_INFO[l.level] || l.level}
                      </span>
                      <span className="text-[11px] text-txt-muted truncate">[{l.time}] {l.source}</span>
                    </div>
                    <div className="text-xs text-txt-primary break-all line-clamp-2">{l.content}</div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

function StatChip({ label, color, count }) {
  return (
    <div className="px-3 py-1.5 rounded-lg border border-base-border bg-base-surface flex items-center gap-2">
      <span className="w-2.5 h-2.5 rounded-full" style={{ background: color }} />
      <span className="text-sm text-txt-muted">{label}</span>
      <span className="text-sm font-semibold" style={{ color }}>{count}</span>
    </div>
  )
}
