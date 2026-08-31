/*  */import React, { useEffect, useState, useCallback } from 'react'
import { backendApi } from '../services/apiClient'
import { useApp } from '../state/AppContext'
import SelfCheckModal from './SelfCheckModal'
import { startUpdate } from '../utils/updater'

// ============================================
// M3 设置页面：可视化编辑 AppConfig（四类配置）
// 涵盖：
//   1. 引擎路径（EnginePaths）
//   2. 启动参数（StartArgs）
//   3. 环境配置（EnvConfig）
//   4. 用户偏好（UserPreference）
//   5. 杂项开关
// ============================================

// 区块定义：便于渲染
const SECTIONS = ['engine_paths', 'quickfolders', 'start_args', 'env', 'preference']

export default function Settings({ initialTab = null }) {
  const [config, setConfig] = useState(null)     // 工作副本（可编辑）
  const [original, setOriginal] = useState(null) // 后端原始
  const [tab, setTab] = useState('engine_paths')
  const [msg, setMsg] = useState(null)           // {type, text}
  const [loading, setLoading] = useState(true)
  const { setTheme } = useApp()

  // 加载配置
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const cfg = await backendApi.getConfig()
      setConfig(JSON.parse(JSON.stringify(cfg || {})))
      setOriginal(JSON.parse(JSON.stringify(cfg || {})))
    } catch (e) {
      setMsg({ type: 'error', text: `加载配置失败: ${e.message}` })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // 支持从其它页面直达指定子 Tab（如「网络下载 → 设置 → 网站API」）
  useEffect(() => {
    if (initialTab) setTab(initialTab)
  }, [initialTab])

  // 接收「前往设置 · 网站API」事件（由模型页下载入口触发）
  useEffect(() => {
    const h = (e) => { if (e?.detail === 'api') setTab('api') }
    window.addEventListener('ftn:navigateSettings', h)
    return () => window.removeEventListener('ftn:navigateSettings', h)
  }, [])

  // 通用浅合并更新（value 可传对象/值）：改动即自动保存到后端，免去单独「保存」按钮
  // section='__top__' 时做为 AppConfig 顶层字段（如 venv_share）直接写入
  const update = useCallback((section, key, value) => {
    setConfig((prev) => {
      const next = JSON.parse(JSON.stringify(prev || {}))
      if (section === '__top__') {
        next[key] = value
      } else {
        if (!next[section]) next[section] = {}
        next[section][key] = value
      }
      // 主题偏好实时预览
      if (section === 'preference' && key === 'theme') setTheme(value)
      // 即时保存
      setMsg({ type: 'ok', text: '已保存' })
      backendApi.updateConfig(next)
        .then((updated) => {
          setConfig(JSON.parse(JSON.stringify(updated)))
          setOriginal(JSON.parse(JSON.stringify(updated)))
        })
        .catch((e) => setMsg({ type: 'error', text: `保存失败: ${e.message}` }))
      return next
    })
  }, [setTheme])

  if (loading || !config) {
    return <div className="p-8 text-txt-muted">加载配置中...</div>
  }

  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">设置</h1>
        <p className="text-sm text-txt-muted mt-1">配置引擎路径、启动参数、环境与偏好（修改即自动保存）</p>
      </div>

      {msg && (
        <div className={`mb-4 px-4 py-2.5 rounded-lg text-sm ${msg.type === 'ok' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
          {msg.text}
        </div>
      )}

      {/* 分区 Tab */}
      <div className="flex gap-1 mb-5 border-b border-base-border pb-3 overflow-x-auto">
        <TabBtn active={tab === 'engine_paths'} onClick={() => setTab('engine_paths')}>引擎路径</TabBtn>
        <TabBtn active={tab === 'quickfolders'} onClick={() => setTab('quickfolders')}>快捷文件夹</TabBtn>
        <TabBtn active={tab === 'start_args'} onClick={() => setTab('start_args')}>启动参数</TabBtn>
        <TabBtn active={tab === 'env'} onClick={() => setTab('env')}>环境配置</TabBtn>
        <TabBtn active={tab === 'preference'} onClick={() => setTab('preference')}>用户偏好</TabBtn>
        <TabBtn active={tab === 'api'} onClick={() => setTab('api')}>网站API</TabBtn>
        <TabBtn active={tab === 'selfcheck'} onClick={() => setTab('selfcheck')}>软件修复更新</TabBtn>
        <TabBtn active={tab === 'data'} onClick={() => setTab('data')}>数据管理</TabBtn>
      </div>

      <div className="space-y-4">
        {tab === 'engine_paths' && <EnginePaths config={config} update={update} />}
        {tab === 'quickfolders' && <QuickFolders />}
        {tab === 'start_args' && <StartArgs config={config} update={update} />}
        {tab === 'env' && <EnvConfigForm config={config} update={update} />}
        {tab === 'preference' && (
          <>
            <Preference config={config} update={update} />
            <OutputMaintain />
          </>
        )}
        {tab === 'api' && <WebsiteApis config={config} update={update} />}
        {tab === 'selfcheck' && <SelfCheckSettings config={config} update={update} />}
        {tab === 'data' && <DataManage />}
      </div>
    </div>
  )
}

function TabBtn({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-1.5 rounded-lg text-sm whitespace-nowrap ${active ? 'bg-accent-soft text-accent font-medium' : 'text-txt-muted hover:text-txt-primary'}`}
    >
      {children}
    </button>
  )
}

// ============ 引擎路径（可编辑引擎） ============
const KIND_LABEL = { webui: 'WebUI', batdir: '启动脚本', ftn_tag: 'Tag 库' }
const FAMILY_LABEL = { reforge: 'reForge', forge: 'Forge', a1111: 'A1111', comfyui: 'ComfyUI', unknown: '未知类型', other: '脚本/工具' }
const SUPPORTED_FAMILY = new Set(['reforge', 'forge'])
function EnginePaths() {
  const [engines, setEngines] = useState([])
  const [loading, setLoading] = useState(true)
  const [banner, setBanner] = useState(null)
  const [adding, setAdding] = useState(false)
  const [renameKey, setRenameKey] = useState(null)   // 正在改名的引擎 key
  const [renameVal, setRenameVal] = useState('')     // 改名输入值
  const [editRoot, setEditRoot] = useState(null)     // 手动编辑的 root 路径（key）
  const [editVal, setEditVal] = useState('')         // 手动编辑的 root 输入值
  const [detectingEntry, setDetectingEntry] = useState(null) // 正在重新检测入口的引擎
  const [editEntry, setEditEntry] = useState(null)           // 手动编辑入口文件的引擎 key
  const [entryVal, setEntryVal] = useState('')               // 入口文件输入值
  const [newEngine, setNewEngine] = useState({ label: '', kind: 'webui', root: '', entry: '', detection: null })

  const load = useCallback(async () => {
    setLoading(true)
    try { setEngines(await backendApi.enginesList()) }
    catch (e) { setBanner({ type: 'error', text: `加载引擎失败: ${e.message}` }) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const browse = async (engine) => {
    if (!window.ftn?.selectDirectory) {
      const p = window.prompt('输入根目录路径：', engine.root || '')
      if (p) setPath(engine, p)
      return
    }
    const res = await window.ftn.selectDirectory()
    if (res && !res.canceled && res.path) setPath(engine, res.path)
  }

  const setPath = async (engine, root) => {
    const r = await backendApi.enginesSetPath(engine.key, root)
    if (r.ok) { setBanner({ type: 'ok', text: `已设置 ${engine.label} 路径` }); setEditRoot(null); load() }
    else setBanner({ type: 'error', text: r.msg || '设置失败' })
  }

  // 清空路径：主引擎不可删，用「清空路径」解除配置（引擎条目保留）
  const clearPath = async (engine) => {
    if (!window.confirm(`确定清空「${engine.label}」的路径？\n仅解除路径配置，引擎条目会保留。`)) return
    const r = await backendApi.enginesClearPath(engine.key)
    if (r.ok) { setBanner({ type: 'ok', text: `已清空 ${engine.label} 路径` }); setEditRoot(null); load() }
    else setBanner({ type: 'error', text: r.msg || '清空失败' })
  }

  // 手动确认编辑路径 / 重新检测入口
  const confirmEdit = async (engine) => {
    if (!editVal.trim()) return
    await setPath(engine, editVal.trim())
  }

  // 重新检测启动入口（清除覆盖后按根目录自动探测）
  const reDetect = async (engine) => {
    setDetectingEntry(engine.key)
    const r = await backendApi.enginesReDetectEntry(engine.key)
    if (r?.entry) setBanner({ type: 'ok', text: `${engine.label} 入口已重新检测: ${r.entry.split(/[\\/]/).pop()}` })
    else setBanner({ type: 'error', text: `${engine.label} 未检测到启动入口，请手动「更改启动文件」` })
    setDetectingEntry(null)
    load()
  }

  // 更改启动文件（手动指定入口文件）
  const startEditEntry = (engine) => {
    setEditEntry(engine.key)
    setEntryVal(engine.entry || '')
  }
  const confirmEntry = async (engine) => {
    const val = entryVal.trim()
    const r = await backendApi.enginesSetEntry(engine.key, val)
    if (r?.ok) { setBanner({ type: 'ok', text: `已设置 ${engine.label} 启动文件` }); setEditEntry(null); load() }
    else setBanner({ type: 'error', text: r?.msg || '设置启动文件失败' })
  }
  const browseEntry = async (engine) => {
    if (!window.ftn?.selectFile) { startEditEntry(engine); return }
    const res = await window.ftn.selectFile()
    if (res && !res.canceled && res.path) {
      const r = await backendApi.enginesSetEntry(engine.key, res.path)
      if (r?.ok) { setBanner({ type: 'ok', text: `已设置 ${engine.label} 启动文件` }); load() }
    }
  }

  const startEdit = (engine) => {
    setEditRoot(engine.key)
    setEditVal(engine.root || '')
  }

  const doRename = async (engine) => {
    // 进入内联编辑状态
    setRenameKey(engine.key)
    setRenameVal(engine.label)
  }
  const confirmRename = async (engine) => {
    const label = renameVal.trim()
    if (!label || label === engine.label) { setRenameKey(null); return }
    const r = await backendApi.enginesRename(engine.key, label)
    if (r.ok) { setBanner({ type: 'ok', text: `已改名 → ${label}` }); load() }
    else setBanner({ type: 'error', text: r.msg || '改名失败' })
    setRenameKey(null)
  }

  const doRemove = async (engine) => {
    if (!window.confirm(`确定删除引擎「${engine.label}」？`)) return
    const r = await backendApi.enginesRemove(engine.key)
    if (r.ok) { setBanner({ type: 'ok', text: `已删除 ${engine.label}` }); load() }
    else setBanner({ type: 'error', text: r.msg || '删除失败' })
  }

  // 自动识别：选目录（按根目录内容判定 WebUI / 启动脚本 / HTML）或直接选启动文件
  const detectNew = async (payload) => {
    setBanner(null)
    const r = await backendApi.enginesDetect(payload)
    if (r?.ok) {
      setNewEngine((s) => ({ ...s, kind: r.kind, root: r.root, entry: r.entry, detection: r }))
    } else {
      setBanner({ type: 'error', text: r?.msg || '识别失败' })
      setNewEngine((s) => ({ ...s, detection: null }))
    }
  }
  const pickEngineDir = async () => {
    const res = await window.ftn?.selectDirectory?.()
    if (res && !res.canceled && res.path) detectNew({ root: res.path })
  }
  const pickEngineFile = async () => {
    const res = await window.ftn?.selectFile?.()
    if (res && !res.canceled && res.path) detectNew({ entry: res.path })
  }
  const doAdd = async () => {
    if (!newEngine.label.trim()) { setBanner({ type: 'error', text: '请填写引擎名称' }); return }
    if (!newEngine.detection) { setBanner({ type: 'error', text: '请先「选择引擎目录」或「选择启动文件」完成识别' }); return }
    const r = await backendApi.enginesAdd({ label: newEngine.label, kind: newEngine.kind, root: newEngine.root })
    if (r.ok) {
      if (newEngine.entry) await backendApi.enginesSetEntry(r.key, newEngine.entry)
      setBanner({ type: 'ok', text: `已新增引擎 ${newEngine.label}（${newEngine.detection.kind_label}）` })
      setNewEngine({ label: '', kind: 'webui', root: '', entry: '', detection: null })
      setAdding(false); load()
    } else setBanner({ type: 'error', text: r.msg || '新增失败' })
  }

  // 设为主引擎：把该引擎标记为主引擎（模型 / 插件 / 快捷文件夹 / 版本页随之跟随）
  const setAsPrimary = async (engine) => {
    const fam = engine.family
    const limited = fam && !SUPPORTED_FAMILY.has(fam)
    if (limited) {
      const famTxt = FAMILY_LABEL[fam] || fam
      if (!window.confirm(
        `「${engine.label}」是 ${famTxt} 类型引擎，FTN Atelier 暂未适配该类型。\n\n` +
        `设为主引擎后仅支持 启动/停止/重启；模型管理、插件、版本下载等功能将显示「不适用」，` +
        `不会改动你的模型与数据。\n\n确定设为主引擎？`
      )) return
    } else {
      if (!window.confirm(`确定将「${engine.label}」设为主引擎？\n模型、插件、快捷文件夹将全部跟随它。`)) return
    }
    const r = await backendApi.enginesSetPrimary(engine.key)
    if (r?.ok) {
      setBanner({ type: 'ok', text: r.limited ? r.msg : `主引擎已切换 → ${engine.label}（${r.primary || ''}）` })
      load()
    }
    else setBanner({ type: 'error', text: r?.msg || '切换失败' })
  }
  const canBePrimary = (engine) => !!(engine.root || engine.entry)

  return (
    <section className="rounded-xl border border-base-border bg-base-surface p-5">
      <div className="flex items-center justify-between mb-2">
        <div>
          <h2 className="font-semibold text-txt-secondary">引擎 / 工具</h2>
          <p className="text-xs text-txt-muted mt-0.5">可增删改名 · 主引擎不可删（可改名 / 清空路径）</p>
        </div>
        <button onClick={() => setAdding((v) => !v)}
          className="px-3 py-1.5 rounded-lg border border-accent/40 text-accent text-sm hover:bg-accent-soft">+ 新增引擎</button>
      </div>

      {banner && (
        <div className={`mb-3 px-3 py-2 rounded-lg text-sm ${banner.type === 'ok' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
          {banner.text}
        </div>
      )}

      {adding && (
        <div className="mb-4 p-3 rounded-lg border border-accent/40 bg-accent-soft/30 space-y-2">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <input placeholder="名称（如：Forge 测试）" value={newEngine.label}
              onChange={(e) => setNewEngine({ ...newEngine, label: e.target.value })}
              onKeyDown={(e) => { if (e.key === 'Enter') doAdd(); if (e.key === 'Escape') setAdding(false) }}
              onMouseDown={(e) => { if (e.target === e.currentTarget) e.currentTarget.focus() }}
              className={inputCls} autoFocus autoComplete="off" />
            <div className="flex gap-2">
              <button onClick={pickEngineDir} className="flex-1 px-3 py-2 rounded-lg border border-base-border text-sm hover:bg-base-surface-2">选择引擎目录</button>
              <button onClick={pickEngineFile} className="flex-1 px-3 py-2 rounded-lg border border-base-border text-sm hover:bg-base-surface-2">选择启动文件</button>
            </div>
          </div>
          {newEngine.detection ? (
            <div className="text-xs text-txt-secondary leading-relaxed">
              已识别：<b>{newEngine.detection.kind_label}</b>
              {newEngine.detection.family ? ` · ${newEngine.detection.family_label} 家族` : ''}
              <div className="text-txt-muted mt-0.5 break-all">启动文件：{newEngine.detection.entry}</div>
            </div>
          ) : (
            <p className="text-xs text-txt-muted">选择引擎根目录（自动识别 WebUI / 启动脚本 / HTML），或直接选择启动文件（.bat / .py / index.html）。</p>
          )}
          <div className="flex justify-end gap-2">
            <button onClick={() => setAdding(false)} className="px-3 py-2 rounded-lg border border-base-border text-sm">取消</button>
            <button onClick={doAdd} disabled={!newEngine.detection || !newEngine.label.trim()}
              className="px-4 py-2 rounded-lg bg-accent text-white text-sm disabled:opacity-40">确认新增</button>
          </div>
        </div>
      )}

      <div className="space-y-2.5">
        {loading ? <p className="text-sm text-txt-muted">加载中...</p>
          : engines.map((e) => (
            <div key={e.key} className="rounded-lg border border-base-border p-3.5 bg-base-bg/40">
              <div className="flex items-center gap-2 mb-2.5">
                {renameKey === e.key ? (
                  <>
                    <input autoFocus value={renameVal}
                      onChange={(ev) => setRenameVal(ev.target.value)}
                      onKeyDown={(ev) => { if (ev.key === 'Enter') confirmRename(e); if (ev.key === 'Escape') setRenameKey(null) }}
                      className={`${inputCls} !flex-1 text-sm`} autoComplete="off" />
                    <button onClick={() => confirmRename(e)} className="px-2 py-1 rounded border border-accent text-accent text-[11px] hover:bg-accent-soft">确定</button>
                    <button onClick={() => setRenameKey(null)} className="px-2 py-1 rounded border border-base-border text-[11px] hover:bg-base-surface-2">取消</button>
                  </>
                ) : (
                  <span className="font-semibold text-sm">{e.label}</span>
                )}
                {e.family && (
                  <span className="px-1.5 py-0.5 rounded bg-base-surface-2 text-[10px] text-txt-muted">{FAMILY_LABEL[e.family] || e.family}</span>
                )}
                {e.primary && renameKey !== e.key && (
                  <span className="px-1.5 py-0.5 rounded bg-accent-soft text-accent text-[10px] font-medium">主引擎 · 不可删</span>
                )}
                <div className="ml-auto flex gap-1.5">
                  <button onClick={() => doRename(e)} className="px-2 py-1 rounded border border-base-border text-[11px] hover:bg-base-surface-2">改名</button>
                  {!e.primary && canBePrimary(e) && (
                    <button onClick={() => setAsPrimary(e)} className="px-2 py-1 rounded border border-accent/40 text-accent text-[11px] hover:bg-accent-soft">设为主引擎</button>
                  )}
                  {!e.primary && (
                    <button onClick={() => doRemove(e)} className="px-2 py-1 rounded border border-red-500/30 text-red-400 text-[11px] hover:bg-red-500/10">删除</button>
                  )}
                </div>
              </div>
              {/* 行 1：根目录路径 */}
              <div className="flex items-center gap-2">
                {editRoot === e.key ? (
                  <>
                    <input value={editVal} onChange={(ev) => setEditVal(ev.target.value)}
                      className={`${inputCls} text-xs`} autoFocus autoComplete="off"
                      onKeyDown={(ev) => { if (ev.key === 'Enter') confirmEdit(e); if (ev.key === 'Escape') setEditRoot(null) }} />
                    <button onClick={() => confirmEdit(e)} className="px-2.5 py-2 rounded-lg border border-accent text-accent text-xs shrink-0">保存</button>
                    <button onClick={() => setEditRoot(null)} className="px-2.5 py-2 rounded-lg border border-base-border text-xs shrink-0">取消</button>
                  </>
                ) : (
                  <>
                    <input value={e.root || ''} readOnly placeholder="未设置引擎根目录" className={`${inputCls} text-xs`} />
                    <button onClick={() => browse(e)} className="px-3 py-2 rounded-lg border border-base-border text-sm hover:bg-base-surface-2 shrink-0">更改路径</button>
                    {e.root && (
                      <button onClick={() => clearPath(e)} className="px-3 py-2 rounded-lg border border-red-500/30 text-red-400 text-sm hover:bg-red-500/10 shrink-0">清空路径</button>
                    )}
                  </>
                )}
              </div>
              {/* 行 2：启动文件（详细路径） */}
              <div className="mt-2 flex items-center gap-2">
                {editEntry === e.key ? (
                  <>
                    <input value={entryVal} onChange={(ev) => setEntryVal(ev.target.value)}
                      className={`${inputCls} text-xs`} autoFocus autoComplete="off"
                      placeholder="启动文件完整路径，如 D:/reforge/webui.bat"
                      onKeyDown={(ev) => { if (ev.key === 'Enter') confirmEntry(e); if (ev.key === 'Escape') setEditEntry(null) }} />
                    <button onClick={() => confirmEntry(e)} className="px-2.5 py-2 rounded-lg border border-accent text-accent text-xs shrink-0">保存</button>
                    <button onClick={() => setEditEntry(null)} className="px-2.5 py-2 rounded-lg border border-base-border text-xs shrink-0">取消</button>
                  </>
                ) : (
                  <>
                    <span className={`flex-1 truncate text-xs px-3 py-2 rounded-lg border ${e.entry ? 'text-emerald-400 border-base-border bg-base-bg/40' : 'text-txt-muted border-base-border bg-base-surface-2/50'}`}>
                      {e.entry ? e.entry : '未设置启动文件'}
                    </span>
                    <button onClick={() => browseEntry(e)} className="px-3 py-2 rounded-lg border border-base-border text-xs hover:bg-base-surface-2 shrink-0">更改启动文件</button>
                    <button onClick={() => reDetect(e)} disabled={detectingEntry === e.key}
                      className="px-3 py-2 rounded-lg border border-base-border text-xs hover:bg-base-surface-2 shrink-0 disabled:opacity-50">
                      {detectingEntry === e.key ? '检测中...' : '重新检测'}
                    </button>
                  </>
                )}
              </div>
            </div>
          ))}
      </div>
    </section>
  )
}

// ============ 快捷文件夹（首页） ============
// 默认 5 个文件夹（root / txt1 / txtg / img1 / imgg）：可「更改路径」也可「重新检测」。
// 其他额外文件夹：仅「更改路径」，不提供「重新检测」（没用）。
const DEFAULT_FOLDER_KEYS = new Set(['root', 'txt1', 'txtg', 'img1', 'imgg'])

function QuickFolders() {
  const [folders, setFolders] = useState([])
  const [loading, setLoading] = useState(true)
  const [banner, setBanner] = useState(null)
  // 内联改名
  const [editingLabel, setEditingLabel] = useState(null)
  const [labelVal, setLabelVal] = useState('')
  // 新增自定义文件夹
  const [adding, setAdding] = useState(false)
  const [newLabel, setNewLabel] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try { const r = await backendApi.quickFolders(); setFolders(r?.folders || []) }
    catch (e) { setBanner({ type: 'error', text: `加载失败: ${e.message}` }) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  // 统一保存：每次变更（改名 / 改路径 / 重新检测 / 新增）即时写后端，免去「保存」按钮
  const save = async (next) => {
    setBanner(null)
    try {
      const r = await backendApi.quickFoldersUpdate(next)
      if (r?.ok) { setFolders(r.folders); setBanner({ type: 'ok', text: '已保存' }) }
      else setBanner({ type: 'error', text: r?.msg || '保存失败' })
    } catch (e) { setBanner({ type: 'error', text: `保存失败: ${e.message}` }) }
  }

  const startLabelEdit = (f) => { setEditingLabel(f.key); setLabelVal(f.label) }
  const confirmLabel = (f) => {
    const v = labelVal.trim()
    if (v) save(folders.map((x) => x.key === f.key ? { ...x, label: v } : x))
    setEditingLabel(null)
  }
  // 「更改路径」：手动浏览并指定路径
  const browsePath = async (f) => {
    if (!window.ftn?.selectDirectory) {
      const p = window.prompt('输入该快捷文件夹路径：', f.custom_path || '')
      if (p) save(folders.map((x) => x.key === f.key ? { ...x, custom_path: p } : x))
      return
    }
    const res = await window.ftn.selectDirectory()
    if (res && !res.canceled && res.path) {
      save(folders.map((x) => x.key === f.key ? { ...x, custom_path: res.path } : x))
    }
  }
  // 「重新检测」：清空自定义路径，回退到按主引擎自动检测
  const resetDetect = (f) => save(folders.map((x) => x.key === f.key ? { ...x, custom_path: '' } : x))
  // 删除自建快捷文件夹（默认 5 项不可删）
  const doRemoveFolder = async (f) => {
    if (!window.confirm(`确定删除快捷文件夹「${f.label}」？`)) return
    save(folders.filter((x) => x.key !== f.key))
  }
  // 新增自定义文件夹（自定义路径手动指定，不走自动检测）
  const doAdd = async () => {
    const label = newLabel.trim()
    if (!label) { setBanner({ type: 'error', text: '请填写文件夹名称' }); return }
    save([...folders, { key: 'custom-' + Date.now(), label, mode: 'custom', custom_path: '' }])
    setNewLabel(''); setAdding(false)
  }

  return (
    <section className="rounded-xl border border-base-border bg-base-surface p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="font-semibold text-txt-secondary">首页快捷文件夹</h2>
          <p className="text-xs text-txt-muted mt-0.5">默认 5 项不可删除；可改名 / 「更改路径」手动指定 / 「重新检测」回退到主引擎自动检测。修改即自动保存。</p>
        </div>
        <button onClick={() => setAdding((v) => !v)}
          className="px-3 py-1.5 rounded-lg border border-accent/40 text-accent text-sm hover:bg-accent-soft">＋ 新增文件夹</button>
      </div>

      {banner && (
        <div className={`mb-3 px-3 py-2 rounded-lg text-sm ${banner.type === 'ok' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
          {banner.text}
        </div>
      )}

      {adding && (
        <div className="mb-4 p-3 rounded-lg border border-accent/40 bg-accent-soft/30 flex gap-2">
          <input autoFocus value={newLabel} onChange={(e) => setNewLabel(e.target.value)}
            placeholder="自定义文件夹名称" className={inputCls}
            onKeyDown={(e) => { if (e.key === 'Enter') doAdd(); if (e.key === 'Escape') setAdding(false) }}
            onMouseDown={(e) => { if (e.target === e.currentTarget) e.currentTarget.focus() }} autoComplete="off" />
          <button onClick={doAdd} className="px-3 py-2 rounded-lg bg-accent text-white text-sm shrink-0">添加</button>
          <button onClick={() => setAdding(false)} className="px-3 py-2 rounded-lg border border-base-border text-sm shrink-0">取消</button>
        </div>
      )}

      <div className="space-y-2.5">
        {loading ? <p className="text-sm text-txt-muted">加载中...</p> : folders.map((f) => {
          const isDefault = DEFAULT_FOLDER_KEYS.has(f.key)
          return (
          <div key={f.key} className="rounded-lg border border-base-border p-3.5 bg-base-bg/40">
            <div className="flex items-center gap-2 mb-2">
              {editingLabel === f.key ? (
                <>
                  <input autoFocus value={labelVal} onChange={(e) => setLabelVal(e.target.value)}
                    className={`${inputCls} !flex-1 text-sm`} autoComplete="off"
                    onKeyDown={(e) => { if (e.key === 'Enter') confirmLabel(f); if (e.key === 'Escape') setEditingLabel(null) }} />
                  <button onClick={() => confirmLabel(f)} className="px-2 py-1 rounded border border-accent text-accent text-[11px] hover:bg-accent-soft">确定</button>
                  <button onClick={() => setEditingLabel(null)} className="px-2 py-1 rounded border border-base-border text-[11px]">取消</button>
                </>
              ) : (
                <span className="font-semibold text-sm">{f.label}</span>
              )}
              <span className="px-1.5 py-0.5 rounded bg-base-surface-2 text-[10px] text-txt-muted">{f.key}-{f.mode}</span>
              <div className="ml-auto flex gap-1.5">
                <button onClick={() => startLabelEdit(f)} className="px-2 py-1 rounded border border-base-border text-[11px] hover:bg-base-surface-2">改名</button>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className={`flex-1 truncate text-xs ${f.path ? 'text-txt-secondary' : 'text-txt-muted'}`}>
                {f.path || '未配置'}
              </span>
              <button onClick={() => browsePath(f)} className="px-3 py-2 rounded-lg border border-base-border text-xs hover:bg-base-surface-2 shrink-0">更改路径</button>
              {isDefault && (
                <button onClick={() => resetDetect(f)} className="px-3 py-2 rounded-lg border border-base-border text-xs hover:bg-base-surface-2 shrink-0">重新检测</button>
              )}
              {!isDefault && (
                <button onClick={() => doRemoveFolder(f)} className="px-3 py-2 rounded-lg border border-red-500/30 text-red-400 text-xs hover:bg-red-500/10 shrink-0">删除</button>
              )}
            </div>
            {f.custom_path && <p className="mt-1.5 text-[11px] text-txt-muted">已手动指定路径，主引擎切换不会影响此项。可点「重新检测」回退到自动检测。</p>}
          </div>
          )
        })}
      </div>
    </section>
  )
}

// ============ 启动参数 ============
// 兜底显存模式（主基底信息未加载时的缺省展示）
const FALLBACK_VRAM = [
  { value: 'auto', label: '自动（默认）', arg: '', hint: '不附加显存参数，让引擎自动判断' },
  { value: 'low', label: '低占用', arg: '--lowvram', hint: '--lowvram' },
]
function StartArgs({ config, update }) {
  const s = config?.start_args || {}
  // 主基底：决定显存模式的可选项（跟随主基底自动适配其参数）
  const [baseInfo, setBaseInfo] = useState(null) // {primary, label, vram_modes}
  useEffect(() => {
    backendApi.basesSnapshot().then((r) => {
      const def = (r?.defs || []).find((d) => d.key === (r?.primary || 'reforge'))
      setBaseInfo({
        primary: r?.primary || 'reforge',
        label: def?.label || '生图引擎',
        vram_modes: def?.vram_modes || FALLBACK_VRAM,
      })
    }).catch(() => setBaseInfo({ primary: 'reforge', label: '生图引擎', vram_modes: FALLBACK_VRAM }))
  }, [])
  const vramModes = baseInfo?.vram_modes || FALLBACK_VRAM
  const vramMode = vramModes.find((m) => m.value === s.vram_mode) || vramModes[0]
  // GPU 自动检测
  const [gpus, setGpus] = useState(null)          // null=未检测 / [] =检测失败
  const [detecting, setDetecting] = useState(false)
  const selIds = Array.isArray(s.gpu_ids) && s.gpu_ids.length ? s.gpu_ids : [s.gpu_index ?? 0]

  const detectGpu = async () => {
    setDetecting(true)
    try { const r = await backendApi.systemGpu(); setGpus(r?.gpus || []) }
    catch { setGpus([]) }
    finally { setDetecting(false) }
  }
  useEffect(() => { detectGpu() }, [])

  const toggleGpu = (idx) => {
    const next = selIds.includes(idx) ? selIds.filter((x) => x !== idx) : [...selIds, idx]
    if (!next.length) return
    update('start_args', 'gpu_ids', next.sort((a, b) => a - b))
    update('start_args', 'gpu_index', next[0])
  }

  return (
    <section className="rounded-xl border border-base-border bg-base-surface p-5 space-y-4">
      <h2 className="font-semibold text-txt-secondary">启动参数</h2>

      {/* 显卡选择：自动检测 + 多选 */}
      <Field label="生成引擎 / 显卡" desc={detecting ? '正在自动检测显卡...' : (gpus && gpus.length ? `检测到 ${gpus.length} 张显卡（nvidia-smi）` : '自动检测失败，请手动指定索引')}>
        {gpus && gpus.length ? (
          <div className="space-y-1.5">
            {gpus.map((g) => (
              <label key={g.index} className="flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer"
                style={{ borderColor: selIds.includes(g.index) ? 'var(--color-accent)' : 'var(--color-border)', background: selIds.includes(g.index) ? 'var(--color-accent-soft)' : 'transparent' }}>
                <input type="checkbox" checked={selIds.includes(g.index)} onChange={() => toggleGpu(g.index)} className="accent-current" />
                <span className="text-sm">{g.name}</span>
                <span className="ml-auto text-[11px] text-txt-muted">{g.vram}</span>
              </label>
            ))}
            <div className="flex items-center gap-2 pt-1">
              <span className="text-[11px] text-txt-muted">或手动指定索引（逗号分隔）：</span>
              <input value={selIds.join(',')} onChange={(e) => {
                const ids = e.target.value.split(',').map((x) => parseInt(x)).filter((n) => !isNaN(n))
                update('start_args', 'gpu_ids', ids)
                if (ids.length) update('start_args', 'gpu_index', ids[0])
              }} className={`${inputCls} max-w-40`} autoComplete="off" />
            </div>
            <p className="text-xs text-txt-muted">勾选多用于生成的多张卡（单张则默认选中那一张）；可随时「重新检测」。</p>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <input type="number" min={0} value={s.gpu_index ?? 0}
              onChange={(e) => update('start_args', 'gpu_index', parseInt(e.target.value) || 0)}
              className={inputCls} autoComplete="off" />
            <button onClick={detectGpu} className="px-3 py-2 rounded-lg border border-base-border text-sm hover:bg-base-surface-2 shrink-0">重新检测</button>
          </div>
        )}
        {!(gpus && gpus.length) && (
          <button onClick={detectGpu} className="mt-2 text-xs text-accent hover:underline">自动检测失败？点击重新检测</button>
        )}
      </Field>

      <Field label="显存模式" desc={`控制显存占用策略（跟随主基底：${baseInfo?.label || '生图引擎'}）`}>
        <select value={s.vram_mode} onChange={(e) => update('start_args', 'vram_mode', e.target.value)} className={inputCls}>
          {vramModes.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
        </select>
        <p className="text-xs text-txt-muted mt-1">{vramMode.hint || (vramMode.arg ? `参数：${vramMode.arg}` : '不附加显存参数')}</p>
      </Field>
      <Field label="端口" desc="webui 监听端口">
        <input type="number" min={1} max={65535} value={s.port ?? 7860}
          onChange={(e) => update('start_args', 'port', parseInt(e.target.value) || 7860)}
          className={inputCls} />
      </Field>
      <div className="flex gap-6">
        <Toggle label="启动后打开浏览器" checked={!!s.open_browser} onChange={(v) => update('start_args', 'open_browser', v)} />
        <Toggle label="强制 CPU 模式(调试)" checked={!!s.use_cpu} onChange={(v) => update('start_args', 'use_cpu', v)} />
      </div>
    </section>
  )
}

// ============ 环境配置 ============
function EnvConfigForm({ config, update }) {
  const e = config?.env || {}
  const browsePy = async () => {
    if (!window.ftn?.selectDirectory) { update('env', 'python_path', window.prompt('输入 Python 目录/路径：', e.python_path || '')); return }
    const res = await window.ftn.selectDirectory()
    if (res && !res.canceled && res.path) update('env', 'python_path', res.path)
  }
  return (
    <section className="rounded-xl border border-base-border bg-base-surface p-5 space-y-4">
      <h2 className="font-semibold text-txt-secondary">环境配置</h2>
      <Field label="Python 解释器" desc="留空 = 自动探测">
        <div className="flex gap-2">
          <input value={e.python_path || ''}
            onChange={(ev) => update('env', 'python_path', ev.target.value)}
            className={inputCls} placeholder="留空自动探测" />
          <button onClick={browsePy} className="px-3 py-2 rounded-lg border border-base-border text-sm hover:bg-base-surface-2">浏览器目录</button>
        </div>
      </Field>
      <div className="border-t border-base-border pt-4 space-y-4">
        <h3 className="text-sm font-medium text-txt-secondary">下载镜像</h3>
        <div className="space-y-1.5">
          <Toggle label="PyPI 国内镜像下载" checked={!!e.use_py_mirror} onChange={(v) => update('env', 'use_py_mirror', v)} />
          <Toggle label="HuggingFace 国内镜像下载" checked={!!e.use_hf_mirror} onChange={(v) => update('env', 'use_hf_mirror', v)} />
          <Toggle label="Git 国内镜像下载（版本 / 插件克隆）" checked={!!e.use_git_mirror} onChange={(v) => update('env', 'use_git_mirror', v)} />
        </div>
        <Field label="PyPI 镜像源">
          <input value={e.pip_mirror || ''} onChange={(ev) => update('env', 'pip_mirror', ev.target.value)} className={inputCls} />
        </Field>
        <Field label="HuggingFace 镜像端点">
          <input value={e.hf_endpoint || ''} onChange={(ev) => update('env', 'hf_endpoint', ev.target.value)} className={inputCls} />
        </Field>
        <Field label="Git / GitHub 下载镜像前缀" desc="留空则不启用。常用于加速版本实例 / 插件克隆（如 ghproxy）。">
          <input value={e.git_mirror || ''} onChange={(ev) => update('env', 'git_mirror', ev.target.value)} className={inputCls} placeholder="https://ghproxy.com/" />
        </Field>
      </div>
      <div className="border-t border-base-border pt-4 space-y-3">
        <h3 className="text-sm font-medium text-txt-secondary">多版本共享环境</h3>
        <Toggle label="多版本间共享 venv（小版本复用，大版本自动提示重建）" checked={!!config?.venv_share} onChange={(v) => update('__top__', 'venv_share', v)} />
        <p className="text-xs text-txt-muted">开启后，生图引擎各小版本复用同一套共享环境，节省磁盘；当跨大版本（如 1.10 → 1.11，Python/Torch 依赖可能变）时自动检测并提示「保留 / 重建」环境。</p>
      </div>
    </section>
  )
}

// ============ 用户偏好 ============
function Preference({ config, update }) {
  const p = config?.preference || {}
  const langs = [
    { value: 'system', label: '跟随系统' },
    { value: 'zh-CN', label: '简体中文' },
    { value: 'en-US', label: 'English (US)' },
    { value: 'ja-JP', label: '日本語' },
  ]
  const logLevels = ['DEBUG', 'INFO', 'WARN', 'ERROR']
  return (
    <section className="rounded-xl border border-base-border bg-base-surface p-5 space-y-4">
      <h2 className="font-semibold text-txt-secondary">用户偏好</h2>
      <Field label="语言">
        <select value={p.language} onChange={(e) => update('preference', 'language', e.target.value)} className={inputCls}>
          {langs.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
        </select>
      </Field>
      <Field label="日志级别">
        <select value={p.log_level} onChange={(e) => update('preference', 'log_level', e.target.value)} className={inputCls}>
          {logLevels.map((l) => <option key={l} value={l}>{l}</option>)}
        </select>
      </Field>
      <p className="text-xs text-txt-muted">外观主题 / 外观动画请前往「主题」页设置。</p>
    </section>
  )
}

// ============ 网站 API（CivitAI / HuggingFace） ============
function WebsiteApis({ config, update }) {
  const k = config?.api_keys || {}
  const openUrl = (url) => {
    if (window.ftn?.openPath) window.ftn.openPath(url)
    else window.open(url, '_blank')
  }
  return (
    <section className="rounded-xl border border-base-border bg-base-surface p-5 space-y-4">
      <h2 className="font-semibold text-txt-secondary">网站 API</h2>
      <p className="text-xs text-txt-muted">
        用于「网络下载」从各平台拉取模型。凭据保存在<b>本机数据目录</b>（%APPDATA%\ftn-studio-frontend，或源码目录 Database\），
        不会随程序本体分发；「数据管理」导出时已自动隐去凭据。请勿把导出文件分享给他人。
      </p>

      <Field label="CivitAI API Key" desc="前往 CivitAI「账号设置 → API Keys」创建（https://civitai.com/user/account）">
        <div className="flex gap-2">
          <input type="password" value={k.civitai_api_key || ''}
            onChange={(e) => update('api_keys', 'civitai_api_key', e.target.value)}
            className={inputCls} placeholder="civitai_xxxxxxxx" autoComplete="off" />
          <button onClick={() => openUrl('https://civitai.com/user/account')}
            className="px-3 py-2 rounded-lg border border-base-border text-sm hover:bg-base-surface-2 shrink-0">一键直达</button>
        </div>
        {k.civitai_api_key ? (
          <p className="text-xs text-emerald-400 mt-1.5">✔ 已填写，可前往「模型」页使用网络下载。</p>
        ) : (
          <p className="text-xs text-amber-400/90 mt-1.5">未填写 — 模型页下载前会提示「请前往设置填写 API」。</p>
        )}
      </Field>

      <Field label="HuggingFace Access Token" desc="前往 HuggingFace「Settings → Access Tokens」创建（https://huggingface.co/settings/tokens）">
        <div className="flex gap-2">
          <input type="password" value={k.huggingface_token || ''}
            onChange={(e) => update('api_keys', 'huggingface_token', e.target.value)}
            className={inputCls} placeholder="hf_xxxxxxxx" autoComplete="off" />
          <button onClick={() => openUrl('https://huggingface.co/settings/tokens')}
            className="px-3 py-2 rounded-lg border border-base-border text-sm hover:bg-base-surface-2 shrink-0">一键直达</button>
        </div>
        {k.huggingface_token ? (
          <p className="text-xs text-emerald-400 mt-1.5">✔ 已填写，可前往「模型」页使用网络下载。</p>
        ) : (
          <p className="text-xs text-amber-400/90 mt-1.5">未填写 — 模型页下载前会提示「请前往设置填写 API」。</p>
        )}
      </Field>

      <div className="pt-2 border-t border-base-border flex items-center gap-3">
        <button
          onClick={() => {
            if (!window.confirm('确定清除已保存的 CivitAI / HuggingFace 凭据？（仅清除本机保存，不影响官网账号）')) return
            update('api_keys', 'civitai_api_key', '')
            update('api_keys', 'huggingface_token', '')
          }}
          className="px-4 py-2 rounded-lg border border-red-500/30 text-red-400 text-sm hover:bg-red-500/10 shrink-0">
          清除凭据
        </button>
        <span className="text-[11px] text-txt-muted">防止把含密钥的数据分享/备份给他人时泄露。</span>
      </div>
    </section>
  )
}

// ============ 输出整理（不分日期） ============
function OutputMaintain() {
  const [enabled, setEnabled] = useState(null)      // null=加载中
  const [banner, setBanner] = useState(null)
  const [orgMsg, setOrgMsg] = useState(null)
  const [organizing, setOrganizing] = useState(false)

  const load = useCallback(async () => {
    try { const r = await backendApi.outputsAutoOrganize(); setEnabled(!!r?.enabled) }
    catch (e) { setBanner({ type: 'error', text: `加载失败: ${e.message}` }) }
  }, [])
  useEffect(() => { load() }, [load])

  const toggle = async (v) => {
    setBanner(null)
    setEnabled(v)
    try {
      const r = await backendApi.outputsSetAutoOrganize(v)
      setEnabled(!!r?.enabled)
      setBanner({ type: 'ok', text: v ? '已开启：日期子目录内容将自动上提到 outputs 根目录' : '已关闭自动整理' })
    } catch (e) {
      setBanner({ type: 'error', text: `保存失败: ${e.message}` }); setEnabled(!v)
    }
  }

  const organizeNow = async () => {
    setOrganizing(true)
    setOrgMsg(null)
    try {
      const r = await backendApi.outputsOrganizeNow()
      const res = r?.result || {}
      const moved = res.moved?.length || 0
      const removed = res.removed?.length || 0
      setOrgMsg(moved + removed ? { type: 'ok', text: `整理完成：迁移 ${moved} 个文件，删除 ${removed} 个空日期目录` } : { type: 'info', text: '当前没有需要整理的日期目录' })
    } catch (e) {
      setOrgMsg({ type: 'error', text: `整理失败: ${e.message}` })
    } finally { setOrganizing(false) }
  }

  return (
    <section className="rounded-xl border border-base-border bg-base-surface p-5 space-y-4">
      <h2 className="font-semibold text-txt-secondary">输出整理 · 不分日期</h2>
      <p className="text-xs text-txt-muted">生图引擎（reForge / Forge 同源）默认把生成图存到 <b>outputs/文种-images/日期目录/</b>。开启本开关后，后台会持续把新增图片自动上提到 <b>outputs/文种-images/</b> 根目录（不分日期），并删除空日期目录。不修改引擎源码，纯外部整理。</p>

      {banner && (
        <div className={`px-3 py-2 rounded-lg text-sm ${banner.type === 'ok' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
          {banner.text}
        </div>
      )}

      <Field label="自动整理" desc="开启后后台线程持续监听并整理 outputs 输出的日期子目录（默认每 3 秒检查一次）。">
        <Toggle label={enabled ? '已开启' : '已关闭'} checked={!!enabled} onChange={toggle} />
      </Field>

      <Field label="立即整理一次" desc="不依赖定时轮询，现在就把已有的日期子目录内容全部上提到对应根目录。">
        <button onClick={organizeNow} disabled={organizing}
          className="px-4 py-2 rounded-lg border border-accent/40 text-accent text-sm hover:bg-accent-soft disabled:opacity-50">
          {organizing ? '整理中…' : '立即整理'}
        </button>
      </Field>

      {orgMsg && (
        <div className={`px-3 py-2 rounded-lg text-sm ${orgMsg.type === 'ok' ? 'bg-emerald-500/10 text-emerald-400' : orgMsg.type === 'info' ? 'bg-sky-500/10 text-sky-400' : 'bg-red-500/10 text-red-400'}`}>
          {orgMsg.text}
        </div>
      )}

      <div className="rounded-lg bg-base-surface-2/40 border border-base-border px-4 py-3 text-xs text-txt-muted">
        提示：仅整理以「<b>-images</b>」结尾的输出目录（如 txt2img-images / img2img-images）中的「纯 8 位数字日期」子目录；文件名冲突自动追加序号，不会覆盖现有图片。
      </div>
    </section>
  )
}

// ============ 软件修复更新 ============
function SelfCheckSettings({ config, update }) {
  // 自检开关：启动自检 / 自动检测更新 / 更新源配置
  const sc = config?.selfcheck || {}
  const [openDlg, setOpenDlg] = useState(false)
  const [updMsg, setUpdMsg] = useState(null)   // 版本检测结果
  const [checkingUpd, setCheckingUpd] = useState(false)
  const [latestInfo, setLatestInfo] = useState(null)   // 检测到的最新版本信息（含资产）
  const [updating, setUpdating] = useState(null)       // {pct, msg, error?} 全屏更新遮罩
  const [ver, setVer] = useState('')

  useEffect(() => {
    let alive = true
    window.ftn?.getAppInfo?.().then((r) => { if (alive && r?.version) setVer(r.version) }).catch(() => {})
    return () => { alive = false }
  }, [])

  const checkUpdate = async () => {
    setCheckingUpd(true)
    setUpdMsg(null)
    setLatestInfo(null)
    try {
      const u = await backendApi.selfcheckUpdate()
      if (!u.ok) setUpdMsg({ type: 'error', text: `无法检测更新：${u.error || '未知'}` })
      else if (u.has_update) {
        setLatestInfo(u)
        setUpdMsg({ type: 'ok', text: `发现新版本 v${u.latest}（当前 v${u.current}，更新源 ${u.owner}/${u.repo}）` })
      } else setUpdMsg({ type: 'ok', text: `当前已是最新版本（v${u.current}）` })
    } catch (e) {
      setUpdMsg({ type: 'error', text: `检测更新失败：${e.message}` })
    } finally {
      setCheckingUpd(false)
    }
  }

  // 一键更新（与自检弹窗同一实现）：下载 → 进度 → Electron 备份/替换/重启。
  // 更新期间全屏遮罩，禁止任何操作（除强制结束进程）。
  const beginUpdate = async () => {
    if (!latestInfo) return
    if (!window.confirm(
      `将下载并应用更新 v${latestInfo.latest}（当前 v${latestInfo.current}）。\n\n` +
      '下载完成后会自动替换程序文件并重启（保留 Core/Data/Database/Logs 等数据目录）。确定继续？'
    )) return
    setUpdating({ pct: 0, msg: '正在启动更新…' })
    await startUpdate({
      onProgress: (phase, pct, msg) => setUpdating({ pct: pct ?? 0, msg }),
      onError: (err) => setUpdating({ pct: 0, msg: err, error: true }),
      assetUrl: latestInfo?.asset?.url,
      expectedVersion: latestInfo?.latest,
      assetSize: latestInfo?.asset?.size,
      assetSha256: latestInfo?.asset?.sha256,
    })
  }

  return (
    <section className="rounded-xl border border-base-border bg-base-surface p-5 space-y-4">
      <h2 className="font-semibold text-txt-secondary">软件修复更新</h2>
      <p className="text-xs text-txt-muted">启动引导自检可提前发现环境 / 目录 / 配置 / 进程等异常；版本自动检测在打开软件前确认是否可更新。</p>

      <Field label="启动自检" desc="打开 FTN Atelier 时，先执行环境自检并进入引导（默认开）。">
        <Toggle label="" checked={sc.run_on_startup !== false} onChange={(v) => update('selfcheck', 'run_on_startup', v)} />
      </Field>

      <Field label="自动检测更新" desc="启动前自动检查 FTN Atelier 是否有新版本（需已配置更新源；默认开）。">
        <Toggle label="" checked={sc.check_update_on_startup !== false} onChange={(v) => update('selfcheck', 'check_update_on_startup', v)} />
      </Field>

      <div className="border-t border-base-border pt-4 text-xs text-txt-muted">
        <p>当前 FTN Atelier 版本：v{ver} ｜ 更新源：由发布方统一配置（F-tidal-night/ftn-atelier）</p>
      </div>

      <div className="flex items-center gap-3 pt-1">
        <button onClick={() => setOpenDlg(true)}
          className="px-4 py-2 rounded-lg border border-accent/40 text-accent text-sm hover:bg-accent-soft">
          立即运行自检
        </button>
        <button onClick={checkUpdate} disabled={checkingUpd}
          className="px-4 py-2 rounded-lg border border-base-border text-sm hover:bg-base-surface-2 disabled:opacity-50">
          {checkingUpd ? '检测中…' : '检测版本更新'}
        </button>
      </div>
      {updMsg && (
        <div className={`px-3 py-2 rounded-lg text-sm ${updMsg.type === 'ok' ? 'bg-emerald-500/10 text-emerald-400' : updMsg.type === 'info' ? 'bg-sky-500/10 text-sky-400' : 'bg-red-500/10 text-red-400'}`}>
          {updMsg.text}
        </div>
      )}
      {latestInfo && !updating && (
        <div className="flex items-center gap-2">
          <button onClick={beginUpdate}
            className="px-4 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:opacity-90">
            开始更新到 v{latestInfo.latest}
          </button>
        </div>
      )}

      {openDlg && (
        <SelfCheckModal
          mode="manual"
          checkUpdate={false}
          onClose={() => setOpenDlg(false)}
        />
      )}

      {/* 更新全屏遮罩：更新期间禁止任何操作（除强制结束进程） */}
      {updating && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 p-6">
          <div className="w-full max-w-md rounded-2xl border border-base-border bg-base-surface p-6 text-center">
            <p className="font-semibold text-txt-primary">{updating.error ? '更新失败' : '正在更新 FTN Atelier…'}</p>
            {!updating.error && (
              <div className="mt-4 h-2 rounded-full bg-base-surface-2 overflow-hidden">
                <div className="h-full bg-accent transition-all duration-300" style={{ width: `${updating.pct || 0}%` }} />
              </div>
            )}
            <p className={`mt-3 text-sm break-words ${updating.error ? 'text-rose-400' : 'text-txt-muted'}`}>{updating.msg}</p>
            {updating.error ? (
              <button onClick={() => setUpdating(null)} className="mt-4 px-4 py-2 rounded-lg bg-accent text-white text-sm">关闭</button>
            ) : (
              <p className="mt-4 text-[11px] text-txt-muted">更新期间请勿关闭或操作程序；异常中断时可通过任务管理器强制结束进程。</p>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

// ============ 通用控件 ============
const inputCls = 'flex-1 px-3 py-2 rounded-lg border border-base-border bg-base-bg text-sm focus:outline-none focus:border-accent'

function Field({ label, desc, children }) {
  return (
    <div>
      <label className="block text-sm font-medium mb-1">{label}</label>
      {desc && <p className="text-xs text-txt-muted mb-2">{desc}</p>}
      {children}
    </div>
  )
}

function PathField({ label, desc, value, onChange, onBrowse }) {
  return (
    <div>
      <label className="block text-sm font-medium mb-1">{label}</label>
      {desc && <p className="text-xs text-txt-muted mb-2">{desc}</p>}
      <div className="flex gap-2">
        <input value={value || ''} onChange={(e) => onChange(e.target.value)}
          className={inputCls} placeholder="未设置" />
        <button onClick={onBrowse} className="px-3 py-2 rounded-lg border border-base-border text-sm hover:bg-base-surface-2 shrink-0">浏览...</button>
      </div>
    </div>
  )
}

function Toggle({ label, checked, onChange }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer select-none">
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={`w-9 h-5 rounded-full relative transition-colors ${checked ? 'bg-accent' : 'bg-base-surface-2 border border-base-border'}`}
      >
        <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all ${checked ? 'left-4.5' : 'left-0.5'}`} />
      </button>
      <span className="text-sm">{label}</span>
    </label>
  )
}

// ============ 数据管理（配置 / 引擎注册 / 模型索引 导出导入） ============
function DataManage() {
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)

  const doExport = async () => {
    setBusy(true); setMsg(null)
    try {
      const r = await backendApi.dataExport()
      if (!r?.ok) { setMsg({ type: 'error', text: r?.msg || '导出失败' }); return }
      const content = JSON.stringify(r.data, null, 2)
      if (window.ftn?.saveTextFile) {
        const res = await window.ftn.saveTextFile('FTN-Atelier-数据备份.json', content)
        setMsg({ type: res?.ok !== false ? 'ok' : 'error', text: res?.ok !== false ? `已导出到 ${res.path}` : '导出已取消或失败' })
      } else {
        setMsg({ type: 'ok', text: `导出数据（${content.length} 字符）` })
      }
    } catch (e) { setMsg({ type: 'error', text: `导出失败: ${e.message}` }) }
    finally { setBusy(false) }
  }

  const doImport = async () => {
    if (!window.ftn?.selectFile) { setMsg({ type: 'error', text: '当前非 Electron 环境，无法选择文件' }); return }
    setBusy(true); setMsg(null)
    try {
      const pick = await window.ftn.selectFile()
      if (pick?.canceled || !pick.path) return
      const rd = await window.ftn.readTextFile(pick.path)
      if (!rd?.ok) { setMsg({ type: 'error', text: `读取文件失败: ${rd?.error || ''}` }); return }
      const data = JSON.parse(rd.content)
      if (!window.confirm('导入将覆盖当前 配置 / 引擎注册 / 模型索引，是否继续？')) return
      const r = await backendApi.dataImport(data)
      setMsg({ type: r?.ok ? 'ok' : 'error', text: r?.msg || '导入失败' })
      if (r?.ok) setTimeout(() => window.location.reload(), 800)
    } catch (e) { setMsg({ type: 'error', text: `导入失败: ${e.message}` }) }
    finally { setBusy(false) }
  }

  return (
    <section className="rounded-xl border border-base-border bg-base-surface p-5">
      <h2 className="font-semibold text-txt-secondary mb-1">数据管理</h2>
      <p className="text-xs text-txt-muted mb-4">
        导出 / 导入 配置、引擎注册与模型索引，便于换机迁移或备份。模型文件本身不打包，只迁移索引与设置；
        <b>导出文件会自动隐去 API 凭据</b>，请勿随意分享。
      </p>
      <div className="flex gap-2">
        <button onClick={doExport} disabled={busy}
          className="px-4 py-2 rounded-lg border border-accent/40 text-accent text-sm hover:bg-accent-soft disabled:opacity-40">导出数据</button>
        <button onClick={doImport} disabled={busy}
          className="px-4 py-2 rounded-lg border border-base-border text-sm hover:bg-base-surface-2 disabled:opacity-40">导入数据</button>
      </div>
      {msg && (
        <div className={`mt-3 px-3 py-2 rounded-lg text-sm ${msg.type === 'ok' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
          {msg.text}
        </div>
      )}
    </section>
  )
}
