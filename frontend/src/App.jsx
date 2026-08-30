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

import { useEffect, useRef, useState } from 'react'
import HomePage from './pages/HomePage'
import WizardPage from './pages/WizardPage'
import ViewerPage from './pages/ViewerPage'
import HelpModal from './components/HelpModal'
import OnboardingTour, { OnboardingWelcome, UpdateAnnouncement } from './components/OnboardingTour'
import { onToast } from './lib/toast'
import {
  CURRENT_UPDATE,
  TOUR_STEPS,
  areUpdatesDisabled,
  completeTour,
  completeUpdate,
  disableTours,
  disableUpdates,
  isTourComplete,
  isTourDisabled,
  isUpdateSeen,
  resetTours,
} from './lib/onboarding'
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
  const [theme, setTheme] = useState(() => localStorage.getItem('tv_theme') || 'dark')
  const [tour, setTour] = useState(null)
  const [welcomeOpen, setWelcomeOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const autoTourAttempted = useRef(new Set())
  const updatePrompted = useRef(false)
  const [updateOpen, setUpdateOpen] = useState(false)
  const [updateTourOpen, setUpdateTourOpen] = useState(false)

  const activeTab = tabs.find((tab) => tab.key === active)
  const section = activeTab?.key === 'home' ? 'home' : activeTab?.key === 'wizard' ? 'wizard' : 'viewer'

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('tv_theme', theme)
  }, [theme])

  useEffect(() => {
    if (!section || autoTourAttempted.current.has(section) || isTourDisabled() || isTourComplete(section)) return
    const timer = window.setTimeout(() => {
      autoTourAttempted.current.add(section)
      if (section === 'home') setWelcomeOpen(true)
      else setTour(section)
    }, 150)
    return () => window.clearTimeout(timer)
  }, [section])

  useEffect(() => {
    if (!CURRENT_UPDATE || updatePrompted.current || areUpdatesDisabled() || isUpdateSeen(CURRENT_UPDATE)) return
    updatePrompted.current = true
    setUpdateOpen(true)
  }, [])

  const completeCurrentTour = () => {
    if (tour) completeTour(tour)
    setTour(null)
  }

  const skipCurrentTour = () => {
    if (tour) completeTour(tour)
    setTour(null)
  }

  const disableAllTours = () => {
    disableTours()
    setTour(null)
    setWelcomeOpen(false)
  }

  const replayCurrentTour = () => {
    setSettingsOpen(false)
    setWelcomeOpen(false)
    setTour(section)
  }

  const resetAllTours = () => {
    resetTours()
    autoTourAttempted.current.clear()
    setSettingsOpen(false)
  }

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
        <div className="settings-wrap">
          <div className="app-tools">
            <button
              type="button"
              className="app-tool"
              title={theme === 'dark' ? '切換至淺色主題' : '切換至深色主題'}
              onClick={() => setTheme((current) => current === 'dark' ? 'light' : 'dark')}
            >
              {theme === 'dark' ? '☼' : '◐'} <span className="app-tool-label">{theme === 'dark' ? '淺色' : '深色'}</span>
            </button>
            <button type="button" className="app-tool" data-tour="app-help" title="目前頁面的詳細說明" onClick={() => setHelpOpen(true)}>?</button>
            <button
              type="button"
              className={`app-tool ${settingsOpen ? 'on' : ''}`}
              title="導覽設定"
              onClick={() => setSettingsOpen((open) => !open)}
            >⚙</button>
          </div>
          {settingsOpen && (
            <div className="settings-menu">
              <button type="button" onClick={replayCurrentTour}>重新播放目前頁面導覽</button>
              <button type="button" onClick={resetAllTours}>重新啟用全部新手導覽</button>
              <button type="button" onClick={disableAllTours}>關閉所有新手導覽</button>
            </div>
          )}
        </div>
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
      {helpOpen && <HelpModal section={section} onClose={() => setHelpOpen(false)} />}
      {welcomeOpen && (
        <OnboardingWelcome
          onStart={() => {
            setWelcomeOpen(false)
            setTour('home')
          }}
          onDismiss={() => setWelcomeOpen(false)}
          onSkip={() => {
            completeTour('home')
            setWelcomeOpen(false)
          }}
          onDisable={disableAllTours}
        />
      )}
      {tour && (
        <OnboardingTour
          key={tour}
          steps={TOUR_STEPS[tour]}
          onComplete={completeCurrentTour}
          onDismiss={() => setTour(null)}
          onSkip={skipCurrentTour}
          onDisable={disableAllTours}
        />
      )}
      {CURRENT_UPDATE && updateOpen && (
        <UpdateAnnouncement
          update={CURRENT_UPDATE}
          onView={() => {
            completeUpdate(CURRENT_UPDATE)
            setUpdateOpen(false)
            setUpdateTourOpen(true)
          }}
          onSkip={() => {
            completeUpdate(CURRENT_UPDATE)
            setUpdateOpen(false)
          }}
          onDisable={() => {
            disableUpdates()
            setUpdateOpen(false)
          }}
        />
      )}
      {CURRENT_UPDATE && updateTourOpen && (
        <OnboardingTour
          key={`update-${CURRENT_UPDATE.id}`}
          steps={CURRENT_UPDATE.steps}
          onComplete={() => setUpdateTourOpen(false)}
          onDismiss={() => setUpdateTourOpen(false)}
          onSkip={() => setUpdateTourOpen(false)}
          onDisable={() => {
            disableUpdates()
            setUpdateTourOpen(false)
          }}
        />
      )}
    </div>
  )
}
