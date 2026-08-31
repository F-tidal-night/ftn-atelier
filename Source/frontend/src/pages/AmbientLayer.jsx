import React, { useEffect, useRef } from 'react'

// ============================================
// 外观动画层 AmbientLayer
// 在应用内容背后渲染一层轻量环境动画，可选三种：
//   - particles 粒子漂浮
//   - light     光效流动光斑
//   - breath    背景柔和呼吸（明暗脉动）
// 窗口非活动（Document hidden / 窗口 blur）时自动暂停，避免占用资源。
// 通过 CSS 变量 --color-accent 与当前主题同色。
// ============================================

const EFFECTS = new Set(['particles', 'light', 'breath'])

// 从主题变量取主色（含透明度 alpha，0~1）
function accent(alpha = 1) {
  if (typeof document === 'undefined') return `rgba(167,139,250,${alpha})`
  const v = getComputedStyle(document.documentElement).getPropertyValue('--color-accent').trim()
  // 已是 rgb/rgba
  if (v.startsWith('rgb')) {
    const m = v.match(/[\d.]+/g)
    if (m) return `rgba(${m[0]},${m[1]},${m[2]},${alpha})`
    return v
  }
  return v
}

/**
 * 粒子效果：彩色光点上浮、飘移、闪烁，带柔和光晕。
 */
function useParticles(active, canvasRef, running) {
  useEffect(() => {
    if (!active) return
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    let raf
    let W = 0, H = 0

    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const resize = () => {
      W = canvas.clientWidth; H = canvas.clientHeight
      canvas.width = W * dpr; canvas.height = H * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    window.addEventListener('resize', resize)

    const COUNT = 48
    const parts = Array.from({ length: COUNT }, () => ({
      x: Math.random() * W,
      y: Math.random() * H,
      r: Math.random() * 3.0 + 0.8,
      vx: (Math.random() - 0.5) * 0.34,
      vy: -(Math.random() * 0.38 + 0.08),
      a: Math.random() * 0.5 + 0.3,
      ph: Math.random() * Math.PI * 2,
    }))

    let start = null
    const tick = (t) => {
      if (!start) start = t
      const dt = Math.min((t - start) / 1000, 0.05)
      start = t
      ctx.clearRect(0, 0, W, H)
      if (!running) { raf = requestAnimationFrame(tick); return }  // 非活动：静止但维持渲染
      for (const p of parts) {
        p.x += p.vx * dt * 60
        p.y += p.vy * dt * 60
        if (p.x < 0 || p.x > W) p.vx *= -1
        if (p.y < -10) { p.y = H + 10; p.x = Math.random() * W }
        const twinkle = 0.6 + 0.4 * Math.sin(t / 1400 + p.ph)
        ctx.shadowColor = accent(p.a * twinkle)
        ctx.shadowBlur = 8
        ctx.beginPath()
        ctx.fillStyle = accent(p.a * twinkle)
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
        ctx.fill()
        ctx.shadowBlur = 0
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => { window.removeEventListener('resize', resize); cancelAnimationFrame(raf) }
  }, [active, canvasRef, running])
}

/**
 * 光效：大号柔光斑缓慢漂移、明暗呼吸，类似流动光感（加强可见度）。
 */
function useLights(active, canvasRef, running) {
  useEffect(() => {
    if (!active) return
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    let raf
    let W = 0, H = 0

    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const resize = () => {
      W = canvas.clientWidth; H = canvas.clientHeight
      canvas.width = W * dpr; canvas.height = H * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    window.addEventListener('resize', resize)

    const blobs = Array.from({ length: 4 }, (_, i) => ({
      x: (i + 0.5) * W / 3,
      y: H * (0.35 + 0.3 * (i % 2)),
      r: Math.min(W, H) * (0.34 + i * 0.07),
      vx: (Math.random() - 0.5) * 0.36,
      vy: (Math.random() - 0.5) * 0.24,
      ph: i * 1.7,
      alpha: 0.07 + i * 0.022,
    }))

    let start = null
    const tick = (t) => {
      if (!start) start = t
      const el = (t - start) / 1000
      ctx.clearRect(0, 0, W, H)
      if (running) {
        for (const b of blobs) {
          b.x += Math.sin(el * 0.1 + b.ph) * 0.25
          b.y += Math.cos(el * 0.08 + b.ph) * 0.18
          // 边界软包裹
          if (b.x < -b.r) b.x = W + b.r
          if (b.x > W + b.r) b.x = -b.r
          if (b.y < -b.r) b.y = H + b.r
          if (b.y > H + b.r) b.y = -b.r
        }
      }
      ctx.globalCompositeOperation = 'lighter'
      for (const b of blobs) {
        const breathe = running ? 0.6 + 0.4 * Math.sin(el * 0.6 + b.ph) : 1
        const g = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, b.r)
        g.addColorStop(0, accent(b.alpha * breathe))
        g.addColorStop(1, 'rgba(0,0,0,0)')
        ctx.beginPath()
        ctx.fillStyle = g
        ctx.arc(b.x, b.y, b.r, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.globalCompositeOperation = 'source-over'
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => { window.removeEventListener('resize', resize); cancelAnimationFrame(raf) }
  }, [active, canvasRef, running])
}

export default function AmbientLayer({ effect, running = true }) {
  const canvasRef = useRef(null)

  // 只有对应 effect 才启用对应渲染（避免同 canvas 上两类动画互相覆盖）
  useParticles(effect === 'particles', canvasRef, running)
  useLights(effect === 'light', canvasRef, running)

  // breath：无 canvas，用 CSS 动画实现背景明暗脉动
  const breath = effect === 'breath'

  if (!EFFECTS.has(effect)) return null

  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 z-0 overflow-hidden"
      style={{
        opacity: breath && !running ? 0 : 1,
        transition: 'opacity .4s ease',
      }}
    >
      {breath ? (
        <div
          className="absolute inset-0"
          style={{
            background: 'radial-gradient(ellipse 80% 60% at 50% 22%, var(--color-accent) 0%, transparent 72%)',
            animation: running ? 'ftn-breath 4.5s ease-in-out infinite' : 'none',
          }}
        />
      ) : (
        <canvas ref={canvasRef} className="w-full h-full" style={{ opacity: 0.9 }} />
      )}
      <style>{`
        @keyframes ftn-breath {
          0%, 100% { opacity: 0.12; transform: scale(1); }
          50% { opacity: 0.55; transform: scale(1.08); }
        }
      `}</style>
    </div>
  )
}
