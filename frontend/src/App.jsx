import './App.css'
import { useMemo, useState } from 'react'
import ChatOpsPage from './pages/ChatOpsPage'
import RCAPage from './pages/RCAPage'
import PredictPage from './pages/PredictPage'

function App() {
  const tabs = useMemo(
    () => [
      { key: 'chatops', title: 'ChatOps 查询' },
      { key: 'rca', title: 'RCA 根因定位' },
      { key: 'predict', title: '风险预测' }
    ],
    []
  )
  const [active, setActive] = useState('chatops')

  return (
    <div className="appShell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brandMark" />
          <div className="brandText">
            <div className="brandTitle">AI Log Agent</div>
            <div className="brandSub">Loki + LangChain</div>
          </div>
        </div>

        <nav className="nav">
          {tabs.map((t) => (
            <button
              key={t.key}
              className={t.key === active ? 'navItem navItemActive' : 'navItem'}
              onClick={() => setActive(t.key)}
              type="button"
            >
              {t.title}
            </button>
          ))}
        </nav>

        <div className="sidebarFooter">
          <div className="hint">默认请求入口：`/api/*`</div>
          <div className="hint">建议在集群内用Ingress统一入口</div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="topbarTitle">
            {tabs.find((t) => t.key === active)?.title ?? ''}
          </div>
        </header>

        <section className="content">
          {active === 'chatops' && <ChatOpsPage />}
          {active === 'rca' && <RCAPage />}
          {active === 'predict' && <PredictPage />}
        </section>
      </main>
    </div>
  )
}

export default App
