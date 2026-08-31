import React, { useEffect, useState, useCallback, useRef } from 'react'
import { backendApi } from '../services/apiClient'
import { motion, AnimatePresence } from 'framer-motion'
import { startUpdate } from '../utils/updater'

// 状态 → 图标 / 颜色 / 中文
const STATUS_META = {
  ok: { icon: '✔', cls: 'text-emerald-400 bg-emerald-500/10 border-emerald-400/30' },
  warn: { icon: '⚠', cls: 'text-amber-400 bg-amber-500/10 border-amber-400/30' },
  error: { icon: '✘', cls: 'text-rose-400 bg-rose-500/10 border-rose-400/30' },
}

// ============================================
// 启动前自检引导弹窗
//   mode='startup'  ：启动进软件前的全屏引导（阻塞主界面，完成后点「进入 FTN Atelier」）
//   mode='manual'   ：从设置「立即自检」呼出（完成后点「关闭」）
// 行为：逐项检测 → 可修复项询问是否修复 → 不可修复项提示；最后版本更新检测（可选）→ 完成
// ============================================
export default function SelfCheckModal({ mode = 'startup', checkUpdate = true, standalone = false, onEnter, onClose }) {
  const [phase, setPhase] = useState('loading') // loading | done
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)          // 后端声明的自检总项数（用于占位行 + 完成度进度条）
  const [current, setCurrent] = useState(null)   // 当前被询问/处理的项
  const [updateInfo, setUpdateInfo] = useState(undefined) // undefined=未检 | {..} 结果
  const [updating, setUpdating] = useState(null)          // {pct, msg, error?} 更新进度/错误
  const [updateSkipped, setUpdateSkipped] = useState(false) // 用户点了「暂不更新」
  const [busy, setBusy] = useState(false)
  const [fatal, setFatal] = useState(null)       // 无法自动修复的提示
  const [handled, setHandled] = useState({})     // {key:true} 已处理（已修复 或 用户选择跳过）的可修复项
  const [logo, setLogo] = useState(null)         // 应用 Logo（独立小窗展示，统一视觉）
  const ranOnce = useRef(false)
  const runSeq = useRef(0)                        // 轮询序号：防止旧任务的轮询覆盖新任务

  useEffect(() => {
    if (!standalone) return
    window.ftn?.getLogo?.().then((r) => { if (r?.ok) setLogo(r.dataUrl) }).catch(() => {})
  }, [standalone])

  const runSelfCheck = useCallback(async () => {
    const myRun = ++runSeq.current
    setPhase('loading')
    setFatal(null)
    setHandled({})
    setItems([])
    setTotal(0)
    setUpdateSkipped(false)
    try {
      // 异步自检：逐项完成 → 轮询拉取 → 进度条逐步推进
      const start = await backendApi.selfcheckStart()
      if (!start?.task_id) throw new Error('无法启动自检')
      const tid = start.task_id
      const deadline = Date.now() + 30000   // 兜底：30s 未完成不卡界面
      await new Promise((resolve, reject) => {
        const tick = async () => {
          try {
            if (Date.now() > deadline) {
              setFatal('自检超时，请点「重新检测」重试')
              resolve()
              return
            }
            const s = await backendApi.selfcheckStatus(tid)
            if (runSeq.current !== myRun) return  // 已重新检测，丢弃旧轮询
            if (!s?.ok) { reject(new Error(s?.msg || '自检状态读取失败')); return }
            setItems(s.items || [])
            setTotal(Math.max(s.total || 0, (s.items || []).length))
            // 项数到齐即完成（不依赖 done 标志滞后），避免 100% 仍显示"检测中"
            if (s.done || (s.items?.length || 0) >= (s.total || 0)) { resolve(); return }
            setTimeout(tick, 180)
          } catch (e) { reject(e) }
        }
        tick()
      })
      setPhase('done')
    } catch (e) {
      setFatal(`无法连接后端执行自检：${e.message}`)
      setPhase('done')
    }
  }, [])

  // 版本更新检测（仅在启动 gate 且开启了自动检测时执行）
  const runUpdateCheck = useCallback(async () => {
    try {
      const u = await backendApi.selfcheckUpdate()
      setUpdateInfo(u)
    } catch {
      setUpdateInfo({ ok: false, current: '?', error: '无法检测更新' })
    }
  }, [])

  useEffect(() => {
    if (ranOnce.current) return
    ranOnce.current = true
    runSelfCheck()
    if (checkUpdate && mode === 'startup') runUpdateCheck()
  }, [runSelfCheck, runUpdateCheck, checkUpdate, mode])

  // 可修复项：询问是否修复
  const askFix = (item) => setCurrent(item)
  // 用户选择「暂不修复」：标记该项已处理（跳过），不再阻塞进入
  const skipFix = () => {
    if (current) setHandled((h) => ({ ...h, [current.key]: true }))
    setCurrent(null)
  }
  const doRepair = async () => {
    if (!current) return
    setBusy(true)
    try {
      const r = await backendApi.selfcheckFix(current.key)
      setItems(r.ok_after?.items || items)
      // 修复成功（或该项已不再可修复）→ 标记已处理
      const stillFixable = (r.ok_after?.items || items).some((i) => i.key === current.key && i.status !== 'ok' && i.fixable)
      if (!stillFixable) setHandled((h) => ({ ...h, [current.key]: true }))
      setFatal(r.ok ? null : `修复未完全成功：${r.msg}`)
    } catch (e) {
      setFatal(`修复失败：${e.message}`)
    } finally {
      setBusy(false)
      setCurrent(null)
    }
  }

  const done = () => (mode === 'startup' && onEnter ? onEnter() : onClose && onClose())

  const fixables = items.filter((i) => i.status !== 'ok' && i.fixable && !handled[i.key])
  const unfixables = items.filter((i) => i.status !== 'ok' && !i.fixable)
  const pendingFixables = fixables.length
  const canEnter = phase === 'done' && !fatal && pendingFixables === 0 && !current
  const updatingBusy = !!updating && !updating.error

  // 一键更新：下载 → 进度 → Electron 应用替换（程序会自动重启）
  const beginUpdate = async () => {
    setUpdating({ pct: 0, msg: '正在启动更新…' })
    await startUpdate({
      onProgress: (phase, pct, msg) => setUpdating({ pct: pct ?? 0, msg }),
      onError: (err) => setUpdating({ pct: 0, msg: err, error: true }),
      assetUrl: updateInfo?.asset?.url,
      expectedVersion: updateInfo?.latest,
    })
  }
  const okCount = items.filter((i) => i.status === 'ok').length
  // 占位行：后端声明 total 后立即铺满（未完成项显示"正在检测…"），
  // 进度条按「已完成 / 总数」推进，不再因前几项全正常而虚报 100%。
  const totalRows = Math.max(total, items.length, 0)
  const rows = Array.from({ length: totalRows }, (_, i) => items[i] || null)
  const pct = totalRows ? Math.round((items.length / totalRows) * 100) : 0
  const allOk = phase === 'done' && items.length > 0 &&
    items.every((i) => i.status === 'ok') && !fatal && !current && !updateInfo?.has_update

  // 无异常：自检完成后自动进入（独立小窗场景）
  useEffect(() => {
    if (!standalone || !allOk) return
    const t = setTimeout(done, 600)
    return () => clearTimeout(t)
  }, [standalone, allOk])  // eslint-disable-line react-hooks/exhaustive-deps

  // ============================================
  // 独立小窗（启动自检）：游戏启动器式整体外观
  // ============================================
  if (standalone) {
    return (
      <div className="relative h-screen w-screen overflow-hidden bg-base-bg text-txt-primary">
        {/* 拖拽栏 */}
        <div className="app-drag absolute top-0 left-0 right-0 h-9 flex items-center px-4 select-none z-10">
          <span className="text-[11px] text-txt-muted tracking-[0.15em]">FTN ATELIER · 启动自检</span>
          <button
            onClick={() => window.close()}
            title="跳过自检并进入"
            className="app-no-drag ml-auto w-6 h-6 flex items-center justify-center rounded-md text-txt-muted hover:text-white hover:bg-white/10 text-sm"
          >✕</button>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: 'easeOut' }}
          className="relative z-[1] h-full flex flex-col px-9 pt-14 pb-6"
        >
          {/* 品牌区 */}
          <div className="flex flex-col items-center text-center shrink-0">
            <div className="w-16 h-16 flex items-center justify-center">
              {logo
                ? <img src={logo} alt="FTN Atelier" className="w-full h-full object-contain" />
                : <span className="text-3xl">🛠️</span>}
            </div>
            <h1 className="mt-4 text-[26px] font-extrabold tracking-wide leading-none">FTN Atelier</h1>
            <p className="mt-2 text-xs text-txt-muted">AI 创作工作台 · 正在检测运行环境</p>
          </div>

          {/* 进度卡 */}
          <div className="mt-6 shrink-0 rounded-2xl border border-base-border bg-base-surface/70 backdrop-blur px-5 py-4">
            <div className="flex items-center justify-between text-xs mb-2">
              <span className="text-txt-secondary font-medium">{phase === 'loading' ? '正在逐项检测…' : '自检完成'}</span>
              <span className="text-txt-muted">
                {items.length}/{totalRows || '?'} 项 · {okCount} 项正常 · {pct}%
              </span>
            </div>
            <div className="h-2.5 rounded-full bg-base-surface-2 overflow-hidden">
              <motion.div
                className="h-full rounded-full"
                animate={{ width: `${pct}%` }}
                transition={{ duration: 0.4, ease: 'easeOut' }}
                style={{
                  background: 'linear-gradient(90deg, var(--color-accent), var(--color-accent-hover))',
                  boxShadow: '0 0 14px color-mix(in srgb, var(--color-accent) 65%, transparent)',
                }}
              />
            </div>
          </div>

          {/* 检测项 / 提示区（可滚动） */}
          <div className="flex-1 min-h-0 mt-4 space-y-2 overflow-auto pr-1">
            {phase === 'loading' && items.length === 0 && (
              <p className="text-sm text-txt-muted text-center py-10">正在检测环境…</p>
            )}
            {rows.map((it, idx) => {
              if (!it) {
                return (
                  <motion.div
                    key={`pending-${idx}`}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="flex items-center gap-3 rounded-xl border border-base-border/60 bg-base-surface-2/40 px-3.5 py-2.5"
                  >
                    <span className="w-3.5 h-3.5 rounded-full border-2 border-base-border border-t-accent animate-spin shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-txt-muted">正在检测…</div>
                    </div>
                  </motion.div>
                )
              }
              const m = STATUS_META[it.status] || STATUS_META.warn
              return (
                <motion.div
                  key={it.key}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={`flex items-start gap-3 rounded-xl border px-3.5 py-2.5 ${m.cls}`}
                >
                  <span className="mt-0.5 text-sm leading-none">{m.icon}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium">{it.label}</div>
                    <div className="text-[11px] text-txt-muted leading-snug break-words">{it.message}</div>
                  </div>
                  {it.status === 'ok' && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 shrink-0">正常</span>
                  )}
                  {it.status !== 'ok' && it.fixable && !handled[it.key] && (
                    <button
                      onClick={() => askFix(it)}
                      className="px-2.5 py-1 rounded-md bg-accent/15 text-accent text-xs hover:bg-accent/25 shrink-0"
                    >{current?.key === it.key ? '…' : '修复'}</button>
                  )}
                  {it.status !== 'ok' && it.fixable && handled[it.key] && (
                    <span className="px-2 py-1 rounded-md bg-base-surface-2 text-txt-muted text-xs shrink-0">已跳过</span>
                  )}
                </motion.div>
              )
            })}
            {phase === 'done' && items.length === 0 && (
              <p className="text-sm text-txt-muted text-center py-8">没有可检测项</p>
            )}

            {/* 修复询问 */}
            <AnimatePresence>
              {current && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                  className="p-3.5 rounded-xl border border-accent/40 bg-accent-soft/30 text-sm">
                  <p>检测到：<b>{current.label}</b> — {current.message}</p>
                  <p className="text-xs text-txt-muted mt-1">是否立即修复该问题？（自动执行修复）</p>
                  <div className="mt-2 flex gap-2 justify-end">
                    <button onClick={skipFix} disabled={busy} className="px-3 py-1.5 rounded-md border border-base-border text-xs">暂不修复（跳过）</button>
                    <button onClick={doRepair} disabled={busy} className="px-3 py-1.5 rounded-md bg-accent text-white text-xs disabled:opacity-50">{busy ? '修复中…' : '是，立即修复'}</button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* 版本更新检测 */}
            {updateInfo && !updateSkipped && (
              <div className={`p-3.5 rounded-xl border text-sm ${
                updateInfo.has_update ? 'border-accent/50 bg-accent-soft/30' : 'border-base-border bg-base-surface-2/40'
              }`}>
                {updateInfo.has_update ? (
                  updating ? (
                    <div>
                      <p className="font-medium text-accent">🔄 正在更新到 v{updateInfo.latest}…</p>
                      <div className="mt-2 h-2 rounded-full bg-base-surface-2 overflow-hidden">
                        <div className="h-full bg-accent transition-all duration-300" style={{ width: `${updating.pct || 0}%` }} />
                      </div>
                      <p className={`mt-1.5 text-xs break-words ${updating.error ? 'text-rose-400' : 'text-txt-muted'}`}>{updating.msg}</p>
                      {updating.error && (
                        <div className="mt-2 flex justify-end">
                          <button onClick={done} className="px-3 py-1.5 rounded-md border border-base-border text-xs">关闭</button>
                        </div>
                      )}
                    </div>
                  ) : (
                  <>
                    <p className="font-medium text-accent">🔄 检测到新版本：v{updateInfo.latest}（当前 v{updateInfo.current}）</p>
                    <p className="text-xs text-txt-muted mt-1 break-words">{updateInfo.body || '建议更新到最新版本，获得修复与新功能。'}</p>
                    <div className="mt-2 flex gap-2 justify-end">
                      <button onClick={() => setUpdateSkipped(true)} className="px-3 py-1.5 rounded-md border border-base-border text-xs">暂不更新</button>
                      <button onClick={beginUpdate} className="px-3 py-1.5 rounded-md bg-accent text-white text-xs">开始更新</button>
                    </div>
                  </>
                  )
                ) : updateInfo.ok !== false && !updateInfo.error ? (
                  <p className="text-txt-muted">✔ 当前已是最新版本（v{updateInfo.current}）</p>
                ) : updateInfo.config_missing ? (
                  <div className="text-txt-muted">
                    <p>ℹ 未配置更新源，暂不检查更新。</p>
                  </div>
                ) : (
                  <p className="text-txt-muted">ℹ 无法检测更新：{updateInfo.error || '未知'}（稍后可在设置→软件修复更新重试）</p>
                )}
              </div>
            )}

            {/* 无法自动修复 / 致命提示 */}
            {fatal && (
              <div className="p-3.5 rounded-xl border border-amber-400/50 bg-amber-500/10 text-sm text-amber-400">
                ⚠️ {fatal}
              </div>
            )}
            {phase === 'done' && unfixables.length > 0 && !fatal && (
              <div className="p-3.5 rounded-xl border border-amber-400/50 bg-amber-500/10 text-sm text-amber-400">
                <p>以下问题<b>无法自动修复</b>，请手动检查：
                  {unfixables.map((u) => (
                    <div key={u.key} className="text-xs mt-1.5 pl-2 border-l-2 border-amber-400/40">
                      <b>{u.label}</b>：{u.message}
                    </div>
                  ))}
                </p>
              </div>
            )}
          </div>

          {/* 底部 */}
          <div className="mt-4 pt-4 border-t border-base-border flex items-center justify-between gap-3 shrink-0">
            <button onClick={runSelfCheck} disabled={busy || updatingBusy}
              className="px-3.5 py-2 rounded-lg border border-base-border text-sm text-txt-muted hover:bg-base-surface-2 disabled:opacity-40">重新检测</button>
            <button
              onClick={done}
              disabled={!canEnter || updatingBusy}
              className="px-6 py-2 rounded-lg text-white text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
              style={{
                background: 'linear-gradient(135deg, var(--color-accent), var(--color-accent-hover))',
                boxShadow: '0 10px 24px -10px color-mix(in srgb, var(--color-accent) 70%, transparent)',
              }}
            >
              {canEnter ? '进入 FTN Atelier' : (phase === 'done' ? '有异常待处理' : '检测中…')}
            </button>
          </div>
          <p className="text-center text-[10px] text-txt-muted mt-3 shrink-0 tracking-widest">FTN STUDIO · 非侵入式 SD WebUI 工作台</p>
        </motion.div>
      </div>
    )
  }

  // ============================================
  // 手动检测（盖在主窗口上的弹窗）
  // ============================================
  return (
    <div className={standalone
      ? 'h-screen w-screen flex flex-col bg-base-bg text-txt-primary overflow-hidden'
      : 'fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-6'}>
      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.25 }}
        className={standalone
          ? 'flex-1 min-h-0 flex flex-col'
          : 'w-full max-w-xl rounded-2xl border border-base-border bg-base-surface shadow-2xl overflow-hidden'}
      >
        {/* 顶栏 */}
        {standalone ? (
          <div className="app-drag px-8 pt-7 pb-3 flex items-center gap-3 shrink-0 select-none">
            <span className="text-3xl">🛠️</span>
            <div className="flex-1 min-w-0">
              <h1 className="text-xl font-extrabold leading-tight">FTN Atelier</h1>
              <p className="text-xs text-txt-muted mt-0.5">正在检测运行环境，请稍候…</p>
            </div>
            <span className="app-no-drag text-[11px] px-2 py-1 rounded-md border border-base-border text-txt-muted shrink-0">
              {phase === 'loading'
                ? `检测中… ${items.length}/${totalRows || '?'}`
                : `${okCount}/${totalRows || items.length} 项正常`}
            </span>
          </div>
        ) : (
          <div className="px-6 py-4 border-b border-base-border flex items-center gap-3">
            <span className="text-2xl">🛠️</span>
            <div className="flex-1">
              <h2 className="text-lg font-bold">启动自检</h2>
              <p className="text-xs text-txt-muted">检测完成前不会进入软件界面</p>
            </div>
            <span className="text-[11px] px-2 py-1 rounded-md border border-base-border text-txt-muted">
              {phase === 'loading'
                ? `检测中… ${items.length}/${totalRows || '?'}`
                : `${okCount}/${totalRows || items.length} 项正常`}
            </span>
          </div>
        )}

        {/* 进度条 */}
        <div className={standalone ? 'px-8 mb-3 shrink-0' : 'px-5 pt-4'}>
          <div className="h-2 rounded-full bg-base-surface-2 overflow-hidden">
            <div className="h-full bg-accent transition-all duration-500" style={{ width: `${pct}%` }} />
          </div>
          <div className="mt-1 text-[11px] text-txt-muted flex justify-between">
            <span>{phase === 'loading' ? '正在逐项检测…' : '自检完成'}</span>
            <span>{pct}%</span>
          </div>
        </div>

        {/* 状态列表 */}
        <div className={standalone
          ? 'flex-1 min-h-0 px-8 pb-4 overflow-auto space-y-2'
          : 'p-5 max-h-[52vh] overflow-auto space-y-2'}>
          {phase === 'loading' && items.length === 0 && (
            <p className="text-sm text-txt-muted text-center py-8">正在检测环境…</p>
          )}
          {rows.map((it, idx) => {
            if (!it) {
              return (
                <div key={`pending-${idx}`} className="flex items-center gap-3 rounded-lg border border-base-border/60 bg-base-surface-2/40 px-3.5 py-2.5">
                  <span className="w-3.5 h-3.5 rounded-full border-2 border-base-border border-t-accent animate-spin shrink-0" />
                  <div className="text-sm text-txt-muted">正在检测…</div>
                </div>
              )
            }
            const m = STATUS_META[it.status] || STATUS_META.warn
            return (
              <div key={it.key} className={`flex items-start gap-3 rounded-lg border px-3.5 py-2.5 ${m.cls}`}>
                <span className="mt-0.5 text-sm leading-none">{m.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium">{it.label}</div>
                  <div className="text-[11px] text-txt-muted leading-snug break-words">{it.message}</div>
                </div>
                {it.status !== 'ok' && it.fixable && !handled[it.key] && (
                  <button
                    onClick={() => askFix(it)}
                    className="px-2.5 py-1 rounded-md bg-accent/15 text-accent text-xs hover:bg-accent/25 shrink-0"
                  >{current?.key === it.key ? '…' : '修复'}</button>
                )}
                {it.status !== 'ok' && it.fixable && handled[it.key] && (
                  <span className="px-2 py-1 rounded-md bg-base-surface-2 text-txt-muted text-xs shrink-0">已跳过</span>
                )}
              </div>
            )
          })}
          {phase === 'done' && items.length === 0 && <p className="text-sm text-txt-muted text-center py-8">没有可检测项</p>}
        </div>

        {/* 修复询问 / 结果 / 更新提示 */}
        <AnimatePresence>
          {current && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="mx-5 mb-3 p-3.5 rounded-lg border border-accent/40 bg-accent-soft/30 text-sm">
              <p>检测到：<b>{current.label}</b> — {current.message}</p>
              <p className="text-xs text-txt-muted mt-1">是否立即修复该问题？（自动执行修复）</p>
              <div className="mt-2 flex gap-2 justify-end">
                <button onClick={skipFix} disabled={busy} className="px-3 py-1.5 rounded-md border border-base-border text-xs">暂不修复（跳过）</button>
                <button onClick={doRepair} disabled={busy} className="px-3 py-1.5 rounded-md bg-accent text-white text-xs disabled:opacity-50">{busy ? '修复中…' : '是，立即修复'}</button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* 升级检测提示 */}
        {mode === 'startup' && updateInfo && (
          <div className={`mx-5 mb-3 p-3.5 rounded-lg border text-sm ${
            updateInfo.has_update ? 'border-accent/50 bg-accent-soft/30' : 'border-base-border bg-base-surface-2/40'
          }`}>
            {updateInfo.has_update ? (
              <>
                <p className="font-medium text-accent">🔄 检测到新版本：v{updateInfo.latest}（当前 v{updateInfo.current}）</p>
                <p className="text-xs text-txt-muted mt-1 break-words">{updateInfo.body || '建议更新到最新版本，获得修复与新功能。'}</p>
                <div className="mt-2 flex gap-2 justify-end">
                  <button onClick={done} className="px-3 py-1.5 rounded-md border border-base-border text-xs">暂不更新</button>
                  <button onClick={() => updateInfo.url && window.ftn?.openPath && window.ftn.openPath(updateInfo.url)}
                    className="px-3 py-1.5 rounded-md bg-accent text-white text-xs">前往更新</button>
                </div>
              </>
            ) : updateInfo.ok !== false && !updateInfo.error ? (
              <p className="text-txt-muted">✔ 当前已是最新版本（v{updateInfo.current}）</p>
            ) : updateInfo.config_missing ? (
              <div className="text-txt-muted">
                <p>ℹ 未配置更新源，暂不检查更新。</p>
              </div>
            ) : (
              <p className="text-txt-muted">ℹ 无法检测更新：{updateInfo.error || '未知'}（稍后可在设置→软件修复更新重试）</p>
            )}
          </div>
        )}

        {/* 无法自动修复提示 + 底部按钮 */}
        {fatal && (
          <div className="mx-5 mb-3 p-3.5 rounded-lg border border-amber-400/50 bg-amber-500/10 text-sm text-amber-400">
            ⚠️ {fatal}
          </div>
        )}
        {phase === 'done' && unfixables.length > 0 && !fatal && (
          <div className="mx-5 mb-3 p-3.5 rounded-lg border border-amber-400/50 bg-amber-500/10 text-sm text-amber-400">
            <p>以下问题<b>无法自动修复</b>，请手动检查：
              {unfixables.map((u) => (
                <div key={u.key} className="text-xs mt-1.5 pl-2 border-l-2 border-amber-400/40">
                  <b>{u.label}</b>：{u.message}
                </div>
              ))}
            </p>
          </div>
        )}

        {/* 底部 */}
        <div className={standalone
          ? 'px-8 py-4 border-t border-base-border flex items-center justify-between gap-3 shrink-0'
          : 'px-5 py-4 border-t border-base-border flex items-center justify-between gap-3'}>
          <button onClick={runSelfCheck} disabled={busy} className="px-3 py-2 rounded-lg border border-base-border text-sm text-txt-muted hover:bg-base-surface-2 disabled:opacity-40">重新检测</button>
          <div className="flex gap-2 ml-auto">
            {mode === 'manual' && (
              <button onClick={done} className="px-4 py-2 rounded-lg border border-base-border text-sm">关闭</button>
            )}
            <button
              onClick={done}
              disabled={mode === 'startup' && !canEnter}
              className="px-5 py-2 rounded-lg bg-accent text-white text-sm disabled:opacity-50"
            >
              {mode === 'startup' ? (canEnter ? '进入 FTN Atelier' : (phase === 'done' ? '有异常待处理' : '检测中…')) : '完成'}
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  )
}
