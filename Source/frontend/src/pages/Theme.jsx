import React, { useEffect, useState, useRef } from 'react'
import { THEMES, THEME_BY_MODE, DEFAULT_THEME } from '../themes'
import { useApp } from '../state/AppContext'
import { backendApi } from '../services/apiClient'
import { BACKEND_URL } from '../state/AppContext'

// 头图预览地址（带版本号参数，裁切/更换后强制刷新，避免同 URL 不重新请求）
function heroSrc(path, ver = 0) {
  if (!path) return null
  if (path.startsWith('http')) return path
  return `${BACKEND_URL}/api/hero?t=${ver}`
}

// 外观动画可选效果
const AMBIENT_OPTIONS = [
  { value: 'none', label: '无', desc: '不启用背景动画' },
  { value: 'particles', label: '粒子', desc: '主色光点缓慢漂浮' },
  { value: 'light', label: '光效', desc: '柔光斑流动呼吸' },
  { value: 'breath', label: '呼吸', desc: '背景明暗柔和脉动' },
]

export default function Theme() {
  const { theme, setTheme, setAmbientEffect } = useApp()
  const [mode, setMode] = useState(theme.split('-')[0] || 'dark')
  const [saved, setSaved] = useState(false)
  const [config, setConfig] = useState(null)
  const [hero, setHero] = useState(null)
  const [heroVer, setHeroVer] = useState(0)      // 头图版本号（每次保存 +1，用于刷新预览）
  const [heroMsg, setHeroMsg] = useState(null)   // 头图保存/压缩提示
  const [cropSrc, setCropSrc] = useState(null)   // 待裁剪的图片 dataURL
  const [ambient, setAmbient] = useState('none')
  const [busy, setBusy] = useState(false)

  const loadConfig = async () => {
    try {
      const cfg = await backendApi.getConfig()
      setConfig(cfg)
      setHero(cfg?.preference?.hero_image || null)
      const eff = cfg?.preference?.ambient_effect || 'none'
      setAmbient(eff)
      setAmbientEffect(eff)
    } catch { /* ignore */ }
  }
  useEffect(() => { loadConfig() }, [])

  const pickAmbient = async (val) => {
    setAmbient(val)
    setAmbientEffect(val)
    try {
      const cfg = await backendApi.getConfig()
      cfg.preference = { ...cfg.preference, ambient_effect: val }
      await backendApi.updateConfig(cfg)
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    } catch { /* 后端离线仍本地生效 */ }
  }

  const applyAndSave = async (id) => {
    setTheme(id)
    try {
      const cfg = await backendApi.getConfig()
      cfg.preference = { ...cfg.preference, theme: id }
      await backendApi.updateConfig(cfg)
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    } catch { /* 后端离线仍本地生效 */ }
  }

  const pickHero = async () => {
    if (!window.ftn?.selectImage) {
      const p = window.prompt('输入头图文件路径：', hero || '')
      if (p) setHeroPath(p)
      return
    }
    const res = await window.ftn.selectImage()
    if (!res || res.canceled || !res.path) return
    setBusy(true)
    setHeroMsg(null)
    try {
      // 先弹出裁剪框：用户自选区域（4:1 头图比例）
      if (window.ftn?.readImageDataUrl) {
        const rd = await window.ftn.readImageDataUrl(res.path)
        if (rd?.ok) { setCropSrc(rd.dataUrl); return }
        setHeroMsg(`图片读取失败（${rd?.error || '未知'}），已直接使用原图`)
      }
      await setHeroPath(res.path)
    } finally { setBusy(false) }
  }

  // 裁剪确认：dataURL → 保存 → 写入配置
  const applyCrop = async (dataUrl) => {
    setCropSrc(null)
    setBusy(true)
    setHeroMsg(null)
    try {
      if (window.ftn?.saveHeroData) {
        const s = await window.ftn.saveHeroData(dataUrl)
        if (s?.ok) { await setHeroPath(s.path); setHeroMsg('已保存（已按所选区域裁剪并压缩）'); return }
        setHeroMsg(`保存失败（${s?.error || '未知'}）`)
        return
      }
      setHeroMsg('当前环境不支持保存裁剪图')
    } finally { setBusy(false) }
  }

  const setHeroPath = async (path) => {
    setBusy(true)
    try {
      const cfg = await backendApi.getConfig()
      cfg.preference = { ...cfg.preference, hero_image: path || '' }
      await backendApi.updateConfig(cfg)
      setHero(path || null)
      setHeroVer((v) => v + 1)
    } finally { setBusy(false) }
  }

  return (
    <div className="p-8 max-w-5xl">
      <h1 className="text-2xl font-bold mb-6">外观 · 主题</h1>

      {/* 首图自定义 */}
      <section className="rounded-xl border border-base-border bg-base-surface p-5 mb-6">
        <h2 className="font-semibold text-txt-secondary mb-3">首页头图</h2>
        <div className="rounded-lg h-[300px] mb-3 overflow-hidden relative border border-base-border"
          style={{ background: 'linear-gradient(135deg, var(--color-hero-from), var(--color-hero-to))' }}>
          {hero && (
            <img src={heroSrc(hero, heroVer)} alt="head"
              className="w-full h-full object-cover"
              onError={(e) => { e.currentTarget.style.display = 'none' }} />
          )}
          {!hero && (
            <div className="flex items-center justify-center h-full">
              <span className="text-white/70 text-sm">未设置头图（使用主色渐变）</span>
            </div>
          )}
        </div>
        <div className="flex gap-2">
          <button onClick={pickHero} disabled={busy}
            className="px-4 py-2 rounded-lg text-white text-sm font-medium disabled:opacity-50"
            style={{ background: 'var(--color-accent)' }}>选择图片</button>
          {hero && (
            <button onClick={() => setHeroPath('')} disabled={busy}
              className="px-4 py-2 rounded-lg border border-base-border text-sm text-txt-muted hover:bg-base-surface-2">移除</button>
          )}
          <span className="text-[11px] text-txt-muted self-center ml-1">{hero ? hero.split(/[\\/]/).pop() : '支持 png/jpg/webp'}</span>
        </div>
        {heroMsg && <p className="text-[11px] mt-2 text-emerald-400">{heroMsg}</p>}
      </section>

      {/* 外观动画 */}
      <section className="rounded-xl border border-base-border bg-base-surface p-5 mb-6">
        <h2 className="font-semibold text-txt-secondary mb-3">外观动画</h2>
        <p className="text-xs text-txt-muted mb-4">在内容背后渲染一层轻量环境动画（随主色同色）。窗口切换为非活动状态时自动暂停，避免占用资源。</p>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {AMBIENT_OPTIONS.map((opt) => (
            <button key={opt.value} onClick={() => pickAmbient(opt.value)}
              className="rounded-lg border p-4 text-left transition-colors"
              style={{
                borderColor: ambient === opt.value ? 'var(--color-accent)' : 'var(--color-border)',
                background: ambient === opt.value ? 'var(--color-accent-soft)' : 'var(--color-surface)',
              }}>
              <div className="text-sm font-medium" style={{ color: ambient === opt.value ? 'var(--color-accent)' : 'var(--color-text-primary)' }}>
                {opt.label}
                {ambient === opt.value && <span className="ml-1.5 text-[10px]">✓</span>}
              </div>
              <div className="text-[11px] text-txt-muted mt-1">{opt.desc}</div>
            </button>
          ))}
        </div>
      </section>

      {/* 明暗切换 */}
      <div className="flex gap-2 mb-5">
        {['dark', 'light'].map((m) => (
          <button key={m} onClick={() => setMode(m)}
            className="px-4 py-2 rounded-lg border text-sm"
            style={{
              borderColor: mode === m ? 'var(--color-accent)' : 'var(--color-border)',
              color: mode === m ? 'var(--color-accent)' : 'var(--color-text-secondary)',
              background: mode === m ? 'var(--color-accent-soft)' : 'transparent',
            }}>
            {m === 'dark' ? '深色' : '浅色'}
          </button>
        ))}
      </div>

      {/* 该模式下的主色主题卡片 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {THEME_BY_MODE[mode].map((t) => {
          const active = theme === t.id
          return (
            <button key={t.id} onClick={() => applyAndSave(t.id)}
              className="rounded-xl border p-4 text-left transition-shadow hover:shadow-md"
              style={{
                borderColor: active ? 'var(--color-accent)' : 'var(--color-border)',
                background: 'var(--color-surface)',
                boxShadow: active ? `0 0 0 1px var(--color-accent)` : 'none',
              }}>
              <div className="rounded-lg h-20 mb-3 flex"
                style={{ background: `linear-gradient(135deg, ${t.colors['--color-accent']}, ${t.colors['--color-bg']})` }}>
                <div className="w-1/2 h-full rounded-l-lg" style={{ background: t.colors['--color-surface'] }} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>{t.label} · {mode === 'dark' ? '深' : '浅'}</span>
                {active && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'var(--color-accent-soft)', color: 'var(--color-accent)' }}>✓ 使用中</span>
                )}
              </div>
            </button>
          )
        })}
      </div>

      {saved && <p className="mt-4 text-sm text-accent">主题已保存 ✓</p>}

      {/* 头图裁剪弹窗 */}
      {cropSrc && (
        <HeroCropModal
          src={cropSrc}
          onCancel={() => { setCropSrc(null); setHeroMsg(null) }}
          onConfirm={applyCrop}
        />
      )}
    </div>
  )
}

