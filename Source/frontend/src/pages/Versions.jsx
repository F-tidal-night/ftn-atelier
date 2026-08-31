import React, { useEffect, useState, useCallback } from 'react'
import { backendApi } from '../services/apiClient'
import { IconEngine, IconSettings } from '../components/icons'

// ============================================
// M5 版本管理：多基底版本列表、当前标记、切换、下载、更新保护、插件
//   基底：reForge / Forge 等（小菜单分隔）
//   插件：与基底分开的小菜单（子分区）
// ============================================

export default function Versions() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [protectedPaths, setProtectedPaths] = useState([])
  const [msg, setMsg] = useState(null)
  const [active, setActive] = useState(null)
  const [selBase, setSelBase] = useState(null)          // 当前查看的基底 key
  const [subTab, setSubTab] = useState('base')          // base / plugins 子分区
  const [plugs, setPlugs] = useState(null)
  const [plugsUnsupported, setPlugsUnsupported] = useState(false)
  const [plugMsg, setPlugMsg] = useState(null)
  const [dlTask, setDlTask] = useState(null)   // 下载后台任务 {taskId,label,version,status,progress,log,error}
  const [opTask, setOpTask] = useState(null)   // 更新/回退后台任务 {taskId,type,status,progress,log,error}

  const load = useCallback(async () => {
    setLoading(true)
    try {
      // 各端点独立容错：单个失败不阻塞版本页整体渲染
      const [snapR, protR, plugsR] = await Promise.allSettled([
        backendApi.versionsSnapshot(),
        backendApi.versionsProtected(),
        backendApi.pluginsList(),
      ])
      const snap = snapR.status === 'fulfilled' ? snapR.value : null
      const prot = protR.status === 'fulfilled' ? protR.value : null
      const plugsRes = plugsR.status === 'fulfilled' ? plugsR.value : null
      setData(snap)
      setProtectedPaths(prot?.items || [])
      setActive(snap?.current?.id || null)
      setPlugs(plugsRes?.plugs || [])
      setPlugsUnsupported(!!plugsRes?.not_supported)
      // 默认选中基底：已安装的主基底优先；否则第一个已安装；都没有则第一个。
      // 未安装时主基底不特殊（与其它基底一致：未装 / 灯不亮 / 提供下载）
      const bases = snap?.bases || []
      const primary = snap?.primary_base
      const target = bases.find((b) => b.key === primary && b.installed)
        || bases.find((b) => b.installed)
        || bases[0]
      setSelBase((prev) => prev || (target ? target.key : null))
    } catch (e) {
      setMsg({ type: 'error', text: `加载失败: ${e.message}` })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const togglePlugin = async (key, enabled) => {
    const r = await backendApi.pluginSetEnabled(key, enabled)
    if (r.ok) {
      setPlugMsg({ type: 'ok', text: `已${enabled ? '启用' : '禁用'}插件 ${key}` })
      const res = await backendApi.pluginsList()
      setPlugs(res?.plugs || [])
    } else {
      setPlugMsg({ type: 'error', text: r.msg || '操作失败' })
    }
  }
  const openPluginsDir = async () => {
    const res = await backendApi.pluginsList()
    if (res?.extensions_dir && window.ftn?.openPath) await window.ftn.openPath(res.extensions_dir)
  }

  // 一键更新全部插件（后台任务 + 轮询）
  const [plugTask, setPlugTask] = useState(null)
  const pollPlugTask = (taskId) => {
    setTimeout(async () => {
      try {
        const t = await backendApi.pluginTaskStatus(taskId)
        if (t?.ok) {
          setPlugTask({ taskId, status: t.status, progress: t.progress || 0, log: t.log || [] })
          if (t.status === 'running') pollPlugTask(taskId)
          else setPlugMsg({ type: 'ok', text: (t.log || []).slice(-1)[0] || '插件更新完成' })
        }
      } catch { /* 忽略 */ }
    }, 1500)
  }
  const updateAllPlugins = async () => {
    try {
      const r = await backendApi.pluginUpdateAll()
      if (r?.task_id) {
        setPlugTask({ taskId: r.task_id, status: 'running', progress: 0, log: ['正在更新...'] })
        pollPlugTask(r.task_id)
      }
    } catch (e) { setPlugMsg({ type: 'error', text: `启动失败: ${e.message}` }) }
  }

  const switchVersion = async (id) => {
    // 切换前预览：venv 策略 + 配置文件迁移差异（二次确认）
    try {
      const preview = await backendApi.versionsPreviewSwitch(id)
      if (preview?.ok) {
        const venvMap = { reuse: '复用共享环境', rebuild: '重建/创建共享环境', unknown: '环境策略未知' }
        const venvTxt = venvMap[preview.venv?.strategy] || preview.venv?.strategy || '未知'
        const changed = (preview.configs || []).filter((c) => c.changed).map((c) => c.name)
        const diffTxt = changed.length
          ? `配置文件有差异：${changed.join('、')}（切换不会覆盖，可后续手动迁移）`
          : '配置文件无差异'
        const curTxt = preview.current ? `当前使用中：${preview.current.version}` : '当前：无使用中的版本'
        if (!window.confirm(
          `切换到版本 ${preview.version}？\n\n${curTxt}\n环境：${venvTxt}（${preview.venv?.reason || ''}）\n${diffTxt}\n\n确定切换？`
        )) return
      }
    } catch { /* 预览失败不阻塞，直接切换 */ }
    const r = await backendApi.versionsSetActive(id)
    if (r.ok) {
      setActive(id)
      setMsg({ type: 'ok', text: `已切换至 ${id}` })
    } else {
      setMsg({ type: 'error', text: r.msg || '切换失败' })
    }
    load()
  }

  // 版本下载：真实 git clone 到 Core/Engines/<base>/（后台任务 + 轮询进度）
  const doDownload = async (base, version) => {
    const verTxt = version ? ` ${version}` : ''
    const hasMainEngine = (data?.bases || []).some((b) => b.installed)
    const roleTxt = hasMainEngine
      ? '将 git clone 官方仓库到引擎目录，成为独立的「非主引擎」实例（与主引擎互不覆盖）。'
      : '当前主引擎为空，下载后将自动设置为主引擎。'
    // 可选：选择安装位置（父目录）；取消则用默认引擎目录
    let writeTo
    if (window.ftn?.selectDirectory) {
      const res = await window.ftn.selectDirectory()
      if (res && !res.canceled && res.path) writeTo = res.path
    }
    const destName = `${base.label}-${version}`
    const destTxt = writeTo ? `${writeTo}\\${destName}` : '默认引擎目录（Core/Engines）'
    if (!window.confirm(
      `即将真实下载 ${base.label}${verTxt}。\n\n${roleTxt}\n\n安装位置：${destTxt}\n\n下载体量较大，请保持网络通畅。确定开始吗？`
    )) return
    try {
      const r = await backendApi.versionsDownload(base.key, version, writeTo ? `${writeTo}\\${destName}` : undefined)
      if (!r.ok) { setMsg({ type: 'error', text: r.msg || '下载启动失败' }); return }
      setMsg({ type: 'ok', text: `已启动下载（后台 git clone）到 ${r.dest || destTxt}。` })
      setDlTask({ taskId: r.task_id, label: base.label, version, status: 'running', progress: 0, log: [], error: null })
    } catch (e) {
      setMsg({ type: 'error', text: `下载启动失败: ${e.message}` })
    }
  }

  // 更新到指定版本（target 为空 = 最新）
  const doUpdate = async (id, target) => {
    if (!window.confirm(`将对该版本实例执行 git 更新${target ? `到 ${target}` : '到最新版本'}（真实更新引擎代码）。确定继续？`)) return
    try {
      const r = await backendApi.versionsUpdate(id, target)
      if (!r.ok) { setMsg({ type: 'error', text: r.msg || '更新启动失败' }); return }
      setMsg({ type: 'ok', text: `已启动更新（目标 ${r.target || ''}）。` })
      setOpTask({ taskId: r.task_id, type: 'update', status: 'running', progress: 0, log: [], error: null })
    } catch (e) { setMsg({ type: 'error', text: `更新启动失败: ${e.message}` }) }
  }

  // 回退到指定旧版本
  const doRollback = async (id, target) => {
    if (!target) return
    try {
      const r = await backendApi.versionsRollback(id, target)
      if (!r.ok) { setMsg({ type: 'error', text: r.msg || '回退启动失败' }); return }
      setMsg({ type: 'ok', text: `已启动回退（目标 ${target}）。` })
      setOpTask({ taskId: r.task_id, type: 'rollback', status: 'running', progress: 0, log: [], error: null })
    } catch (e) { setMsg({ type: 'error', text: `回退启动失败: ${e.message}` }) }
  }

  // 环境检查：先查 venv / PyTorch / skimage / numpy 对齐；有问题才询问修复
  const doEnvCheck = async (id) => {
    try {
      const r = await backendApi.versionsEnvCheck(id)
      const items = r?.items || []
      const bad = items.filter((i) => !i.ok)
      if (bad.length === 0) {
        window.alert('环境检查通过：\n' + items.map((i) => `✓ ${i.name}：${i.msg}`).join('\n'))
        return
      }
      const lines = bad.map((i) => `✗ ${i.name}：${i.msg}`)
      if (window.confirm(
        `环境检查发现 ${bad.length} 个问题：\n\n${lines.join('\n')}\n\n` +
        '是否立即执行「修复环境」？将安装/修复依赖（走国内镜像，需要联网且可能较久），进度见上方任务区。'
      )) {
        const t = await backendApi.versionsEnvInstall(id)
        if (!t?.task_id) { setMsg({ type: 'error', text: t?.msg || '修复任务启动失败' }); return }
        setMsg({ type: 'ok', text: '已启动环境修复，进度见上方任务区。' })
        setOpTask({ taskId: t.task_id, type: 'env', status: 'running', progress: 0, log: [], error: null })
      }
    } catch (e) { setMsg({ type: 'error', text: `启动失败: ${e.message}` }) }
  }

  // 接管外部 ZIP（后台任务，失败自动回滚）
  const runManagedTask = async (id) => {
    try {
      const r = await backendApi.versionsTakeover(id)
      if (!r?.task_id) { setMsg({ type: 'error', text: r?.msg || '任务启动失败' }); return }
      setOpTask({ taskId: r.task_id, type: 'takeover', status: 'running', progress: 0, log: [], error: null })
    } catch (e) { setMsg({ type: 'error', text: `启动失败: ${e.message}` }) }
  }
  const takeoverExternal = (id) => {
    if (!window.confirm(
      '接管外部 ZIP：将备份你的模型/输出/配置，再安装该引擎最新版本（保持同一目录），' +
      '此后由 Atelier 管理更新。确定继续？'
    )) return
    runManagedTask(id)
  }

  // Atelier Managed 选择式更新/回退（先看候选，用户选定目标后再执行）
  const doManagedUpdate = async (id, target) => {
    const shown = target && target !== 'latest' ? `（${target}）` : '（最新）'
    if (!window.confirm(`将下载${shown}并替换程序文件（保留模型/输出/配置），失败自动回滚旧版本。确定继续？`)) return
    try {
      const r = await backendApi.versionsManagedUpdate(id, target)
      if (!r?.task_id) { setMsg({ type: 'error', text: r?.msg || '更新启动失败' }); return }
      setMsg({ type: 'ok', text: `已启动更新${shown}。` })
      setOpTask({ taskId: r.task_id, type: 'managed-update', status: 'running', progress: 0, log: [], error: null })
    } catch (e) { setMsg({ type: 'error', text: `更新启动失败: ${e.message}` }) }
  }

  // 外部 ZIP 手动绑定版本身份（无 .git 不猜版本；用户知道来源 commit/tag 才绑）
  const bindExternal = async (id) => {
    const v = curBase.versions.find((x) => x.id === id)
    const cur = (v && (v.git_commit || v.git_tag)) || ''
    const input = window.prompt(
      '外部 ZIP 没有 .git，无法自动识别版本。\n\n如果你知道这个 ZIP 的来源 commit（推荐）或 tag，可手动绑定，仅作展示：\n例如：8f31abc 或 v1.7.0d\n\n不确定就留空取消，不猜版本。',
      cur
    )
    if (input === null) return
    const val = input.trim()
    if (!val) return
    const looksTag = /^v?\d+(\.\d+)*[A-Za-z]*$/.test(val)
    try {
      const r = await backendApi.versionsBind(id, looksTag ? { tag: val } : { commit: val })
      if (r?.ok) setMsg({ type: 'ok', text: r.msg || '已绑定版本身份' })
      else setMsg({ type: 'error', text: r?.msg || '绑定失败' })
    } catch (e) { setMsg({ type: 'error', text: `绑定失败: ${e.message}` }) }
    load()
  }

  // 版本选择弹窗：更新（新版候选） / 回退（历史版本）由用户自己挑
  const [verPick, setVerPick] = useState(null)   // {type:'update'|'rollback', id, items:[{label,value}], loading, managed}
  const openUpdatePick = async (id) => {
    const cur = curBase.versions.find((v) => v.active)
    const v = curBase.versions.find((x) => x.id === id)
    const isManaged = v?.install_source === 'atelier_managed'
    const isGit = v?.install_source === 'git'
    const curTxt = cur ? fmtVer(cur) : ''
    setVerPick({ type: 'update', id, items: [], loading: true, current: curTxt, managed: isManaged })
    // 接管引擎（Atelier 管理）：先查远端最新 commit + tags，列出候选供选择
    if (isManaged) {
      try {
        const r = await backendApi.versionsManagedCandidates(id)
        const items = (r?.update || []).map((u) => ({ label: u.label, value: u.target }))
        setVerPick({ type: 'update', id, items, loading: false, current: curTxt, managed: true })
      } catch {
        setVerPick({ type: 'update', id, items: [], loading: false, current: curTxt, managed: true })
      }
      return
    }
    // clone 版（git）：更新 = 所属分支远端最新 commit（滚动更新）
    if (isGit) {
      try {
        const r = await backendApi.versionsGitCandidates(id)
        const items = (r?.update || []).map((u) => ({ label: u.label, value: u.target }))
        setVerPick({ type: 'update', id, items, loading: false, current: curTxt, managed: false })
      } catch {
        setVerPick({ type: 'update', id, items: [], loading: false, current: curTxt, managed: false })
      }
      return
    }
    try {
      const r = await backendApi.basesDownloadCandidates(curBase.key)
      const cands = (r?.versions || [])
        .filter((v) => v && verGt(v, cur?.version || ''))
        .map((v) => ({ label: v, value: v }))
      setVerPick({ type: 'update', id, items: cands, loading: false, current: curTxt, managed: false })
    } catch {
      setVerPick({ type: 'update', id, items: [], loading: false, current: curTxt, managed: false })
    }
  }
  const openRollbackPick = (id) => {
    const cur = curBase.versions.find((v) => v.active)
    const v = curBase.versions.find((x) => x.id === id)
    const curTxt = cur ? fmtVer(cur) : ''
    const isManaged = v?.install_source === 'atelier_managed'
    const isGit = v?.install_source === 'git'
    if (isManaged) {
      setVerPick({ type: 'rollback', id, items: [], loading: true, current: curTxt, managed: true })
      backendApi.versionsManagedCandidates(id)
        .then((r) => {
          const items = (r?.rollback || []).map((u) => ({ label: u.label, value: u.target }))
          setVerPick({ type: 'rollback', id, items, loading: false, current: curTxt, managed: true })
        })
        .catch(() => setVerPick({ type: 'rollback', id, items: [], loading: false, current: curTxt, managed: true }))
      return
    }
    if (isGit) {
      // clone 版：回退 = 仓库正式 tag（如 v1.7.0d）+ previous（如 Forge）
      setVerPick({ type: 'rollback', id, items: [], loading: true, current: curTxt, managed: false })
      backendApi.versionsGitCandidates(id)
        .then((r) => {
          const items = (r?.rollback || []).map((u) => ({ label: u.label, value: u.target }))
          setVerPick({ type: 'rollback', id, items, loading: false, current: curTxt, managed: false })
        })
        .catch(() => setVerPick({ type: 'rollback', id, items: [], loading: false, current: curTxt, managed: false }))
      return
    }
    const older = curBase.versions
      .filter((v) => !v.active && verGt(cur?.version || '', v.version))
      .map((v) => ({ label: v.version, value: v.version }))
    setVerPick({ type: 'rollback', id, items: older, loading: false, current: curTxt, managed: false })
  }

  // 轮询下载任务进度
  useEffect(() => {
    if (!dlTask || dlTask.status === 'done' || dlTask.status === 'error') return
    const poll = async () => {
      try {
        const s = await backendApi.versionsDownloadStatus(dlTask.taskId)
        if (s && s.ok) {
          setDlTask((prev) => ({ ...prev, status: s.status, progress: s.progress ?? 0, log: s.log || [], error: s.error }))
          if (s.status === 'done' || s.status === 'error') load()
        }
      } catch (_) {}
    }
    poll()
    const t = setInterval(poll, 1200)
    return () => clearInterval(t)
  }, [dlTask])

  // 轮询更新/回退任务进度
  useEffect(() => {
    if (!opTask || opTask.status === 'done' || opTask.status === 'error') return
    const poll = async () => {
      try {
        const s = await backendApi.versionsDownloadStatus(opTask.taskId)
        if (s && s.ok) {
          setOpTask((prev) => ({ ...prev, status: s.status, progress: s.progress ?? 0, log: s.log || [], error: s.error }))
          if (s.status === 'done' || s.status === 'error') load()
        }
      } catch (_) {}
    }
    poll()
    const t = setInterval(poll, 1200)
    return () => clearInterval(t)
  }, [opTask])

  if (loading || !data) return <div className="p-8 text-txt-muted">加载中...</div>

  const bases = data.bases || []
  const primaryBase = data.primary_base
  const curBase = bases.find((b) => b.key === selBase) || bases[0] || null
  // 是否有可用主引擎：任一基底已安装即视为已有引擎可用，新下载归类非主引擎
  const hasMainEngine = bases.some((b) => b.installed)

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold">版本管理</h1>
          <p className="text-sm text-txt-muted mt-1">多基底隔离 · 更新保护 · 一键下载 / 切换 / 回退</p>
        </div>
        <div className="flex items-center gap-2 text-sm text-txt-muted">
          <IconEngine style={{ fontSize: 18 }} />
          <span>{data.engines_root}</span>
        </div>
      </div>

      {msg && (
        <div className={`mb-4 px-4 py-2.5 rounded-lg text-sm whitespace-pre-line ${msg.type === 'ok' ? 'bg-accent-soft text-accent' : 'bg-red-500/10 text-red-400'}`}>
          {msg.text}
        </div>
      )}

      {/* 子分区小菜单：基底版本 / 插件管理 / 插件市场 */}
      <div className="flex gap-1 mb-4 border-b border-base-border pb-3">
        <SubTabBtn active={subTab === 'base'} onClick={() => setSubTab('base')}>基底版本</SubTabBtn>
        <SubTabBtn active={subTab === 'manage'} onClick={() => setSubTab('manage')}>插件管理</SubTabBtn>
        <SubTabBtn active={subTab === 'market'} onClick={() => setSubTab('market')}>插件市场</SubTabBtn>
      </div>

      {/* 当前主引擎版本（对比新旧用） */}
      {data?.current && (
        <div className="mb-4 rounded-xl border border-accent/40 bg-accent-soft/30 px-4 py-3 flex items-center gap-3">
          <span className="text-lg">⚙️</span>
          <div className="flex-1 text-sm min-w-0">
            <span className="font-medium">当前主引擎：{data.primary_label}</span>
            <span className="ml-2 text-accent font-semibold">{fmtVer(data.current)}</span>
          </div>
          <span className="text-[11px] text-txt-muted shrink-0">用于比对新旧版本</span>
        </div>
      )}

      {subTab === 'base' && (
        <>
          {/* 后台任务进度（下载 / 更新 / 回退） */}
          {(dlTask || opTask) && (() => {
            const t = opTask || dlTask
            const opTitles = { update: '更新版本', rollback: '回退版本', takeover: '接管安装', 'managed-update': '在线更新' }
            const title = dlTask
              ? `下载 ${dlTask.label || ''} ${dlTask.version || ''}`
              : (opTitles[opTask.type] || opTask.type)
            const statusTxt = t.status === 'done' ? '完成' : t.status === 'error' ? '失败' : '进行中'
            return (
              <div className={`mb-4 rounded-xl border p-4 ${t.status === 'error' ? 'border-red-500/40 bg-red-500/5' : 'border-base-border bg-base-surface'}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium">{title}</span>
                  <span className={`text-xs ${t.status === 'error' ? 'text-red-400' : t.status === 'done' ? 'text-emerald-400' : 'text-accent'}`}>{statusTxt} · {Math.round(t.progress || 0)}%</span>
                </div>
                <div className="h-2 rounded-full bg-base-surface-2 overflow-hidden">
                  <div className="h-full transition-all rounded-full" style={{ width: `${t.progress || 0}%`, background: 'var(--color-accent)' }} />
                </div>
                {(t.log && t.log.length > 0) && (
                  <pre className="mt-2 max-h-28 overflow-auto text-[11px] text-txt-muted leading-relaxed whitespace-pre-wrap">
                    {t.log.join('\n')}
                  </pre>
                )}
                {t.error && <p className="mt-2 text-xs text-red-400">{t.error}</p>}
              </div>
            )
          })()}

          {/* 基底切换小菜单（每个基底一个） */}
          <div className="flex flex-wrap items-center gap-2 mb-4">
            {bases.map((b) => {
              const on = b.key === primaryBase
              return (
                <button key={b.key}
                  onClick={() => setSelBase(b.key)}
                  title={b.desc}
                  className="px-3 py-1.5 rounded-lg border text-sm flex items-center gap-1.5 transition-colors"
                  style={{
                    borderColor: curBase?.key === b.key ? 'var(--color-accent)' : 'var(--color-border)',
                    background: curBase?.key === b.key ? 'var(--color-accent-soft)' : 'transparent',
                  }}>
                  <span className="w-1.5 h-1.5 rounded-full"
                    style={{ background: b.installed ? 'var(--color-accent)' : 'var(--color-border)' }} />
                  {b.label}
                  {on && b.installed && <span className="text-[9px] px-1 py-0.5 rounded bg-accent text-white">主</span>}
                  {!b.installed && <span className="text-[9px] px-1 py-0.5 rounded bg-base-surface-2 text-txt-muted">未装</span>}
                </button>
              )
            })}
          </div>

          {/* 注：主基底由设置页的主引擎决定，此处不做选择；版本页仅浏览。 */}

          {/* 当前基底版本列表（新旧排序，当前版本在中间位置） */}
          <section className="rounded-xl border border-base-border bg-base-surface overflow-hidden">
            <div className="px-5 py-3.5 border-b border-base-border flex justify-between items-center">
              <h2 className="font-semibold text-txt-secondary">
                {curBase?.label}
                <span className="ml-2 text-xs text-txt-muted">版本实例（新→旧排序，当前版本于中间位置）</span>
              </h2>
              <span className="text-xs text-txt-muted">{curBase?.version_count ?? 0} 个实例</span>
            </div>

            {(() => {
              const isPrimaryBase = curBase.key === primaryBase
              const rows = curBase.versions || []
              if (!rows.length) {
                // 空基底 → 提供「多版本下载」，文案随是否有主引擎自适应
                return <CandidatesDownload base={curBase} hasMainEngine={hasMainEngine} onDownload={(v) => doDownload(curBase, v)} />
              }
              if (!isPrimaryBase) {
                // 非主基底：直接展示其版本（不再额外说明，防止干扰）
                return (
                  <div className="divide-y divide-base-border">
                    {rows.map((v) => (
                      <VersionRow key={v.id} v={v} isActive={v.active}
                        onSwitch={switchVersion}
                        onUpdatePick={openUpdatePick} onRollbackPick={openRollbackPick}
                        onTakeover={takeoverExternal} onBind={bindExternal} onEnvCheck={doEnvCheck}
                        busy={!!opTask}
                        mode="other" primaryLabel={data.primary_label} />
                    ))}
                  </div>
                )
              }
              // 主基底：使用中 / 更新 / 回退
              return (
                <div className="divide-y divide-base-border">
                  {(() => {
                    const activeIdx = rows.findIndex((v) => v.active)
                    return rows.map((v, i) => {
                      const rel = activeIdx >= 0 ? (i < activeIdx ? 'newer' : i === activeIdx ? 'active' : 'older') : 'other'
                      return (
                        <VersionRow key={v.id} v={v} isActive={v.active}
                          onSwitch={switchVersion} onUpdatePick={openUpdatePick} onRollbackPick={openRollbackPick}
                          onTakeover={takeoverExternal} onBind={bindExternal} onEnvCheck={doEnvCheck}
                          busy={!!opTask} mode="primary" rel={rel} activeIdx={activeIdx} />
                      )
                    })
                  })()}
                </div>
              )
            })()}
          </section>
        </>
      )}

      {subTab === 'manage' && (
        <PluginManage plugs={plugs} unsupported={plugsUnsupported} plugMsg={plugMsg} onToggle={togglePlugin} onOpenDir={openPluginsDir}
          onUpdateAll={updateAllPlugins} task={plugTask} />
      )}

      {subTab === 'market' && <PluginMarket />}

      {/* 版本选择弹窗（更新新版候选 / 回退历史版本） */}
      {verPick && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6" onClick={() => setVerPick(null)}>
          <div className="w-full max-w-md rounded-2xl border border-base-border bg-base-surface shadow-2xl flex flex-col max-h-[80vh]" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-base-border">
              <div>
                <h2 className="text-base font-bold">{verPick.type === 'update' ? '选择要更新的新版本' : '选择要回退的历史版本'}</h2>
                <p className="text-[11px] text-txt-muted mt-0.5">当前版本：{verPick.current || '—'}</p>
              </div>
              <button onClick={() => setVerPick(null)} className="w-8 h-8 rounded-lg border border-base-border text-txt-muted hover:bg-base-surface-2 shrink-0">✕</button>
            </div>
            <div className="p-4 overflow-y-auto flex-1 space-y-1.5">
              {verPick.loading ? (
                <p className="text-sm text-txt-muted py-8 text-center">加载候选版本…</p>
              ) : verPick.items.length === 0 ? (
                <div className="text-center py-8">
                  <p className="text-sm text-txt-muted">
                    {verPick.type === 'update'
                      ? (verPick.managed
                        ? '当前已是最新（未发现更新的候选版本），无需重复更新。'
                        : '当前已是最新版本（未发现更新的候选版本）。')
                      : '没有可回退的历史版本。'}
                  </p>
                  {verPick.type === 'update' && !verPick.managed && (
                    <button onClick={() => { doUpdate(verPick.id); setVerPick(null) }}
                      className="mt-3 px-4 py-2 rounded-lg border border-emerald-500/40 text-emerald-500 text-sm hover:bg-emerald-500/10">
                      仍要更新到最新
                    </button>
                  )}
                </div>
              ) : (
                verPick.items.map((item) => (
                  <button key={item.value}
                    onClick={() => {
                      if (verPick.type === 'update') {
                        if (verPick.managed) doManagedUpdate(verPick.id, item.value)
                        else doUpdate(verPick.id, item.value)
                      } else {
                        if (verPick.managed) doManagedUpdate(verPick.id, item.value)
                        else doRollback(verPick.id, item.value)
                      }
                      setVerPick(null)
                    }}
                    className="w-full px-3 py-2.5 rounded-lg border border-base-border hover:border-accent/50 text-left transition-colors">
                    <span className="font-mono text-sm text-txt-primary">{item.label}</span>
                    <span className="ml-2 text-xs text-txt-muted">{verPick.type === 'update' ? '更新到此版本' : '回退到此版本'}</span>
                  </button>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* 更新保护 */}
      <section className="mt-6 rounded-xl border border-base-border bg-base-surface p-5">
        <div className="flex items-center gap-2 mb-3">
          <IconSettings style={{ fontSize: 18 }} className="text-txt-muted" />
          <h2 className="font-semibold text-txt-secondary">更新保护</h2>
        </div>
        <p className="text-sm text-txt-muted mb-3">以下路径在更新时永不覆盖（非侵入原则）：</p>
        <div className="flex flex-wrap gap-2">
          {protectedPaths.map((p) => (
            <span key={p} className="px-2.5 py-1 rounded-md bg-base-surface-2 border border-base-border text-xs font-mono text-txt-secondary">
              {p}
            </span>
          ))}
        </div>
      </section>
    </div>
  )
}

function SubTabBtn({ active, onClick, children }) {
  return (
    <button onClick={onClick}
      className={`px-4 py-1.5 rounded-lg text-sm ${active ? 'bg-accent-soft text-accent font-medium' : 'text-txt-muted hover:text-txt-primary'}`}>
      {children}
    </button>
  )
}

// 版本号数值化比较（"v1.10.1" → [1,10,1]）
function verNum(s) {
  return String(s || '').replace(/^v/i, '').split(/[.\-]/).map((x) => parseInt(x, 10) || 0)
}
function verGt(a, b) {
  const A = verNum(a), B = verNum(b)
  for (let i = 0; i < Math.max(A.length, B.length); i++) {
    const x = A[i] || 0, y = B[i] || 0
    if (x > y) return true
    if (x < y) return false
  }
  return false
}

// 版本身份展示：tag（友好名称）→ branch @ commit → 未知
function fmtVer(v) {
  if (!v) return '未知版本'
  const date = v.date ? `${v.date} · ` : ''
  if (v.git_tag) return date + v.git_tag
  if (v.git_commit) {
    const short = String(v.git_commit).slice(0, 7)
    const branch = v.git_branch || v.branch
    return date + (branch ? `${branch} @ ${short}` : `Commit ${short}`)
  }
  return v.version || '未知版本'
}

const SRC_LABEL = { atelier_managed: 'Atelier 管理', git: 'Git', external: '外部 ZIP' }

// 未安装基底的候选版本下载列表（多版本；文案随是否有主引擎自适应）
function CandidatesDownload({ base, hasMainEngine, onDownload }) {
  const [cands, setCands] = useState(null)
  useEffect(() => {
    setCands(null)
    backendApi.basesDownloadCandidates(base.key)
      .then((r) => setCands(r))
      .catch(() => setCands(null))
  }, [base.key])

  if (cands === null) return <p className="text-sm text-txt-muted px-5 py-4">加载可下载版本...</p>
  const vers = cands.versions || []
  const CAND_LABEL = { main: 'main（最新）', previous: 'previous（上一版）' }
  return (
    <div className="px-5 py-6">
      <div className="mb-4 text-center">
        <p className="text-sm text-txt-muted">
          「{base.label}」当前未安装。请选择一个版本下载。
          {hasMainEngine
            ? '下载后将自动归类为「非主引擎」，作为独立引擎使用（与主引擎互不覆盖）。'
            : '当前主引擎为空，下载后自动设置为主引擎。'}
        </p>
      </div>
      {vers.length === 0 ? (
        <div className="text-center py-4">
          <p className="text-sm text-txt-muted mb-1">暂无预置版本清单。</p>
          <p className="text-xs text-txt-muted">请稍后重试，或在该基底配置官方候选版本后即可一键真实下载。</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
          {vers.map((v) => (
            <button key={v} onClick={() => onDownload(v)}
              className="rounded-xl border border-base-border bg-base-bg/40 p-4 text-left hover:border-accent/50 transition-all group">
              <div className="text-sm font-medium text-txt-primary flex items-center gap-2">
                {base.label}
                <span className="px-1.5 py-0.5 rounded bg-accent-soft text-accent text-xs font-mono">{CAND_LABEL[v] || v}</span>
              </div>
              <div className="text-[11px] text-txt-muted mt-2">{hasMainEngine ? '下载后归类为非主引擎 · 独立版本' : '下载后将成为主引擎'}</div>
              <div className="mt-3 text-accent text-xs font-medium opacity-70 group-hover:opacity-100">⬇ 下载此版本</div>
            </button>
          ))}
        </div>
      )}
      <p className="text-xs text-txt-muted mt-4 text-center">下载前可选择目标路径，若取消则为默认路径，并建议使用纯英文路径。</p>
    </div>
  )
}

// 单个版本行
// 非 active 行：切换使用版本（真实切换 active，多实例共存）。
// active 行：显示「使用中」，并提供真实的 git「更新到最新」/「回退」操作。
function VersionRow({ v, isActive, onSwitch, onUpdatePick, onRollbackPick, onTakeover, onBind, onEnvCheck, busy = false, mode = 'primary', rel, activeIdx }) {
  const isRelevantNewer = rel === 'newer'
  const isRelevantOlder = rel === 'older'
  const isExternal = v.install_source === 'external'
  const isManaged = v.install_source === 'atelier_managed'
  return (
    <div className="flex items-center gap-4 px-5 py-4" style={{ background: isActive ? 'var(--color-accent-soft)' : undefined }}>
      <div className="w-8 flex justify-center">
        {isActive
          ? <span className="px-1.5 py-0.5 rounded text-white text-[10px] font-bold" style={{ background: 'var(--color-accent)' }}>当前</span>
          : <span className="w-3 h-3 rounded-full border border-base-border" />}
      </div>
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <span className="font-semibold">{v.name}</span>
          <span className="px-1.5 py-0.5 rounded bg-base-surface-2 text-xs text-txt-secondary font-mono">{fmtVer(v)}</span>
          {v.install_source && (
            <span className="px-1.5 py-0.5 rounded bg-base-surface-2 text-[10px] text-txt-muted"
              title={isExternal ? '用户自带的 ZIP/目录，无 git、无安装记录' : (isManaged ? '由 FTN Atelier 安装并记录 commit' : 'Git 仓库安装')}>
              {SRC_LABEL[v.install_source] || v.install_source}
            </span>
          )}
          {mode === 'primary' && !isActive && isRelevantNewer && <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 text-[10px]">更新版本</span>}
          {mode === 'primary' && !isActive && isRelevantOlder && <span className="px-1.5 py-0.5 rounded bg-base-surface-2 text-[10px] text-txt-muted">历史版本</span>}
          {isActive && mode === 'primary' && !isExternal && (
            <span className="px-1.5 py-0.5 rounded bg-base-surface-2 text-[10px] text-txt-muted">正在使用的引擎</span>
          )}
        </div>
        <div className="text-xs text-txt-muted mt-0.5 font-mono">{v.path}</div>
      </div>
      <div className="text-sm text-txt-muted shrink-0">{v.size > 0 ? fmtSize(v.size) : ''}</div>
      {isActive ? (
        <div className="shrink-0 flex items-center gap-2">
          {isExternal ? (
            <>
              <button
                onClick={() => onBind && onBind(v.id)}
                disabled={busy}
                className="px-3 py-2 rounded-lg border text-sm font-medium border-base-border hover:bg-base-surface-2 disabled:opacity-40"
                title="外部 ZIP 没有 .git，无法自动识别版本；可手动绑定来源 commit/tag（仅作展示）"
              >{v.user_bound ? '重新绑定版本' : '绑定版本'}</button>
              <button
                onClick={() => onTakeover(v.id)}
                disabled={busy}
                className="px-3 py-2 rounded-lg border text-sm font-medium border-accent/40 text-accent hover:bg-accent-soft disabled:opacity-40"
                title="备份用户数据 → 安装最新版 → 由 Atelier 管理更新"
              >接管为 Atelier 管理</button>
              <button
                onClick={() => onEnvCheck && onEnvCheck(v.id)}
                disabled={busy}
                className="px-3 py-2 rounded-lg border text-sm font-medium border-base-border hover:bg-base-surface-2 disabled:opacity-40"
                title="检查虚拟环境、PyTorch、依赖与 numpy 对齐；发现问题可一键修复"
              >检查环境</button>
            </>
          ) : (
            <>
              <button
                onClick={() => onUpdatePick(v.id)}
                disabled={busy}
                className="px-3 py-2 rounded-lg border text-sm font-medium border-emerald-500/40 text-emerald-500 hover:bg-emerald-500/10 disabled:opacity-40"
              >↑ 选择新版</button>
              <button
                onClick={() => onRollbackPick(v.id)}
                disabled={busy}
                className="px-3 py-2 rounded-lg border text-sm font-medium border-base-border hover:bg-base-surface-2 disabled:opacity-40"
              >↶ 选择回退</button>
              <button
                onClick={() => onEnvCheck && onEnvCheck(v.id)}
                disabled={busy}
                className="px-3 py-2 rounded-lg border text-sm font-medium border-base-border hover:bg-base-surface-2 disabled:opacity-40"
                title="检查虚拟环境、PyTorch、依赖与 numpy 对齐；发现问题可一键修复"
              >检查环境</button>
            </>
          )}
        </div>
      ) : (
        <div className="shrink-0 flex items-center gap-2">
          <button
            onClick={() => onSwitch(v.id)}
            className="px-4 py-2 rounded-lg border text-sm font-medium border-accent/40 text-accent hover:bg-accent-soft"
          >切换至此</button>
          {isExternal && (
            <>
              <button
                onClick={() => onBind && onBind(v.id)}
                disabled={busy}
                className="px-3 py-2 rounded-lg border text-sm font-medium border-base-border hover:bg-base-surface-2 disabled:opacity-40"
              >{v.user_bound ? '重新绑定版本' : '绑定版本'}</button>
              <button
                onClick={() => onTakeover(v.id)}
                disabled={busy}
                className="px-3 py-2 rounded-lg border text-sm font-medium border-accent/40 text-accent hover:bg-accent-soft disabled:opacity-40"
              >接管为 Atelier 管理</button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// 插件管理：管理（浏览 / 开关）当前主引擎已安装的插件
function PluginManage({ plugs, unsupported, plugMsg, onToggle, onOpenDir, onUpdateAll, task }) {
  // plugs: 来自 pluginsList()，为 null = 加载中；[] = 无插件
  const loading = plugs === null
  return (
    <section className="rounded-xl border border-base-border bg-base-surface p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="font-semibold text-txt-secondary">插件管理</h2>
          <p className="text-xs text-txt-muted mt-0.5">浏览并开关当前主引擎已安装的插件（来自主引擎 extensions 目录）</p>
        </div>
        <div className="flex gap-2">
          <button onClick={onUpdateAll} disabled={task?.status === 'running'}
            className="px-3 py-1.5 rounded-lg border border-base-border text-sm hover:bg-base-surface-2 disabled:opacity-40"
            title="拉取所有已装插件的仓库最新代码">
            {task?.status === 'running' ? `更新中 ${task.progress || 0}%…` : '全部更新'}
          </button>
          <button onClick={onOpenDir} className="px-3 py-1.5 rounded-lg border border-base-border text-sm hover:bg-base-surface-2">打开插件目录</button>
        </div>
      </div>

      {task?.status === 'running' && (
        <div className="mb-3">
          <div className="h-1 rounded-full bg-base-surface-2 overflow-hidden">
            <div className="h-full bg-accent transition-all duration-500" style={{ width: `${task.progress || 0}%` }} />
          </div>
          <p className="text-[11px] text-txt-muted mt-1 truncate">{task.log?.slice(-1)[0] || '更新中…'}</p>
        </div>
      )}

      {plugMsg && (
        <div className={`mb-3 px-3 py-2 rounded-lg text-sm ${plugMsg.type === 'ok' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
          {plugMsg.text}
        </div>
      )}

      {unsupported ? (
        <p className="text-sm text-txt-muted py-6 text-center">当前主引擎类型不受支持（仅支持启动/停止/重启），插件管理不适用。</p>
      ) : loading ? (
        <p className="text-sm text-txt-muted">加载中...</p>
      ) : plugs.length === 0 ? (
        <p className="text-sm text-txt-muted py-6 text-center">当前主引擎下暂无插件。可到「插件市场」下载安装。</p>
      ) : (
        <div className="space-y-2">
          {plugs.map((p) => (
            <div key={p.key} className="rounded-lg border border-base-border p-3 flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm truncate">{p.name}</span>
                  {p.has_git && <span className="px-1.5 py-0.5 rounded bg-base-surface-2 text-[10px] text-txt-muted">git</span>}
                  {p.dup && <span className="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 text-[10px]" title="检测到相同来源仓库的重复插件">重复</span>}
                </div>
                <div className="text-[11px] text-txt-muted truncate mt-0.5 font-mono">{p.path}</div>
              </div>
              <button
                onClick={() => onToggle(p.key, !p.enabled)}
                className={`w-9 h-5 rounded-full relative transition-colors shrink-0 ${p.enabled ? 'bg-accent' : 'bg-base-surface-2 border border-base-border'}`}
                title={p.enabled ? '点击禁用' : '点击启用'}
              >
                <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all ${p.enabled ? 'left-4.5' : 'left-0.5'}`} />
              </button>
              <span className={`text-[11px] w-8 text-center shrink-0 ${p.enabled ? 'text-accent' : 'text-txt-muted'}`}>{p.enabled ? '启用' : '禁用'}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

// 插件市场：只展示主引擎通用 / 专属插件，搜索 + 分类筛选，可下载 / 更新 / 卸载 / URL 安装
function PluginMarket() {
  const [market, setMarket] = useState(null)   // {items, groups, primary_label, demo}
  const [q, setQ] = useState('')
  const [group, setGroup] = useState('全部')
  const [opMsg, setOpMsg] = useState(null)
  const [busyKey, setBusyKey] = useState(null)
  const [urlInput, setUrlInput] = useState('')
  const [showUrl, setShowUrl] = useState(false)

  const loadMarket = useCallback(async () => {
    const r = await backendApi.pluginMarket({ query: q, group })
    setMarket(r)
  }, [q, group])
  useEffect(() => { loadMarket() }, [loadMarket])

  const run = async (fn, key, okText) => {
    setBusyKey(key); setOpMsg(null)
    try {
      const r = await fn()
      if (r?.ok) setOpMsg({ type: 'ok', text: r.msg || okText })
      else if (r?.code) setOpMsg({ type: 'ok', text: r.msg })
      else setOpMsg({ type: 'error', text: r?.msg || '操作失败' })
    } catch (e) { setOpMsg({ type: 'error', text: String(e?.message || e) }) }
    finally { setBusyKey(null); loadMarket() }
  }
  const confirmAndUpdate = (item) => {
    if (!window.confirm(`确认更新插件「${item.name}」？将拉取其仓库最新代码。`)) return
    run(() => backendApi.pluginUpdate(item.key), item.key, `已更新 ${item.name}`)
  }
  const confirmUninstall = (item) => {
    if (!window.confirm(`确认卸载插件「${item.name}」？资产目录将移入 .uninstalled 备份。`)) return
    run(() => backendApi.pluginUninstall(item.key), item.key, `已卸载 ${item.name}`)
  }
  const confirmUrl = async () => {
    const url = urlInput.trim()
    if (!url) return
    setShowUrl(false)
    const r = await backendApi.pluginUrlInstall(url)
    if (r && r.ok && (r.code === 'update' || r.code === 'update_unknown' || r.code === 'rollback')) {
      if (!window.confirm(r.msg)) return
      await run(() => backendApi.pluginUpdate(r.key), r.key, '操作完成')
      setUrlInput('')
      return
    }
    setOpMsg({ type: r?.ok ? 'ok' : 'error', text: r?.msg || (r?.code === 'same' ? '已是最新' : '操作完成') })
    setUrlInput(''); loadMarket()
  }

  // 仅列出主引擎「通用」或「专属适配」的插件
  const items = (market?.items || []).filter((p) => p.base === '通用' || p.fits)
  const groups = market?.groups || ['全部']

  return (
    <section className="rounded-xl border border-base-border bg-base-surface p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="font-semibold text-txt-secondary">插件市场</h2>
          <p className="text-xs text-txt-muted mt-0.5">
            仅展示主引擎「{market?.no_engine ? 'reForge / Forge（自动检测）' : (market?.primary_label || '...')}」通用 / 专属插件，安装后直达该引擎 extensions 目录
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setShowUrl((v) => !v)} className="px-3 py-1.5 rounded-lg border border-base-border text-sm hover:bg-base-surface-2">URL 安装</button>
        </div>
      </div>

      {showUrl && (
        <div className="mb-3 p-3 rounded-lg border border-accent/40 bg-accent-soft/20 flex gap-2">
          <input value={urlInput} onChange={(e) => setUrlInput(e.target.value)} autoFocus autoComplete="off"
            placeholder="粘贴 Git 仓库 URL（如 https://github.com/...）" className={`${inputCls} text-sm`}
            onKeyDown={(e) => { if (e.key === 'Enter') confirmUrl() }} />
          <button onClick={confirmUrl} className="px-3 py-2 rounded-lg bg-accent text-white text-sm shrink-0">安装 / 比对</button>
          <button onClick={() => setShowUrl(false)} className="px-3 py-2 rounded-lg border border-base-border text-sm shrink-0">取消</button>
        </div>
      )}

      {/* 搜索 / 分组筛选（元基底筛选） */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索插件名称..." className={`${inputCls} max-w-52 text-sm`} autoComplete="off" />
        <select value={group} onChange={(e) => setGroup(e.target.value)} className="px-2 py-1.5 rounded border border-base-border bg-base-bg text-xs">
          {groups.map((g) => <option key={g} value={g}>{g === '全部' ? '全部分类' : g}</option>)}
        </select>
      </div>

      {opMsg && (
        <div className={`mb-3 px-3 py-2 rounded-lg text-xs ${opMsg.type === 'ok' ? 'bg-accent-soft text-accent' : 'bg-red-500/10 text-red-400'}`}>
          {opMsg.text}
        </div>
      )}

      {market === null ? (
        <p className="text-sm text-txt-muted">加载中...</p>
      ) : market.not_supported ? (
        <p className="text-sm text-txt-muted py-4 text-center">{market.note || '当前主引擎类型不受支持，插件市场不适用。'}</p>
      ) : market.no_engine ? (
        <p className="text-sm text-txt-muted py-4 text-center">当前尚未安装主引擎，请先在「基底版本」页下载或配置主引擎；插件将安装到主引擎 extensions 目录。</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-txt-muted py-4 text-center">无匹配插件</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {items.map((p) => (
            <div key={p.key} className="rounded-lg border border-base-border p-3 flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${p.base === '通用' ? 'bg-base-surface-2 text-txt-muted' : 'bg-accent-soft text-accent'}`}>
                  {p.base === '通用' ? '通用' : `${p.base} 专属`}
                </span>
                <span className="px-1.5 py-0.5 rounded text-[10px] bg-base-surface-2 text-txt-muted">{p.group}</span>
                {p.installed && <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400">已安装</span>}
              </div>
              <div className="text-sm font-medium">{p.name}</div>
              <div className="text-[11px] text-txt-muted line-clamp-2">{p.desc}</div>
              {p.installed && p.local_version && (
                <div className="text-[10px] text-txt-muted font-mono">本地版本：{p.local_version}</div>
              )}
              <div className="flex items-center gap-2 mt-auto">
                {!p.installed ? (
                  <button onClick={() => run(() => backendApi.pluginInstall(p.repo, p.key), p.key, `已下载 ${p.name}`)} disabled={busyKey === p.key}
                    className="flex-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-accent text-white disabled:opacity-40">
                    {busyKey === p.key ? '下载中...' : '⬇ 下载'}
                  </button>
                ) : (
                  <>
                    <button onClick={() => confirmAndUpdate(p)} disabled={busyKey === p.key}
                      className="flex-1 px-3 py-1.5 rounded-lg border text-xs font-medium border-accent/50 text-accent hover:bg-accent-soft disabled:opacity-40">
                      {busyKey === p.key ? '处理中...' : '更新'}
                    </button>
                    <button onClick={() => confirmUninstall(p)} disabled={busyKey === p.key}
                      className="px-3 py-1.5 rounded-lg border text-xs border-red-500/30 text-red-400 hover:bg-red-500/10 disabled:opacity-40">
                      卸载
                    </button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function fmtSize(n) {
  if (n >= 1e9) return (n / 1e9).toFixed(1) + ' GB'
  if (n >= 1e6) return (n / 1e6).toFixed(0) + ' MB'
  return n + ' B'
}

const inputCls = 'flex-1 px-3 py-2 rounded-lg border border-base-border bg-base-bg text-sm focus:outline-none focus:border-accent'
