import React from 'react'

// ============================================
// 纯线条风格图标库（Outline / Linear Style）
//
// 设计要点：
// - 内联 SVG，`stroke="currentColor"`，颜色跟随文本（CSS 变量）
//   因此主题切换（html.dark 改变 --color-text-*）时图标自动变色
// - `fill="none"`，圆角端点/连接，线条纤细，营造高级感
// - 统一 24x24 viewBox、stroke-width 1.6、round 线帽
// ============================================

const stroke = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
}

function Svg({ children, ...props }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="1em"
      height="1em"
      aria-hidden="true"
      {...stroke}
      {...props}
    >
      {children}
    </svg>
  )
}

// 首页（房子+烟囱）
export function IconHome(props) {
  return (
    <Svg {...props}>
      <path d="M3 9.5 12 3l9 6.5" />
      <path d="M5 8.5V21h14V8.5" />
    </Svg>
  )
}

// 模型（双图层/卡片）
export function IconModels(props) {
  return (
    <Svg {...props}>
      <path d="M4 8.5 12 4l8 4.5v2L12 15l-8-4.5z" />
      <path d="M4 13v6l8 4.5 8-4.5v-6" />
    </Svg>
  )
}

// 设置（调谐滑块 - 现代线条风格，避免齿轮像太阳）
export function IconSettings(props) {
  return (
    <Svg {...props}>
      <path d="M3.5 8h5M12 8h8.5" />
      <circle cx="9.5" cy="8" r="2.2" />
      <path d="M3.5 16h8.5M15.5 16h5" />
      <circle cx="12.5" cy="16" r="2.2" />
    </Svg>
  )
}

// 关于（信息圈）
export function IconAbout(props) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8h.01" />
      <path d="M11 12h1v5h1" />
    </Svg>
  )
}

// 引擎（方块+连接，用于控制状态等）
export function IconEngine(props) {
  return (
    <Svg {...props}>
      <rect x="3.5" y="3.5" width="8" height="8" rx="1.5" />
      <rect x="12.5" y="12.5" width="8" height="8" rx="1.5" />
      <path d="M7.5 11.5v1a2 2 0 0 0 2 2h1" />
      <path d="M16.5 12.5v-1a2 2 0 0 0-2-2h-1" />
    </Svg>
  )
}

// 日志（水平线条）
export function IconLog(props) {
  return (
    <Svg {...props}>
      <path d="M4 5h16M4 12h16M4 19h10" />
    </Svg>
  )
}

// 版本（标签/分支）
export function IconVersions(props) {
  return (
    <Svg {...props}>
      <path d="M4 19V6M4 6h8a4 4 0 0 1 4 4v2" />
      <circle cx="4" cy="19" r="2" />
      <circle cx="16" cy="6" r="2" />
      <circle cx="16" cy="18" r="2" />
      <path d="M16 8v8" />
      <path d="M4 14h10a2 2 0 0 1 2 2" />
    </Svg>
  )
}

// 主题（调色板 / 画笔）
export function IconTheme(props) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3a9 9 0 1 0 0 18c1.5 0 2-1 2-2 0-1-1-1.5-.5-2.5S15 14.5 15 14a2 2 0 0 1 2-2c2 0 2.5.5 3.5 1A9 9 0 0 0 12 3z" />
    </Svg>
  )
}

// 疑难解答（扳手 + 螺丝）
export function IconTool(props) {
  return (
    <Svg {...props}>
      <path d="M14.7 6.3a4.5 4.5 0 0 0-5.6 5.6L4 17l3 3 5.1-5.1a4.5 4.5 0 0 0 5.6-5.6l-2.6 2.6-2-2z" />
    </Svg>
  )
}

// 小工具（网格九宫格）
export function IconWidgets(props) {
  return (
    <Svg {...props}>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1.5" />
    </Svg>
  )
}

// 网络下载（云 + 向下箭头）
export function IconDownload(props) {
  return (
    <Svg {...props}>
      <path d="M4 13a4 4 0 0 1 1.2-7.8A5 5 0 0 1 15 5.5 3.5 3.5 0 0 1 14.5 12H12" />
      <path d="M12 8v9" />
      <path d="m8 13 4 4 4-4" />
    </Svg>
  )
}

export default {
  home: IconHome,
  models: IconModels,
  settings: IconSettings,
  about: IconAbout,
  engine: IconEngine,
  log: IconLog,
  theme: IconTheme,
  tool: IconTool,
  widgets: IconWidgets,
  downloads: IconDownload,
}
