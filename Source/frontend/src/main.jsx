import React from 'react'
import { createRoot } from 'react-dom/client'
import './styles/global.css'
import App from './App.jsx'
import { AppProvider } from './state/AppContext'
import StartupCheck from './pages/StartupCheck'

// ============================================
// FTN Studio 前端入口
// 挂载 App + 全局词法错误边界（页面崩坏时不白屏，给出可恢复 UI）
// ============================================

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, message: '' }
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, message: String(error?.message || error) }
  }
  componentDidCatch(error, info) {
    console.error('[FTN] 前端运行时错误：', error, info)
  }
  handleReload = () => {
    this.setState({ hasError: false, message: '' })
    try {
      window.location.reload()
    } catch {
      /* ignore */
    }
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="h-screen flex items-center justify-center bg-base-bg text-txt-primary">
          <div className="text-center max-w-md px-6">
            <div className="text-3xl mb-3">⚠ 界面发生错误</div>
            <p className="text-sm text-txt-muted mb-4 break-all">{this.state.message}</p>
            <button
              onClick={this.handleReload}
              className="px-5 py-2.5 rounded-lg text-white text-sm font-medium"
              style={{ background: 'var(--color-accent)' }}
            >
              重新加载
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

// 独立启动自检小窗（?view=startup）与主窗口（?main=1 / 普通访问）分流渲染
const urlParams = new URLSearchParams(window.location.search)
const isStartupWindow = urlParams.get('view') === 'startup'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AppProvider>
      <ErrorBoundary>
        {isStartupWindow ? <StartupCheck /> : <App />}
      </ErrorBoundary>
    </AppProvider>
  </React.StrictMode>
)
