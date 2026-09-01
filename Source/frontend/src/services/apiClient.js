// ============================================
// FTN Studio 前后端 HTTP API 客户端
// 所有 REST 调用集中在这里，后续模块统一使用
// ============================================
import { BACKEND_URL } from '../state/AppContext'

async function request(path, options = {}) {
  const { method = 'GET', body, headers = {}, timeout = 15000 } = options

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)

  try {
    const resp = await fetch(`${BACKEND_URL}${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...headers,
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })

    if (!resp.ok) {
      const errText = await resp.text().catch(() => '')
      throw new Error(`HTTP ${resp.status}: ${errText}`)
    }

    // 处理无内容响应
    const text = await resp.text()
    return text ? JSON.parse(text) : null
  } finally {
    clearTimeout(timer)
  }
}

export const api = {
  get: (path, opts) => request(path, { ...opts, method: 'GET' }),
  post: (path, body, opts) => request(path, { ...opts, method: 'POST', body }),
  put: (path, body, opts) => request(path, { ...opts, method: 'PUT', body }),
  delete: (path, opts) => request(path, { ...opts, method: 'DELETE' }),
}

// 剔除 undefined/null/空串 参数，避免 URL 出现 ?q=undefined 导致后端误过滤
function cleanParams(params) {
  const out = {}
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null && v !== '') out[k] = v
  }
  return out
}

// ============================================
// 具体业务接口
// ============================================
export const backendApi = {
  // ===== 系统信息 =====
  health: () => api.get('/api/health'),
  systemInfo: () => api.get('/api/system'),
  systemGpu: () => api.get('/api/system/gpu'),
  systemEnv: () => api.get('/api/system/env'),
  // ===== 启动自检 / 修复 / 更新检测 =====
  selfcheckRun: () => api.get('/api/selfcheck/run'),
  selfcheckStart: () => api.post('/api/selfcheck/start'),
  selfcheckStatus: (taskId) => api.get(`/api/selfcheck/status/${encodeURIComponent(taskId)}`),
  selfcheckFix: (key) => api.post('/api/selfcheck/fix', { key }),
  selfcheckUpdate: () => api.get('/api/selfcheck/update'),
  updateDownload: (payload) => api.post('/api/update/download', payload || {}),
  // ===== 网络下载（CivitAI / HuggingFace）=====
  downloadSources: () => api.get('/api/downloads/sources'),
  civitaiSearch: (query, type, limit) => api.get(`/api/downloads/civitai/search?${new URLSearchParams({ query: query || '', type: type || '', limit: String(limit || 24) }).toString()}`),
  hfSearch: (query, limit) => api.get(`/api/downloads/hf/search?${new URLSearchParams({ query: query || '', limit: String(limit || 24) }).toString()}`),
  hfFiles: (repo) => api.get(`/api/downloads/hf/files?${new URLSearchParams({ repo: repo || '' }).toString()}`),
  downloadStart: (source, url, filename, type) => api.post('/api/downloads/start', { source, url, filename, type }),
  downloadStatus: (taskId) => api.get(`/api/downloads/status/${taskId}`),

  // 获取当前运行状态
  status: () => api.get('/api/status'),

  // ===== M1 新增 =====
  // 配置
  getConfig: () => api.get('/api/config'),
  updateConfig: (payload) => api.put('/api/config', payload),
  resetConfig: () => api.post('/api/config/reset'),
  // 统计
  stats: () => api.get('/api/stats'),
  // 日志
  recentLogs: (params) => api.get(`/api/logs/recent?${new URLSearchParams(params || {}).toString()}`),
  logsSources: () => api.get('/api/logs/sources'),
  logsFile: (category, lines) => api.get(`/api/logs/file?${new URLSearchParams({ category, lines: String(lines || 500) }).toString()}`),
  troubleshootLogs: () => api.get('/api/logs/troubleshoot'),

  // ===== M2 新增：引擎控制 =====
  engineStatus: () => api.get('/api/engine/status'),
  engineStart: (engine = 'reforge') => api.post(`/api/engine/start?${new URLSearchParams({ engine }).toString()}`),
  engineStop: (engine) => api.post(`/api/engine/stop?${engine ? new URLSearchParams({ engine }).toString() : ''}`),
  engineStopAll: () => api.post('/api/engine/stop-all'),
  engineStats: () => api.get('/api/engine/stats'),
  engineDiagnose: () => api.get('/api/engine/diagnose'),

  // ===== M4 新增：模型资产管理 =====
  modelsStats: () => api.get('/api/models/stats'),
  modelsList: (params) => api.get(`/api/models?${new URLSearchParams(cleanParams(params)).toString()}`),
  modelsScan: (params) => api.post(`/api/models/scan?${new URLSearchParams(cleanParams(params)).toString()}`),
  modelLoraDetail: (id) => api.get(`/api/models/${encodeURIComponent(id)}/lora`),
  modelLoraOverride: (id, payload) => api.post(`/api/models/${encodeURIComponent(id)}/lora/override`, payload),
  modelDir: (id) => api.get(`/api/models/${encodeURIComponent(id)}/dir`),
  modelsAdd: (paths, type) => api.post('/api/models/add', { paths, type }),

  // ===== M5 新增：版本管理 =====
  versionsSnapshot: () => api.get('/api/versions'),
  versionsSetActive: (engineId) => api.post(`/api/versions/active?${new URLSearchParams({ engine_id: engineId }).toString()}`),
  versionsProtected: () => api.get('/api/versions/protected'),
  versionsDownload: (baseKey, version, writeTo) => api.post('/api/versions/download', { base_key: baseKey, version, write_to: writeTo }),
  versionsDownloadStatus: (taskId) => api.get(`/api/versions/download/status/${taskId}`),
  versionsUpdate: (engineId, targetVersion) => api.post(`/api/versions/${encodeURIComponent(engineId)}/update`, { target_version: targetVersion }),
  versionsRollback: (engineId, toVersion) => api.post(`/api/versions/${encodeURIComponent(engineId)}/rollback`, { to_version: toVersion }),
  versionsPreviewSwitch: (engineId) => api.post('/api/versions/preview-switch', { engine_id: engineId }),
  versionsTakeover: (engineId) => api.post('/api/versions/takeover', { engine_id: engineId }),
  versionsManagedUpdate: (engineId, target) => api.post('/api/versions/managed-update', { engine_id: engineId, target }),
  versionsManagedCandidates: (engineId) => api.get(`/api/versions/${encodeURIComponent(engineId)}/managed-candidates`),
  versionsGitCandidates: (engineId) => api.get(`/api/versions/${encodeURIComponent(engineId)}/git-candidates`),
  versionsBind: (engineId, payload) => api.post(`/api/versions/${encodeURIComponent(engineId)}/bind`, payload),
  versionsEnvInstall: (engineId) => api.post(`/api/versions/${encodeURIComponent(engineId)}/env-install`),
  versionsEnvCheck: (engineId) => api.get(`/api/versions/${encodeURIComponent(engineId)}/env-check`),
  pluginsList: () => api.get('/api/plugins'),
  pluginSetEnabled: (key, enabled) => api.post(`/api/plugins/${encodeURIComponent(key)}/enabled`, { enabled }),
  pluginUpdateAll: () => api.post('/api/plugins/update-all'),
  pluginTaskStatus: (taskId) => api.get(`/api/plugins/task/${encodeURIComponent(taskId)}`),

  // ===== 基底管理 / 版本下载 =====
  basesSnapshot: () => api.get('/api/bases'),
  basesDownloadInfo: (baseKey) => api.get(`/api/bases/${encodeURIComponent(baseKey)}/download`),
  basesDownloadCandidates: (baseKey) => api.get(`/api/bases/${encodeURIComponent(baseKey)}/candidates`),
  enginePrimaryHealth: () => api.get('/api/engine/primary-health'),
  quickFolders: () => api.get('/api/quickfolders'),
  quickFoldersUpdate: (folders) => api.put('/api/quickfolders', { folders }),

  // ===== M7 新增：引擎注册表 =====
  enginesList: () => api.get('/api/engines'),
  enginesAdd: (payload) => api.post('/api/engines', payload),
  enginesDetect: (payload) => api.post('/api/engines/detect', payload),
  changelog: () => api.get('/api/changelog'),
  enginesRemove: (key) => api.delete(`/api/engines/${key}`),
  enginesRename: (key, label) => api.post(`/api/engines/${key}/rename`, { label }),
  enginesSetPath: (key, root) => api.post(`/api/engines/${key}/path`, { root }),
  enginesClearPath: (key) => api.post(`/api/engines/${key}/path/clear`),
  enginesSetPrimary: (key) => api.post(`/api/engines/${key}/primary`),
  enginesSetEntry: (key, entry) => api.post(`/api/engines/${key}/entry`, { entry }),
  enginesReDetectEntry: (key) => api.post(`/api/engines/${key}/entry/redetect`),

  // ===== 插件市场（下载/更新/URL安装/卸载） =====
  pluginMarket: (params) => api.get(`/api/plugins/market?${new URLSearchParams(params || {}).toString()}`),
  pluginInstall: (repoUrl, key) => api.post('/api/plugins/install', { repo_url: repoUrl, key }, { timeout: 120000 }),
  pluginUpdate: (key) => api.post('/api/plugins/update', { key }, { timeout: 120000 }),
  pluginUninstall: (key) => api.post('/api/plugins/uninstall', { key }),
  pluginUrlInstall: (repoUrl, key) => api.post('/api/plugins/url-install', { repo_url: repoUrl, key }, { timeout: 120000 }),

  // ===== 输出目录自动整理（不分日期） =====
  outputsAutoOrganize: () => api.get('/api/outputs/auto-organize'),
  outputsSetAutoOrganize: (enabled) => api.post('/api/outputs/auto-organize', { enabled }),
  outputsOrganizeNow: () => api.post('/api/outputs/organize-now'),

  // ===== 数据迁移（配置 / 引擎注册 / 模型索引）=====
  dataExport: () => api.get('/api/data/export'),
  dataImport: (data) => api.post('/api/data/import', { data }),

  // ===== 控制台多窗口 / CMD 多开 =====
  consoleSessions: () => api.get('/api/console/sessions'),
  consoleSessionStop: (sid) => api.post(`/api/console/sessions/${encodeURIComponent(sid)}/stop`),
}
