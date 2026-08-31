import React, { useEffect, useState, useCallback } from 'react'
import { backendApi } from '../services/apiClient'
import { BACKEND_URL } from '../state/AppContext'

// 快捷文件夹定义（基于主引擎根目录推算输出目录）
const FAMILY_LABEL = { reforge: 'reForge', forge: 'Forge', a1111: 'A1111', comfyui: 'ComfyUI', unknown: '未知类型', other: '脚本/工具' }
const SUPPORTED_FAMILY = new Set(['reforge', 'forge'])
// 实际配置来自 /api/quickfolders（设置页可改名/重指定路径）
export default function Dashboard({ onNavigate }) {
  const [engine, setEngine] = useState(null)
  const [engines, setEngines] = useState([])
  const [folders, setFolders] = useState([])
  const [sel, setSel] = useState('reforge')
  const [hero, setHero] = useState(null)
  const [engineBusy, setEngineBusy] = useState(false)
  const [systemInfo, setSystemInfo] = useState(null)
  const [tip, setTip] = useState('')
  const [primaryHealth, setPrimaryHealth] = useState(null)
  const [stats, setStats] = useState([])             // 各引擎实例占用（内存/显存）
  const [history, setHistory] = useState([])         // 占用趋势采样
  const [totalMem, setTotalMem] = useState(null)     // 系统内存总量（MB）
  const [totalGpu, setTotalGpu] = useState(null)     // 显存总量（MB）
  // 首启引导：每次启动显示一次；点「知道了」后本次运行不再显示（sessionStorage 随窗口关闭重置）
  const [guideDismissed, setGuideDismissed] = useState(
    () => { try { return sessionStorage.getItem('ftn_guide_dismissed') === '1' } catch { return false } }
  )

  const refresh = useCallback(async () => {
    try {
      const [eng, list] = await Promise.all([backendApi.engineStatus(), backendApi.enginesList()])
      setEngine(eng)
      if (list) {
        setEngines(list)
        // 默认选中主引擎（主引擎已由后端置顶）
        setSel((s) => {
          const pk = list.find((e) => e.primary)
          if (pk && (!list.some((e) => e.key === s) || s === 'reforge')) return pk.key
          return s
        })
      }
      try { setSystemInfo(await backendApi.systemInfo()) } catch {}
      try { setPrimaryHealth(await backendApi.enginePrimaryHealth()) } catch {}
      try {
        const s = await backendApi.engineStats()
        setStats(s?.instances || [])
        setHistory(s?.history || [])
        setTotalMem(s?.total_mem_mb ?? null)
        setTotalGpu(s?.total_gpu_mb ?? null)
      } catch {}
    } catch { /* 静默 */ }
  }, [])

  const loadFolders = useCallback(async () => {
    try {
      const r = await backendApi.quickFolders()
      if (r?.folders) setFolders(r.folders)
    } catch { /* 静默 */ }
  }, [])

  useEffect(() => {
    refresh()
    loadFolders()
    backendApi.getConfig().then((c) => setHero(c?.preference?.hero_image || null)).catch(() => {})
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [refresh, loadFolders])

  const startEngine = async (key) => {
    setEngineBusy(true); setTip('')
    try {
      const eng = engines.find((e) => e.key === key)
      if (eng?.kind === 'ftn_tag') {
        // 本地 HTML 工具：无需端口/进程，直接在浏览器打开 html 文件
        if (eng.entry) {
          const res = await window.ftn?.openPath?.(eng.entry)
          setTip(res?.ok ? `已打开 ${eng.entry}` : '无法打开（未找到 HTML 文件，请到设置 → 引擎路径确认）')
        } else {
          setTip('未设置 HTML 文件（请到设置 → 引擎路径配置启动文件）')
        }
        setEngineBusy(false)
        return
      }
      const r = await backendApi.engineStart(key)
      if (!r?.ok) {
        const msg = r?.msg || '启动失败'
        setTip(msg)
        // 端口隔离失败：弹窗明确提示哪个端口被谁占用
        if (r?.code === 'port_busy') window.alert(msg)
      } else {
        if (r?.first_run) {
          setTip('首次启动：引擎将自动创建环境并安装依赖（已用国内镜像，需要联网，可能较久），进度请到控制台查看')
        }
        // 启动成功 → 直达控制台对应会话 Tab
        const focusId = r.instance && r.instance > 1 ? `engine:${key}:${r.instance}` : `engine:${key}`
        if (onNavigate) onNavigate('console', focusId)
      }
      setTimeout(refresh, 300)
    }
    catch (e) { setTip(String(e?.message || '启动失败')) }
    finally { setEngineBusy(false) }
  }
  const stopEngine = async () => {
    setEngineBusy(true)
    try { await backendApi.engineStop(sel); setTimeout(refresh, 400) }
    finally { setEngineBusy(false) }
  }
  const restartEngine = async () => {
    setEngineBusy(true)
    try {
      await backendApi.engineStop(sel)
      setTimeout(async () => { await backendApi.engineStart(engine?.engine || sel); refresh() }, 500)
    } finally { setEngineBusy(false) }
  }

  // 全部引擎实例（主实例 + 多开），按引擎判断运行状态
  const instances = engine?.instances || []
  const running = ['starting', 'running'].includes(engine?.status)
  const selRunning = instances.some((i) => i.engine === sel) || (engine?.engine === sel && running)
  const busy = engineBusy || ['starting', 'stopping'].includes(engine?.status)

  const selEng = engines.find((e) => e.key === sel) || null
  const selIsHtml = selEng?.kind === 'ftn_tag'
  // 无路径 → 启动按钮锁定
  const noEntry = !!selEng && !selEng.entry

  // 快捷文件夹：path 由后端解析（主引擎根目录 + 自定义覆盖）
  const currentFolders = folders.length ? folders : [] 
  const openFolder = async (f) => {
    const p = f?.path
    if (!p) { setTip('目录未配置，无法打开'); return }
    if (!window.ftn?.openPath) { setTip(`路径: ${p}`); return }
    const res = await window.ftn.openPath(p)
    setTip(res.ok ? '已打开文件管理器' : `无法打开（目录可能尚未生成）`)
  }

  const heroImg = hero && (hero.startsWith('http') ? hero : `${BACKEND_URL}/api/hero`)

  const mainAction = () => {
    // HTML 工具：只能启动（无 cmd 窗，不提供停止/重启），运行中按钮禁用
    if (selIsHtml) return startEngine(sel)
    if (selRunning) return stopEngine()
    return startEngine(sel)
  }
  const mainLabel = selIsHtml ? '启动' : (selRunning ? '停止' : '启动')
  // 自由多开：只要选中的引擎可启动（有入口）就允许，其他引擎运行不阻塞
  // HTML 工具不做运行保护：运行中仍可再点「启动」（多开/重开）
  const mainDisabled = busy || noEntry

  return (
    <div className="h-full px-10 py-6 flex flex-col" style={{ minHeight: 0 }}>
      {/* 顶栏标题 + 后台状态小角标 */}
      <div className="flex items-center justify-between mb-4 shrink-0">
        <h1 className="text-2xl font-bold">首页</h1>
        <div className="flex items-center gap-2 text-[11px] text-txt-muted">
          {systemInfo && <span>系统 {systemInfo.python}</span>}
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border border-base-border">
            <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--color-accent)' }} />
            后端
          </span>
        </div>
      </div>

      {/* 头图横幅（加高 1.4 倍，其余容器相应压矮） */}
      <section className="rounded-2xl overflow-hidden relative mb-4 shrink-0" style={{ height: 300,
        background: 'linear-gradient(135deg, var(--color-hero-from) -25%, var(--color-hero-to) 120%)' }}>
        {heroImg && <img src={heroImg} alt="hero" className="absolute inset-0 w-full h-full object-cover" onError={(e) => (e.currentTarget.style.display = 'none')} />}
        <div className="absolute inset-0 flex flex-col justify-center px-10 bg-gradient-to-r from-black/35 to-transparent">
          <h1 className="text-4xl font-extrabold text-white drop-shadow">FTN Atelier</h1>
          <p className="text-white/90 mt-2 text-sm drop-shadow">AI 绘画创作工作台 · 引擎 / 模型 / 版本 一站管理</p>
        </div>
      </section>

      {/* 首启引导（简单版）：未配置主引擎时高亮提示 */}
      {!guideDismissed && engines.some((e) => e.primary && !e.entry) && (
        <div className="mb-4 rounded-xl border border-accent/40 bg-accent-soft/30 px-4 py-3 flex items-center gap-3 shrink-0">
          <span className="text-xl">🎯</span>
          <div className="flex-1 text-sm">
            <p className="font-medium">第一步 · 配置主引擎</p>
            <p className="text-xs text-txt-muted mt-0.5">点击左侧「设置 → 引擎路径」，选择你的生图引擎目录（含 webui.bat 的文件夹），即可开始使用。</p>
          </div>
          <button onClick={() => { try { sessionStorage.setItem('ftn_guide_dismissed', '1') } catch {} setGuideDismissed(true) }}
            className="px-3 py-1.5 rounded-lg border border-base-border text-xs hover:bg-base-surface-2 shrink-0">知道了</button>
        </div>
      )}

      {/* 主体：左 引擎启动 + 右 快捷文件夹（占满剩余高度，固定不滚动） */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5 flex-1" style={{ minHeight: 0 }}>
        <section className="lg:col-span-2 rounded-xl border border-base-border bg-base-surface p-5 flex flex-col">
          <h2 className="font-semibold text-txt-secondary mb-3">引擎启动</h2>
          <div className="space-y-1.5 mb-4 overflow-y-auto" style={{ maxHeight: engines.length > 4 ? 148 : 'none' }}>
            {engines.map((e) => {
              const on = instances.some((i) => i.engine === e.key) || (engine?.engine === e.key && running)
              const active = sel === e.key
              const rowLabel = e.primary && !e.entry ? '暂无主引擎' : e.label
              // 占用统计：该引擎全部实例进程树内存/显存合计（html 无进程不显示）
              const st = on && e.kind !== 'ftn_tag'
                ? stats.filter((x) => x.engine === e.key)
                : []
              const rssSum = st.reduce((a, b) => a + (b.rss_mb || 0), 0)
              const gpuSum = st.reduce((a, b) => a + (b.gpu_mb || 0), 0)
              const memPct = totalMem ? Math.round((rssSum / totalMem) * 100) : null
              const gpuPct = totalGpu ? Math.round((gpuSum / totalGpu) * 100) : null
              const statsLine = rssSum || gpuSum
                ? `内存 ${memPct != null ? memPct + '%' : Math.round(rssSum) + 'MB'}`
                  + (gpuSum ? ` · 显存 ${gpuPct != null ? gpuPct + '%' : gpuSum.toFixed(1) + 'GB'}` : '')
                : ''
              // 实际端口（多实例用 / 分隔）
              const ports = instances.filter((i) => i.engine === e.key && i.port).map((i) => i.port).join('/')
              const infoLine = [ports ? `端口 ${ports}` : '', statsLine].filter(Boolean).join(' · ')
              // 内存趋势（历史采样按时间聚合）
              const byTs = {}
              for (const p of history) {
                if (p.engine === e.key) byTs[p.ts] = (byTs[p.ts] || 0) + (p.rss_mb || 0)
              }
              const sparkVals = Object.keys(byTs).sort().slice(-24).map((k) => byTs[k])
              return (
                <button key={e.key} onClick={() => !busy && setSel(e.key)}
                  disabled={!!(busy && engine?.engine !== e.key)}
                  className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-base-surface-2 disabled:opacity-50 text-left cursor-pointer"
                  style={{ background: active ? 'var(--color-accent-soft)' : 'transparent', border: active ? '1px solid var(--color-accent)' : '1px solid transparent' }}>
                  <span className="w-2.5 h-2.5 rounded-full shrink-0"
                    style={{ background: on ? 'var(--color-accent)' : 'var(--color-border)', boxShadow: on ? '0 0 8px var(--color-accent)' : 'none' }} />
                  <span className="flex-1 min-w-0">
                    <span className="block text-sm font-medium truncate" style={{ color: on ? 'var(--color-accent)' : 'var(--color-text-secondary)' }}>
                      {rowLabel}
                      {e.primary && (
                        <span className="ml-1.5 inline-block align-middle relative -top-0.5 text-[9px] px-1 py-0.5 rounded font-bold"
                          style={{ background: 'var(--color-accent-soft)', color: 'var(--color-accent)' }}>主</span>
                      )}
                    </span>
                    {infoLine && <span className="block text-[10px] text-txt-muted truncate">{infoLine}</span>}
                    {on && e.kind !== 'ftn_tag' && sparkVals.length >= 2 && (
                      <span className="block mt-0.5"><Spark values={sparkVals} /></span>
                    )}
                  </span>
                      {e.primary && primaryHealth && primaryHealth.ok === false && (
                        <span title={primaryHealth.warn} className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400">主引擎异常</span>
                      )}
                      {e.primary && e.family && !SUPPORTED_FAMILY.has(e.family) && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400">仅启动/停止</span>
                      )}
                      {on && <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'var(--color-accent-soft)', color: 'var(--color-accent)' }}>运行中</span>}
                </button>
              )
            })}
          </div>

          <div className="flex gap-2 mb-2">
            <button onClick={mainAction} disabled={mainDisabled}
              className="flex-1 px-4 py-2.5 rounded-lg text-white text-sm font-medium disabled:opacity-45 disabled:cursor-not-allowed"
              style={{ background: 'var(--color-accent)' }}>{mainLabel}</button>
            {!selIsHtml && selEng?.entry && (
              <button onClick={restartEngine} disabled={!selRunning}
                className="px-4 py-2.5 rounded-lg border text-sm font-medium disabled:opacity-40"
                style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }}>重启</button>
            )}
          </div>

          {(noEntry || tip) && (
            <p className="text-xs text-amber-400 mt-1">{noEntry ? '未设置启动入口（请到设置 → 引擎路径配置）' : tip}</p>
          )}
          {engine?.status === 'starting' && <p className="text-xs text-amber-400 mt-1">正在启动 {engine.engine}…</p>}
          {primaryHealth && primaryHealth.ok === false && (
            <p className="text-xs text-amber-400 mt-1">⚠ {primaryHealth.warn}</p>
          )}
          {(() => {
            const pe = engines.find((x) => x.primary)
            if (pe && pe.family && !SUPPORTED_FAMILY.has(pe.family)) {
              return (
                <p className="text-xs text-amber-400 mt-1">
                  ⚠ 当前主引擎为 {FAMILY_LABEL[pe.family] || pe.family} 类型，暂未适配：仅支持启动/停止/重启，模型/插件/版本下载等显示「不适用」。
                </p>
              )
            }
            return null
          })()}
          {engine?.diagnosis?.length > 0 && (
            <div className="mt-2 rounded-lg border border-amber-400/40 bg-amber-500/10 p-2.5 text-xs text-amber-400 space-y-1">
              <p className="font-medium">⚠ 启动失败诊断：</p>
              {engine.diagnosis.map((d) => (
                <p key={d.key}>· {d.title}：{d.suggestion}</p>
              ))}
            </div>
          )}
        </section>

        <section className="lg:col-span-3 rounded-xl border border-base-border bg-base-surface p-5 flex flex-col">
          <h2 className="font-semibold text-txt-secondary mb-3">快捷文件夹</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 content-start overflow-y-auto"
            style={{ maxHeight: currentFolders.length > 9 && currentFolders.length ? 332 : 'none' }}>
            {(currentFolders.length ? currentFolders : [] ).map((f) => (
              <button key={f.key} onClick={() => openFolder(f)}
                className="rounded-lg border border-base-border p-4 hover:border-accent/50 text-left transition-all hover:-translate-y-0.5"
                style={{ background: 'var(--color-surface-2)' }}>
                <div className="text-sm font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>{f.label}</div>
                <div className="text-[11px] text-txt-muted truncate">{f.path || '未配置'}</div>
              </button>
            ))}
            {!currentFolders.length && <p className="text-sm text-txt-muted col-span-full py-2">快捷文件夹加载中...</p>}
          </div>
        </section>
      </div>
    </div>
  )
}

// 微型占用趋势图（SVG 折线，无第三方依赖）
function Spark({ values, w = 56, h = 14 }) {
  if (!values || values.length < 2) return <span className="text-[10px] text-txt-muted">—</span>
  const max = Math.max(...values, 1)
  const pts = values
    .map((v, i) => `${((i / (values.length - 1)) * w).toFixed(1)},${(h - (v / max) * h).toFixed(1)}`)
    .join(' ')
  return (
    <svg width={w} height={h} className="align-middle">
      <polyline points={pts} fill="none" strokeWidth="1.5" strokeLinejoin="round" style={{ stroke: 'var(--color-accent)' }} />
    </svg>
  )
}
