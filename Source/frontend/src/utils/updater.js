// ============================================
// 统一「在线更新」流程：下载更新包 → 轮询进度 → 交给 Electron 应用替换并重启。
// 设置页与启动自检弹窗共用同一实现，保证两个入口行为完全一致。
// ============================================
import { backendApi } from '../services/apiClient'

const POLL_INTERVAL = 1200

/**
 * 开始一次完整更新。
 * @param {object} opts
 * @param {(phase: string, pct: number|null, msg: string) => void} opts.onProgress
 * @param {(err: string) => void} opts.onError
 * @param {string} [opts.assetUrl] 最近一次检测到的更新包下载 URL（复用结果，避免重复请求 GitHub）
 * @param {string} [opts.expectedVersion] 最近一次检测到的最新版本号
 * @returns {Promise<boolean>} 是否已进入「应用更新」阶段（程序即将替换并重启）
 */
export async function startUpdate({ onProgress, onError, assetUrl, expectedVersion }) {
  try {
    onProgress('preparing', 0, '正在启动更新…')
    const r = await backendApi.updateDownload({ asset_url: assetUrl, expected_version: expectedVersion })
    if (!r?.ok) {
      onError(r?.msg || '下载启动失败')
      return false
    }
    const taskId = r.task_id
    const dest = r.dest
    onProgress('downloading', 1, '正在下载更新包…')
    // 轮询下载任务（下载失败绝不进入应用阶段）
    while (true) {
      const s = await backendApi.versionsDownloadStatus(taskId)
      if (!s) {
        onError('读取下载进度失败')
        return false
      }
      if (s.status === 'error') {
        onError(s.error || '下载失败')
        return false
      }
      if (s.status === 'done') break
      const last = (s.log || []).slice(-1)[0] || ''
      const pct = Math.round(s.progress || 0)
      onProgress('downloading', pct, `${last}（${pct}%）`)
      await new Promise((res) => setTimeout(res, POLL_INTERVAL))
    }
    // 下载完成 → 应用更新（Electron 备份旧程序 → 替换 → 校验 → 重启）
    onProgress('applying', 95, '下载完成，正在应用更新…')
    const applied = await window.ftn?.applyUpdate?.(dest)
    if (applied && !applied.ok) {
      onError(applied.msg || '应用更新失败')
      return false
    }
    onProgress('restarting', 100, '更新完成，程序即将重启…')
    return true
  } catch (e) {
    onError(`更新失败：${e.message}`)
    return false
  }
}
