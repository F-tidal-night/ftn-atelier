// ============================================
// FTN Studio Preload 脚本
// 通过 contextBridge 安全暴露 Electron 能力给渲染进程
// ============================================
const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('ftn', {
  // 获取后端信息
  getBackendInfo: () => ipcRenderer.invoke('backend:info'),
  getAppInfo: () => ipcRenderer.invoke('app:info'),
  // 在线更新：应用已下载的更新包 zip（替换程序文件并重启）
  applyUpdate: (zipPath) => ipcRenderer.invoke('update:apply', zipPath),
  // 应用 Logo（ico → dataURL，启动自检小窗 / 关于页统一展示）
  getLogo: () => ipcRenderer.invoke('app:logo'),

  // 打开原生目录选择对话框
  selectDirectory: () => ipcRenderer.invoke('dialog:selectDirectory'),
  // 打开任意文件选择对话框（用于引擎启动文件等）
  selectFile: () => ipcRenderer.invoke('dialog:selectFile'),
  // 打开多选文件对话框（用于「添加模型」剪切式入库）
  selectModelFiles: () => ipcRenderer.invoke('dialog:selectModelFiles'),
  // 打开图片文件选择对话框（用于首页头图）
  selectImage: () => ipcRenderer.invoke('dialog:selectImage'),
  // 打开本地路径（文件夹/文件）
  openPath: (p) => ipcRenderer.invoke('shell:openPath', p),
  // 将内容保存到用户选择的文件（用于日志导出）
  saveTextFile: (defaultName, content) => ipcRenderer.invoke('dialog:saveTextFile', defaultName, content),
  // 读取文本文件（数据导入用）
  readTextFile: (p) => ipcRenderer.invoke('dialog:readTextFile', p),
  // 首页头图：原生压缩后保存（限宽 1920 / JPEG），返回保存路径
  prepareHero: (p) => ipcRenderer.invoke('image:prepareHero', p),
  // 首页头图：读取为 dataURL（裁剪预览用）
  readImageDataUrl: (p) => ipcRenderer.invoke('image:readDataUrl', p),
  // 首页头图：保存裁剪结果（dataURL → JPEG）
  saveHeroData: (dataUrl) => ipcRenderer.invoke('image:saveHeroData', dataUrl),
  // 启动自检独立小窗完成 → 通知主进程显示主窗口
  startupCheckDone: () => ipcRenderer.send('startup-check-done'),

  // 平台信息
  platform: process.platform,
  isElectron: true,
})
