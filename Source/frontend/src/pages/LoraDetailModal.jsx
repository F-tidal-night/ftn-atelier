import React, { useEffect, useState } from 'react'
import { backendApi } from '../services/apiClient'

// LoRA 详情弹窗
// 数据来自后端统一 LoraMetadata（SafetensorsMetadataProvider + 手动覆盖合并）。
// 展示：触发词 / 基底（手动 + 重读）/ 推荐权重 / 自定义备注，并支持保存手动覆盖。
// 训练 tag / 训练信息 / 架构 不再自动检测展示，由用户自行备注。
export default function LoraDetailModal({ model, onClose, onSaved }) {
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [saved, setSaved] = useState(null)   // 保存结果提示
  // 可编辑覆盖字段（受控）
  const [srcBase, setSrcBase] = useState('')   // safetensors 原始基底（重读回退用）
  const [base, setBase] = useState('')
  const [weight, setWeight] = useState('')
  const [words, setWords] = useState('')       // 触发词（逗号分隔）
  const [notes, setNotes] = useState('')

  const load = async () => {
    setLoading(true); setErr(null)
    try {
      const r = await backendApi.modelLoraDetail(model.id)
      if (!r.ok) { setErr(r.msg || '加载失败'); return }
      const lora = r.lora
      setDetail(lora)
      const src = lora.override?.raw_base ?? (lora.override ? null : lora.base_model)
      setSrcBase(lora.base_model || '')
      setBase(lora.base_model || '')
      setWeight(lora.recommended_weight != null ? String(lora.recommended_weight) : '')
      setWords(lora.override?.trigger_words?.join(', ') || '')
      setNotes(lora.custom_notes || '')
    } catch (e) { setErr(e.message) } finally { setLoading(false) }
  }

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [model.id])

  const save = async () => {
    setSaved(null)
    try {
      const r = await backendApi.modelLoraOverride(model.id, {
        base_model: base.trim(),
        recommended_weight: weight === '' ? null : parseFloat(weight),
        trigger_words: words.split(/[,，]/).map((x) => x.trim()).filter(Boolean),
        custom_notes: notes,
      })
      if (!r.ok) { setErr(r.msg || '保存失败'); return }
      setDetail(r.lora)
      setSaved('已保存')
      onSaved && onSaved()
    } catch (e) { setErr(e.message) }
  }

  // 基底重读：回到 safetensors 读取的原始值
  const rereadBase = () => {
    setBase(srcBase)
    setErr(null)
    setSaved('已重读基底为 safetensors 原始值（记得点击保存生效）')
  }

  const lora = detail

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-2xl border border-base-border bg-base-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-base-border">
          <div>
            <h2 className="text-lg font-bold flex items-center gap-2">
              <span>🧩</span>
              {lora?.title_name || model.name}
            </h2>
            {lora?.asset?.type_label && (
              <span className="text-xs text-txt-muted mt-0.5">
                {lora.asset.type_label} · {lora.can_read_safetensors ? '已读取 safetensors metadata' : '索引信息（无 safetensors 元数据）'}
              </span>
            )}
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-lg border border-base-border hover:bg-base-surface-2 text-txt-muted">✕</button>
        </div>

        {loading ? (
          <div className="p-10 text-center text-txt-muted text-sm">加载 LoRA 详情...</div>
        ) : err && !lora ? (
          <div className="p-10 text-center text-red-400 text-sm">{err}</div>
        ) : (
          <div className="grid md:grid-cols-5 gap-0 md:gap-6">
            {/* 左：预览图 */}
            <div className="md:col-span-2 p-5 md:pl-6">
              <div className="aspect-square rounded-xl bg-base-surface-2 border border-base-border overflow-hidden flex items-center justify-center">
                {lora?.preview_path && !lora.preview_path.startsWith('demo://') ? (
                  <img src={`file://${lora.preview_path.replace(/\\/g, '/')}`} className="w-full h-full object-cover" alt="" />
                ) : (
                  <span className="text-6xl opacity-40">🎨</span>
                )}
              </div>
              <div className="mt-3 space-y-1 text-xs text-txt-muted break-all font-mono">
                <p className="p-2 rounded-lg bg-base-surface-2">{lora?.file_path}</p>
              </div>
            </div>

            {/* 右：字段 */}
            <div className="md:col-span-3 p-5 md:pr-6 space-y-4">
              {/* 触发词 */}
              <div className="rounded-xl border border-base-border p-3.5">
                <label className="block text-sm font-semibold mb-2">触发词 Trigger Words</label>
                <input value={words} onChange={(e) => setWords(e.target.value)} placeholder="逗号分隔，如：1girl, detailed"
                  className="w-full px-3 py-2 rounded-lg bg-base-surface-2 border border-base-border text-sm focus:outline-none focus:border-accent" />
              </div>

              {/* 基底（读取 + 手动 + 重读） */}
              <div className="rounded-xl border border-base-border p-3.5">
                <label className="block text-sm font-semibold mb-2">训练基底 Base Model</label>
                <div className="flex gap-2">
                  <input value={base} onChange={(e) => setBase(e.target.value)} placeholder="如 SD 1.5 / SDXL"
                    className="flex-1 px-3 py-2 rounded-lg bg-base-surface-2 border border-base-border text-sm focus:outline-none focus:border-accent" />
                  <button onClick={rereadBase} title="重读 safetensors 原始基底" disabled={!lora?.can_read_safetensors}
                    className="shrink-0 px-3 py-2 rounded-lg border border-base-border text-sm hover:bg-base-surface-2 disabled:opacity-40">重读</button>
                </div>
              </div>

              {/* 推荐权重 */}
              <div className="rounded-xl border border-base-border p-3.5">
                <label className="block text-sm font-semibold mb-2">推荐权重 Recommended Weight</label>
                <input value={weight} onChange={(e) => setWeight(e.target.value)} placeholder="如 0.7"
                  className="w-32 px-3 py-2 rounded-lg bg-base-surface-2 border border-base-border text-sm focus:outline-none focus:border-accent" />
              </div>

              {/* 备注 */}
              <div className="rounded-xl border border-base-border p-3.5">
                <label className="block text-sm font-semibold mb-2">自定义备注</label>
                <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} placeholder="记录使用心得、搭配等..."
                  className="w-full px-3 py-2 rounded-lg bg-base-surface-2 border border-base-border text-sm focus:outline-none focus:border-accent resize-none" />
              </div>
            </div>
          </div>
        )}

        {/* 底部操作 */}
        <div className="px-6 py-4 border-t border-base-border flex items-center justify-between">
          <div className="text-sm">
            {err && <span className="text-red-400">{err}</span>}
            {saved && <span className="text-emerald-400">{saved}</span>}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onClose} className="px-4 py-2 rounded-lg border border-base-border text-sm hover:bg-base-surface-2">关闭</button>
            <button onClick={save} className="px-5 py-2 rounded-lg text-white text-sm font-medium" style={{ background: 'var(--color-accent)' }}>保存覆盖</button>
          </div>
        </div>
      </div>
    </div>
  )
}

function Info({ k, v }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-txt-muted">{k}</span>
      <span className="text-txt-primary text-right">{v}</span>
    </div>
  )
}