// ============================================
// 头图裁剪（常见交互：拖动定位 + 右下角等比缩放，固定 4:1 头图比例）
// ============================================
function HeroCropModal({ src, onCancel, onConfirm }) {
  const imgRef = useRef(null)
  const [nat, setNat] = useState({ w: 0, h: 0 })
  const [disp, setDisp] = useState({ w: 0, h: 0 })
  const [crop, setCrop] = useState(null)
  const dragRef = useRef(null)
  const ASPECT = 4 / 1

  const onLoad = () => {
    const el = imgRef.current
    if (!el) return
    const iw = el.naturalWidth, ih = el.naturalHeight
    const maxW = Math.min(620, iw), maxH = 400
    const sc = Math.min(maxW / iw, maxH / ih, 1)
    const dw = Math.round(iw * sc), dh = Math.round(ih * sc)
    setNat({ w: iw, h: ih })
    setDisp({ w: dw, h: dh })
    let cw = dw, ch = Math.round(dw / ASPECT)
    if (ch > dh) { ch = dh; cw = Math.round(ch * ASPECT) }
    setCrop({ x: Math.round((dw - cw) / 2), y: Math.round((dh - ch) / 2), w: cw, h: ch })
  }

  const clampCrop = (c) => {
    let { x, y, w, h } = c
    if (w < 40 || h < 10 || !disp.w || !disp.h) return null
    x = Math.max(0, Math.min(x, disp.w - w))
    y = Math.max(0, Math.min(y, disp.h - h))
    return { x, y, w, h }
  }

  const onPointerDown = (e, mode, el) => {
    e.preventDefault()
    dragRef.current = { mode, sx: e.clientX, sy: e.clientY, oc: { ...crop } }
    const move = (ev) => {
      const d = dragRef.current
      if (!d || !crop) return
      const dx = ev.clientX - d.sx, dy = ev.clientY - d.sy
      if (d.mode === 'move') {
        setCrop(clampCrop({ ...d.oc, x: d.oc.x + dx, y: d.oc.y + dy }))
      } else {
        let nw = Math.max(60, d.oc.w + dx)
        let nh = Math.round(nw / ASPECT)
        if (nh > disp.h) { nh = disp.h; nw = Math.round(nh * ASPECT) }
        setCrop(clampCrop({
          x: Math.min(d.oc.x, disp.w - nw),
          y: Math.min(d.oc.y, disp.h - nh),
          w: nw, h: nh,
        }))
      }
    }
    const up = () => {
      dragRef.current = null
      el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerup', up)
    }
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerup', up)
  }

  const confirm = () => {
    if (!crop || !nat.w || !disp.w || !imgRef.current) return
    const k = nat.w / disp.w
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(crop.w * k)
    canvas.height = Math.round(crop.h * k)
    const ctx = canvas.getContext('2d')
    ctx.fillStyle = '#ffffff'   // 透明 PNG 导出 JPEG 时垫白底，避免黑底
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(
      imgRef.current,
      crop.x * k, crop.y * k, crop.w * k, crop.h * k,
      0, 0, canvas.width, canvas.height,
    )
    onConfirm(canvas.toDataURL('image/jpeg', 0.9))
  }

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/70 p-6" onClick={onCancel}>
      <div className="w-full max-w-2xl rounded-2xl border border-base-border bg-base-surface shadow-2xl p-5 flex flex-col"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-bold">裁剪头图</h2>
          <span className="text-xs text-txt-muted">拖动定位 · 右下角缩放（4:1 头图比例）</span>
          <button onClick={onCancel} className="w-8 h-8 rounded-lg border border-base-border text-txt-muted hover:bg-base-surface-2">✕</button>
        </div>
        <div className="relative mx-auto select-none" style={{ width: disp.w || '100%', height: disp.h || 320, touchAction: 'none' }}>
          {src && (
            <img ref={imgRef} src={src} alt="crop"
              onLoad={onLoad}
              className="absolute inset-0 max-w-none"
              style={{ width: disp.w || 'auto', height: disp.h || 'auto' }} draggable={false} />
          )}
          {crop && (
            <>
              {/* 四边暗化（只压暗裁剪框外，不再用 9999px 大阴影压暗整个弹窗） */}
              <div className="absolute bg-black/55 pointer-events-none" style={{ left: 0, top: 0, width: disp.w, height: crop.y }} />
              <div className="absolute bg-black/55 pointer-events-none" style={{ left: 0, top: crop.y, width: crop.x, height: crop.h }} />
              <div className="absolute bg-black/55 pointer-events-none" style={{ left: crop.x + crop.w, top: crop.y, width: Math.max(0, disp.w - crop.x - crop.w), height: crop.h }} />
              <div className="absolute bg-black/55 pointer-events-none" style={{ left: 0, top: crop.y + crop.h, width: disp.w, height: Math.max(0, disp.h - crop.y - crop.h) }} />
              <div className="absolute border-2 border-accent cursor-move"
                style={{ left: crop.x, top: crop.y, width: crop.w, height: crop.h }}
                onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); onPointerDown(e, 'move', e.currentTarget) }} />
              <div className="absolute w-4 h-4 border-r-2 border-b-2 border-accent cursor-nwse-resize"
                style={{ left: crop.x + crop.w - 4, top: crop.y + crop.h - 4 }}
                onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); onPointerDown(e, 'resize', e.currentTarget) }} />
            </>
          )}
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onCancel} className="px-4 py-2 rounded-lg border border-base-border text-sm">取消</button>
          <button onClick={confirm} disabled={!crop}
            className="px-5 py-2 rounded-lg text-white text-sm font-medium disabled:opacity-40"
            style={{ background: 'var(--color-accent)' }}>确定裁剪</button>
        </div>
      </div>
    </div>
  )
}
