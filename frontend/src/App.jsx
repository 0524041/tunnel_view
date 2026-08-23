// Copyright (C) 2026 willywu <pop2585158@gmail.com>
// SPDX-License-Identifier: GPL-3.0-only
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.

import { useEffect, useState } from 'react'
import HomePage from './pages/HomePage'
import WizardPage from './pages/WizardPage'
import ViewerPage from './pages/ViewerPage'
import { onToast } from './lib/toast'
import './styles/App.css'

function ToastHost() {
  const [items, setItems] = useState([])
  useEffect(
    () =>
      onToast((t) => {
        setItems((xs) => [...xs, t])
        setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== t.id)), 3000)
      }),
    [],
  )
  return (
    <div className="toast-host">
      {items.map((t) => (
        <div key={t.id} className={`toast toast-${t.type}`}>{t.msg}</div>
      ))}
    </div>
  )
}

export default function App() {
  const [tabs, setTabs] = useState([{ key: 'home' }])
  const [active, setActive] = useState('home')

  const openTunnel = (tunnelId, name) => {
    const key = `t${tunnelId}`
    setTabs((ts) => {
      const withoutWizard = ts.filter((t) => t.key !== 'wizard')
      return withoutWizard.some((t) => t.key === key)
        ? withoutWizard.map((t) => (t.key === key ? { ...t, name } : t))
        : [...withoutWizard, { key, tunnelId, name }]
    })
    setActive(key)
  }

  const openWizard = () => {
    const key = 'wizard'
    setTabs((ts) => (ts.some((t) => t.key === key) ? ts : [...ts, { key }]))
    setActive(key)
  }

  const closeWizard = () => {
    setTabs((ts) => ts.filter((t) => t.key !== 'wizard'))
    setActive('home')
  }

  const closeTab = (key) => {
    setTabs((ts) => {
      const next = ts.filter((t) => t.key !== key)
      if (active === key) setActive(next[next.length - 1].key)
      return next
    })
  }

  return (
    <div className="app">
      <div className="tabbar">
        <div className="brand display">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden>
            <path d="M2 21V13C2 7 6.5 3 12 3s10 4 10 10v8h-5v-8a5 5 0 0 0-10 0v8H2z" stroke="var(--amber)" strokeWidth="1.8" />
          </svg>
          TUNNELVIEW
        </div>
        {tabs.map((t) => (
          <div
            key={t.key}
            className={`tab ${active === t.key ? 'on' : ''}`}
            onClick={() => setActive(t.key)}
          >
            <span className="tab-label">{t.key === 'home' ? '總覽' : t.key === 'wizard' ? '建立隧道' : t.name}</span>
            {t.key !== 'home' && (
              <button className="tab-close" onClick={(e) => { e.stopPropagation(); closeTab(t.key) }} aria-label="關閉">×</button>
            )}
          </div>
        ))}
      </div>

      <div className="tab-body">
        {tabs.map((t) => (
          <div key={t.key} style={{ display: active === t.key ? 'flex' : 'none', flex: 1, minHeight: 0 }} className="tab-pane">
            {t.key === 'home' && <HomePage onOpenTunnel={openTunnel} onNewTunnel={openWizard} />}
            {t.key === 'wizard' && <WizardPage onDone={openTunnel} onCancel={closeWizard} />}
            {t.tunnelId != null && (
              <ViewerPage tunnelId={t.tunnelId} active={active === t.key} onTitle={(n) => {
                if (t.name === n) return
                setTabs((ts) => ts.map((x) => (x.key === t.key ? { ...x, name: n } : x)))
              }} />
            )}
          </div>
        ))}
      </div>
      <ToastHost />
    </div>
  )
}
