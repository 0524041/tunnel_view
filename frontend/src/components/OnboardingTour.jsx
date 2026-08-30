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

function clamp(value, low, high) {
  return Math.max(low, Math.min(value, high))
}

export function OnboardingWelcome({ onStart, onDismiss, onSkip, onDisable }) {
  return (
    <div className="tour-layer" role="dialog" aria-modal="true" aria-label="歡迎使用 TunnelView">
      <div className="tour-welcome">
        <span className="label">首次使用</span>
        <h2 className="display">歡迎使用 TUNNELVIEW</h2>
        <p>用約一分鐘認識專案整理、匯入照片與多視角檢視的核心流程。</p>
        <div className="tour-actions tour-actions-primary">
          <button type="button" className="btn primary" onClick={onStart}>開始導覽</button>
          <button type="button" className="btn" onClick={onDismiss}>稍後再說</button>
        </div>
        <div className="tour-secondary-actions">
          <button type="button" onClick={onSkip}>跳過總覽介紹</button>
          <button type="button" onClick={onDisable}>我已知道，不再導覽</button>
        </div>
      </div>
    </div>
  )
}

export function UpdateAnnouncement({ update, onView, onSkip, onDisable }) {
  return (
    <div className="tour-layer" role="dialog" aria-modal="true" aria-label={`更新公告：${update.title}`}>
      <div className="tour-welcome">
        <span className="label">重要更新</span>
        <h2 className="display">{update.title}</h2>
        <p>{update.text}</p>
        <div className="tour-actions tour-actions-primary">
          <button type="button" className="btn primary" onClick={onView}>查看新功能</button>
          <button type="button" className="btn" onClick={onSkip}>這次跳過</button>
        </div>
        <div className="tour-secondary-actions">
          <button type="button" onClick={onDisable}>不再顯示更新公告</button>
        </div>
      </div>
    </div>
  )
}

export default function OnboardingTour({ steps, onComplete, onDismiss, onSkip, onDisable }) {
  const [index, setIndex] = useState(0)
  const [rect, setRect] = useState(null)
  const step = steps[index]
  const stepKey = `${step.target}:${step.title}`

  useEffect(() => {
    let detach = null
    let observer = null
    const locate = () => {
      const primaryTarget = document.querySelector(step.target)
      const target = primaryTarget || (step.fallbackTarget && document.querySelector(step.fallbackTarget))
      if (!target) {
        return
      }
      observer?.disconnect()
      target.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' })
      const update = () => {
        const next = target.getBoundingClientRect()
        setRect({ stepKey, fallback: !primaryTarget, top: next.top, left: next.left, width: next.width, height: next.height })
      }
      update()
      window.addEventListener('resize', update)
      window.addEventListener('scroll', update, true)
      detach = () => {
        window.removeEventListener('resize', update)
        window.removeEventListener('scroll', update, true)
      }
    }
    observer = new MutationObserver(locate)
    observer.observe(document.body, { childList: true, subtree: true })
    locate()
    return () => {
      observer.disconnect()
      detach?.()
    }
  }, [step, stepKey])

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') onDismiss()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onDismiss])

  if (!rect || rect.stepKey !== stepKey) return null

  const pad = 7
  const cutout = {
    top: Math.max(4, rect.top - pad),
    left: Math.max(4, rect.left - pad),
    width: rect.width + pad * 2,
    height: rect.height + pad * 2,
  }
  const cardWidth = Math.min(440, window.innerWidth - 24)
  const left = clamp(rect.left, 12, window.innerWidth - cardWidth - 12)
  const top = rect.top + rect.height + 18 < window.innerHeight - 310
    ? rect.top + rect.height + 18
    : Math.max(12, rect.top - 310)

  return (
    <div className="tour-layer" role="dialog" aria-modal="true" aria-label={`新手導覽：${step.title}`}>
      <div className="tour-cutout" style={cutout} />
      <section className="tour-card" style={{ width: cardWidth, left, top }}>
        <div className="tour-card-head">
          <span className="label">導覽 {index + 1} / {steps.length}</span>
          <button type="button" className="tour-dismiss" onClick={onDismiss} aria-label="稍後再說">×</button>
        </div>
        <h2 className="display">{step.title}</h2>
        <p>{step.text}</p>
        {rect.fallback && <SampleTunnelCard />}
        <div className="tour-actions">
          {index > 0 && <button type="button" className="btn" onClick={() => setIndex(index - 1)}>上一步</button>}
          <button type="button" className="btn primary" onClick={() => index + 1 === steps.length ? onComplete() : setIndex(index + 1)}>
            {index + 1 === steps.length ? '完成導覽' : '下一步'}
          </button>
        </div>
        <div className="tour-secondary-actions">
          <button type="button" onClick={onDismiss}>稍後再說</button>
          <button type="button" onClick={onSkip}>跳過本段</button>
          <button type="button" onClick={onDisable}>我已知道，不再導覽</button>
        </div>
      </section>
    </div>
  )
}

function SampleTunnelCard() {
  return (
    <div className="tour-sample-card" aria-label="隧道卡片示意">
      <div><b className="display">八卦山隧道 西行</b><span className="chip">4 台相機</span></div>
      <span className="mono">K23+000 ⟶ K24+200</span>
      <small>建立後，隧道卡片會出現在這個位置。</small>
    </div>
  )
}
