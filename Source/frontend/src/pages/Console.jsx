import React, { useEffect, useRef, useState, useCallback } from 'react'
import { backendApi } from '../services/apiClient'
import { useSocket } from '../hooks/useSocket'

// 等级标签（跟随语言，正常/警告/错误）
const LEVEL_INFO = { INFO: '正常', WARN: '警告', ERROR: '错误', DEBUG: '调试', FATAL: '致命' }
const LEVEL_COLOR = { INFO: '#22c55e', WARN: '#f59e0b', ERROR: '#ef4444', DEBUG: '#94a3b8', FATAL: '#dc2626' }

export default function Console({ initialFocus = null }) {
  const [sessions, setSessions] = useState([])      // 自动挂载的引擎会话（实际运行才出现）
  const [active, setActive] = useState('backend')    // 当前 Tab：'backend' | 会话 id
  const [content, setContent] = useState('')         // 当前源日志全文
  const [loading, setLoading] = useState(false)
  const [notice, setNotice] = useState('')
  const [stopping, setStopping] = useState({})
  const bodyRef = useRef(null)
  const { lastMessage } = useSocket()

  const activeSession = sessions.find((s) => s.id === active)
  const activeSource = active === 'backend' ? 'backend' : (activeSession?.log_source || active)
  const activeLabel = active === 'backend' ? '客户端' : (activeSession?.title || active)
  const liveCount = sessions.filter((s) => ['starting', 'running', 'stopping'].includes(s.status)).length

  // 加载会话列表（轮询：引擎启动自动新增 / 停止自动消失）
  const loadSessions = useCallback(async () => {
    try {
      const r = await backendApi.consoleSessions()
      const list = r?.sessions || []
      setSessions(list)
      // 引擎启动后直达对应会话 Tab
      if (initialFocus && list.some((s) => s.id === initialFocus)) setActive(initialFocus)
      setActive((prev) => {
        if (prev !== 'backend' && !list.some((s) => s.id === prev)) {
          setNotice('当前引擎会话已结束')
          return 'backend'
        }
        return prev
      })
    } catch { /* 后端离线等场景静默 */ }
  }, [initialFocus])

  // 加载当前源日志
  const loadFile = useCallback(async (cat) => {
    setLoading(true)
    try {
      const r = await backendApi.logsFile(cat, 800)
      setContent(r?.content || '')
    } catch { setContent('（读取失败）') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { loadFile(activeSource) }, [activeSource, loadFile])

  useEffect(() => {
    loadSessions()
    const t = setInterval(loadSessions, 2000)
    return () => clearInterval(t)
  }, [loadSessions])

  // 实时日志追加（仅当推送源 == 当前查看源）
  useEffect(() => {
    if (lastMessage && lastMessage.type === 'log') {
      const rec = lastMessage.record
      if (rec && (rec.source || 'backend') === activeSource) {
        const line = `[${rec.time}] [${rec.level}] ${rec.content}\n`
        setContent((prev) => {
          const next = prev + line
          const lines = next.split('\n')
          return lines.length > 20000 ? lines.slice(-20000).join('\n') : next
        })
      }
    }
  }, [lastMessage, activeSource])

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight
  }, [content])

  // 提示自动消失
  useEffect(() => {
    if (!notice) return
    const t = setTimeout(() => setNotice(''), 3500)
    return () => clearTimeout(t)
  }, [notice])

  // 关闭会话（仅终止该引擎实例，不影响其他实例/引擎）
  const stopSession = async (sid) => {
    setStopping((s) => ({ ...s, [sid]: true }))
    try {
      const r = await backendApi.consoleSessionStop(sid)
      if (!r?.ok && r?.msg) setNotice(r.msg)
      setTimeout(loadSessions, 400)
    } catch (e) { setNotice(String(e?.message || '停止失败')) }
    finally { setStopping((s) => ({ ...s, [sid]: false })) }
  }

  const progress = loading ? 1 : 0

  return (
    <div className="h-full p-6 flex flex-col" style={{ minHeight: 0 }}>
      {/* 顶栏：浏览器式标签（引擎启动的 cmd 自动挂载，名字与引擎对应） */}
      <div className="flex items-center gap-2 mb-3 shrink-0 flex-wrap">
        <h1 className="text-xl font-bold mr-1">控制台</h1>
        <div className="flex items-center gap-1 overflow-x-auto py-0.5 max-w-full">
          {/* 客户端日志固定 Tab（非会话，不可关闭） */}
          <button
            onClick={() => setActive('backend')}
            className={[
              'px-3 py-1.5 rounded-t-lg border text-sm whitespace-nowrap transition-colors flex items-center gap-1.5',
              active === 'backend'
                ? 'border-b-2 border-accent text-accent font-medium bg-accent-soft/60'
                : 'border-base-border text-txt-muted hover:text-txt-primary hover:bg-base-surface-2',
            ].join(' ')}
            title="客户端日志"
          >
            <span>⚙</span>
            客户端
          </button>

          {sessions.map((s) => {
            const on = active === s.id
            const ended = ['stopped', 'exited', 'error'].includes(s.status)
            return (
              <div key={s.id} className="flex items-stretch">
                <button
                  onClick={() => setActive(s.id)}
                  className={[
                    'px-3 py-1.5 rounded-t-lg border text-sm whitespace-nowrap transition-colors flex items-center gap-1.5',
                    on
                      ? 'border-b-2 border-accent text-accent font-medium bg-accent-soft/60'
                      : 'border-base-border text-txt-muted hover:text-txt-primary hover:bg-base-surface-2',
                    ended && 'opacity-60',
                  ].join(' ')}
                  title={`引擎 · ${s.title}`}
                >
                  <span>⌘</span>
                  {s.title}
                  {s.status === 'starting' && <span className="text-[10px] text-amber-400">启动中</span>}
                  {s.status === 'running' && on && <span className="text-[10px] text-accent">●</span>}
                  {s.status === 'stopping' && <span className="text-[10px] text-amber-400">停止中</span>}
                  {ended && <span className="text-[10px] px-1 rounded bg-base-surface-2 text-txt-muted">已结束</span>}
                </button>
                {/* 关闭：仅终止本引擎实例 */}
                {!ended && (
                  <button
                    onClick={() => stopSession(s.id)}
                    disabled={!!stopping[s.id]}
                    title="关闭此引擎实例（仅终止对应进程）"
                    className={[
                      'px-1.5 rounded-r-lg border-l-0 border text-sm transition-colors disabled:opacity-40',
                      on
                        ? 'border-b-2 border-accent text-accent hover:bg-accent-soft/60'
                        : 'border-base-border text-txt-muted hover:text-red-400 hover:bg-red-500/10',
                    ].join(' ')}
                  >
                    ×
                  </button>
                )}
              </div>
            )
          })}
          {sessions.length === 0 && (
            <span className="text-xs text-txt-muted px-1">启动引擎后，对应控制台标签会自动出现</span>
          )}
        </div>
        <span className="ml-auto text-[11px] text-txt-muted">引擎 cmd 自动挂载 · 日志导出请到「疑难解答」</span>
      </div>

      {/* 加载进度条 */}
      <div className="h-0.5 mb-2 rounded overflow-hidden bg-base-surface-2 shrink-0" style={{ opacity: progress ? 1 : 0.35 }}>
        <div className="h-full transition-all duration-500"
          style={{ width: progress ? (loading ? '70%' : '100%') : '0%', background: 'var(--color-accent)' }} />
      </div>

      {/* 日志主体（每个引擎实例独立输出流） */}
      <div ref={bodyRef} className="flex-1 rounded-xl border border-base-border bg-black/50 p-3 overflow-auto font-mono text-xs leading-relaxed" style={{ minHeight: 0 }}>
        {loading && !content ? <p className="text-txt-muted">加载中...</p>
          : !content && !loading ? <p className="text-txt-muted">（{activeLabel} 暂无日志记录）</p>
          : content.split('\n').filter((l) => l.trim()).map((line, i) => {
              const m = line.match(/\[(INFO|WARN|ERROR|DEBUG|FATAL)\]/)
              const lv = m ? m[1] : null
              return (
                <div key={i} className="break-all">
                  {lv && (
                    <span className="inline-block w-16 mr-1 px-1 rounded text-center"
                      style={{ background: `${LEVEL_COLOR[lv]}22`, color: LEVEL_COLOR[lv] }}>{LEVEL_INFO[lv]}</span>
                  )}
                  <span style={{ color: lv ? '#cbd5e1' : 'var(--color-text-muted)' }}>{line}</span>
                </div>
              )
            })}
      </div>

      {notice && <p className="text-[11px] text-amber-400 mt-2 shrink-0">{notice}</p>}

      <div className="text-[11px] text-txt-muted mt-2 shrink-0 flex items-center gap-3 flex-wrap">
        <span>当前：{activeLabel}{activeSession && activeSession.pid ? ` (pid ${activeSession.pid})` : ''}</span>
        <span>运行中引擎实例：{liveCount}</span>
        <span className="ml-auto">引擎进程已隐藏 · 输出集成于此 · 日志自动保留最近 30 份</span>
      </div>
    </div>
  )
}
