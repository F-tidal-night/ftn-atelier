// ============================================
// M6+ 主题系统（重做）
// 主色驱动「整个界面」而非仅点缀色：
//   - 每主色含完整调色板（背景/表面/边框/文本/强调）
//   - 亮/暗两模式分别有独立面板色
//   - 切主题时背景、卡片、文字全随主色变化
// 主色：紫 / 粉 / 金 / 蓝 — 粉紫金属偏好系 3:1 普通色，符合 4:6 期望
// ============================================

// 各主色完整调色板（含明暗自变体）
const PALETTES = {
  purple: {
    name: '紫',
    light: { bg: '#f4f1fb', surface: '#ffffff', surface2: '#ece7f7', border: '#e0d8f2',
             text1: '#191526', text2: '#433d58', text3: '#817a95',
             accent: '#7c5cd6', accentHover: '#6a4bc4', accentSoft: '#ece4fb', shadow: 'rgba(124,92,214,.35)' },
    dark:  { bg: '#100d1c', surface: '#1a162b', surface2: '#241e3a', border: '#332a4d',
             text1: '#ece5fb', text2: '#c6bce0', text3: '#8b81a8',
             accent: '#a78bfa', accentHover: '#b9a1ff', accentSoft: '#2a2145', shadow: 'rgba(167,139,250,.45)' },
  },
  pink: {
    name: '粉',
    light: { bg: '#faf0f5', surface: '#fff9fb', surface2: '#f6e2ee', border: '#f0d3e3',
             text1: '#2b1220', text2: '#5a3a4d', text3: '#9a7490',
             accent: '#d94f9f', accentHover: '#c4408c', accentSoft: '#fbe4f1', shadow: 'rgba(217,79,159,.35)' },
    dark:  { bg: '#180d15', surface: '#25152a', surface2: '#301b33', border: '#47233e',
             text1: '#ffecf6', text2: '#e2b8d4', text3: '#a87a96',
             accent: '#f48bc4', accentHover: '#f9a8d4', accentSoft: '#3a1c31', shadow: 'rgba(244,139,196,.45)' },
  },
  gold: {
    name: '金',
    light: { bg: '#faf5e8', surface: '#fffdf6', surface2: '#f4ead3', border: '#eadbbb',
             text1: '#2b2110', text2: '#5c4d2f', text3: '#9c8a5f',
             accent: '#c4942a', accentHover: '#a97d1c', accentSoft: '#f7ebc9', shadow: 'rgba(196,148,42,.35)' },
    dark:  { bg: '#14110a', surface: '#201b11', surface2: '#2c2518', border: '#4a3f28',
             text1: '#f6efdc', text2: '#d4c39a', text3: '#a08e63',
             accent: '#e2b649', accentHover: '#eec95f', accentSoft: '#372d1c', shadow: 'rgba(226,182,73,.45)' },
  },
  blue: {
    name: '蓝',
    light: { bg: '#eef3fb', surface: '#ffffff', surface2: '#e5edf7', border: '#d3e0f0',
             text1: '#111827', text2: '#41506b', text3: '#7e8ca3',
             accent: '#2f6fce', accentHover: '#2560b8', accentSoft: '#e2edfb', shadow: 'rgba(47,111,206,.35)' },
    dark:  { bg: '#0b1220', surface: '#131d30', surface2: '#1b2740', border: '#2c3d5c',
             text1: '#e8f0fb', text2: '#b9c8e2', text3: '#8292b0',
             accent: '#5b9bff', accentHover: '#73aaff', accentSoft: '#1b2a44', shadow: 'rgba(91,155,255,.45)' },
  },
}

// 主题清单
export const THEMES = []
for (const [pk, p] of Object.entries(PALETTES)) {
  for (const mode of ['dark', 'light']) {
    const c = p[mode]
    THEMES.push({
      id: `${mode}-${pk}`,
      label: `${p.name}`,
      mode,
      primaryKey: pk,
      colors: {
        '--color-bg': c.bg,
        '--color-surface': c.surface,
        '--color-surface-2': c.surface2,
        '--color-border': c.border,
        '--color-accent': c.accent,
        '--color-accent-hover': c.accentHover,
        '--color-accent-soft': c.accentSoft,
        '--color-shadow': c.shadow,
        '--color-text-primary': c.text1,
        '--color-text-secondary': c.text2,
        '--color-text-muted': c.text3,
        '--color-hero-from': c.accent,
        '--color-hero-to': c.bg,
      },
    })
  }
}

export const THEME_BY_MODE = {
  dark: THEMES.filter((t) => t.mode === 'dark'),
  light: THEMES.filter((t) => t.mode === 'light'),
}

// 默认主题（暗 · 紫）
export const DEFAULT_THEME = 'dark-purple'

export function getTheme(id) {
  const t = THEMES.find((x) => x.id === id)
  return t || THEMES.find((x) => x.id === DEFAULT_THEME)
}

// 应用主题：一次性批量写入变量 + 平滑过渡
export function applyTheme(id) {
  const theme = getTheme(id)
  if (!theme) return theme
  const root = document.documentElement
  root.style.transition = 'background-color .45s ease'
  requestAnimationFrame(() => {
    for (const [k, v] of Object.entries(theme.colors)) {
      root.style.setProperty(k, v)
    }
    root.classList.toggle('dark', theme.mode === 'dark')
  })
  return theme
}

