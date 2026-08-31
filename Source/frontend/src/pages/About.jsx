import React, { useEffect, useState } from 'react'
import { backendApi } from '../services/apiClient'

// ============================================
// 关于页：软件信息 / 环境 / 版本
// ============================================

export default function About() {
  const [info, setInfo] = useState(null)
  const [stats, setStats] = useState(null)

  useEffect(() => {
    Promise.allSettled([
      backendApi.systemInfo(),
      backendApi.stats(),
    ]).then(([sys, st]) => {
      setInfo(sys.status === 'fulfilled' ? sys.value : null)
      setStats(st.status === 'fulfilled' ? st.value : null)
    })
  }, [])

  return (
    <div className="p-8 max-w-3xl">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">关于</h1>
        <p className="text-sm text-txt-muted mt-1">FTN Atelier · 生图引擎工作台</p>
      </header>

      {/* 品牌卡 */}
      <div className="rounded-2xl border border-base-border bg-base-surface p-6 mb-6">
        <div className="flex items-center gap-4">
          <div>
            <div className="text-xl font-bold">FTN Atelier</div>
            <div className="text-sm text-txt-muted mt-0.5">生图引擎 · AI 创作工作台</div>
            <div className="text-[11px] text-txt-muted/70 mt-1">Electron · React · FastAPI · SQLite</div>
          </div>
        </div>
        <p className="text-sm text-txt-secondary mt-4 leading-relaxed">
          一键启动与管理生图引擎（兼容 reForge / Forge 等）：引擎启动、模型资产管理、
          LoRA 详情、版本更新回退、插件管理、网络模型下载（CivitAI / HuggingFace）、
          日志与疑难解答。仅面向 Windows，非侵入式管理引擎（不修改其核心源码）。
        </p>
      </div>

      {/* 使用声明 */}
      <div className="rounded-2xl border border-base-border bg-base-surface p-6 mb-6">
        <h2 className="text-base font-semibold mb-3">使用声明</h2>
        <ul className="text-sm text-txt-secondary leading-relaxed space-y-1.5 list-disc pl-5">
          <li>本工具仅用于合法的 AI 创作与学习交流，请遵守所在国家/地区的法律法规。</li>
          <li>禁止将本工具或生成内容用于商业盗版、付费转卖、侵权牟利等行为。</li>
          <li>禁止利用本工具制作、传播或存储色情、赌博、毒品及任何违法违规内容。</li>
          <li>因违规使用产生的一切后果由使用者自行承担。</li>
        </ul>
      </div>

      {/* 环境信息 */}
      {info && (
        <div className="rounded-2xl border border-base-border bg-base-surface p-6 mb-6">
          <h2 className="text-base font-semibold mb-4">运行环境</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
            <InfoRow label="操作系统" value={info.platform} />
            <InfoRow label="架构" value={info.arch} />
            <InfoRow label="Python" value={info.python} />
            <InfoRow label="后端版本" value={info.version} />
          </div>
        </div>
      )}

      {/* 数据库状态 */}
      {stats && (
        <div className="rounded-2xl border border-base-border bg-base-surface p-6 mb-6">
          <h2 className="text-base font-semibold mb-4">数据状态</h2>
          <div className="flex flex-wrap gap-6">
            <StatBox label="模型资产" value={stats.model_count ?? 0} />
            <StatBox label="配置条目" value={stats.meta_count ?? 0} />
            <div className="text-sm text-txt-muted flex items-center">
              <span className="w-2 h-2 rounded-full bg-emerald-400 mr-2" />
              数据库正常（{stats.db}）
            </div>
          </div>
        </div>
      )}

      <div className="text-center text-[11px] text-txt-muted mt-8">
        FTN Studio · 保留所有权利 · 生图引擎工作台 · 非侵入式管理引擎
      </div>
    </div>
  )
}

function InfoRow({ label, value }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="text-txt-muted shrink-0">{label}</span>
      <span className="text-txt-primary text-right break-all">{value || '—'}</span>
    </div>
  )
}

function StatBox({ label, value }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-3xl font-bold text-txt-primary">{(value ?? 0).toLocaleString()}</span>
      <span className="text-xs text-txt-muted">{label}</span>
    </div>
  )
}
