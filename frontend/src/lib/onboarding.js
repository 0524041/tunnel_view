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

export const TOUR_STEPS = {
  home: [
    {
      target: '[data-tour="home-search"]',
      title: '先找既有的工作資料',
      text: '搜尋欄會同時比對專案名稱與隧道名稱。輸入「八卦山」可找到該案所有方向或年度的資料；輸入更完整的名稱，則可快速鎖定單一隧道。',
    },
    {
      target: '[data-tour="home-new-project"]',
      title: '用專案收納同一案子',
      text: '「專案」是案子層級，例如台 76 線八卦山隧道。可將西行、東行或不同年度拍攝的多條隧道歸在同一專案，後續可隨時移動、改名或重新分類。',
    },
    {
      target: '[data-tour="home-tunnel-card"]',
      fallbackTarget: '[data-tour="home-projects"]',
      title: '從卡片開啟檢視',
      text: '每張卡片代表一條已建立的隧道，會顯示相機數、里程範圍與最近使用時間。點擊卡片即可在上方開啟新的檢視分頁，不會離開總覽。',
    },
    {
      target: '[data-tour="home-new-tunnel"]',
      title: '建立一條隧道',
      text: '從這裡依序設定拍攝範圍、選擇各相機的照片資料夾並確認對齊結果。系統只讀取原始照片的 EXIF 與縮圖，不會搬移、刪除或改寫來源照片。',
    },
    {
      target: '[data-tour="app-help"]',
      title: '需要完整說明時',
      text: '隨時按 ? 開啟目前頁面的完整說明。本導覽帶你走核心流程；專案管理、相機設定與快捷鍵等細節都可在說明中隨時查閱。',
    },
  ],
  wizard: [
    {
      target: '[data-tour="wizard-steps"]',
      title: '三步完成匯入',
      text: '依序設定拍攝範圍、配置相機與照片資料夾，再確認對齊結果。建立前不會變更來源照片。',
    },
    {
      target: '[data-tour="wizard-basics"]',
      title: '先定義拍攝方向',
      text: '起點與迄點決定里程遞增或遞減方向；隧道名稱建議包含方向與年度，方便後續辨識。',
    },
    {
      target: '[data-tour="app-help"]',
      title: '查看完整操作說明',
      text: '按 ? 可查看建立流程、相機版型與對齊分析的詳細說明。選資料夾與建立資料都必須由你確認。',
    },
  ],
  viewer: [
    {
      target: '[data-tour="viewer-search"]',
      title: '直接跳到指定里程',
      text: '輸入樁號可定位至最接近的照片群組；也可使用 Ctrl + G 隨時開啟搜尋。',
    },
    {
      target: '[data-tour="viewer-fit"]',
      title: '切換完整與填滿呈現',
      text: '「完整」保留照片全貌，適合判讀整體位置與邊界；「填滿」放大至填滿每個格位，適合集中查看襯砌表面細節。此設定只影響畫面呈現，不會改動照片。',
    },
    {
      target: '[data-tour="viewer-grid"]',
      title: '同步檢視所有視角',
      text: '每個格位都是同一時間點、不同相機拍到的照片。可用滾輪縮放、拖曳平移、雙擊還原；照片缺失會在對應機位顯示，方便交叉比對。',
    },
    {
      target: '[data-tour="viewer-grid"]',
      title: '點照片標註異狀',
      text: '點擊任一照片會開啟原圖。右側「異狀標註」可新增裂縫、滲漏水、剝落等類型，寫入照片備註並儲存；已標註的照片會在檢視格與里程軌留下標記。',
    },
    {
      target: '[data-tour="viewer-anchors"]',
      title: '用錨點校正里程',
      text: '到實際里程牌所在的群組後按 Enter 輸入真實樁號，全線推算里程會立即重新計算。右側「錨點列」可檢視、跳轉或刪除既有錨點。',
    },
    {
      target: '[data-tour="viewer-mode"]',
      title: '切換異狀總覽',
      text: '異狀總覽會集中列出所有已標註照片，可依類型、備註關鍵字與里程排序篩選，也能匯出 Excel 或 CSV。按「定位」會直接回到對應照片格。',
    },
    {
      target: '[data-tour="viewer-rail"]',
      title: '用里程軌巡查全線',
      text: '底部里程軌可點擊跳轉、滾輪縮放、拖曳平移。藍色是錨點、紅色是缺照、琥珀菱形是比例異常、洋紅色是已標註異狀；停在異狀標記上可查看摘要。',
    },
    {
      target: '[data-tour="viewer-info"]',
      title: '從資訊面板管理資料',
      text: '「資訊」有匯入報告與相機兩頁：可查看對齊容差、群組與缺照統計、重新對齊預覽、已隱藏群組；也能重新命名隧道與相機、調整相機版型與照片方向。',
    },
    {
      target: '[data-tour="viewer-help"]',
      title: '完整功能與快捷鍵',
      text: '按 ? 可查看錨點、合併邊界、照片操作與所有快捷鍵的詳細說明。',
    },
  ],
}

// Set this to an object when a future release needs a targeted announcement.
// Example: { id: '2026-10-layout', title: '版型編輯更新', text: '...', steps: [...] }.
// Existing completed tours will not replay; only this announcement is shown.
export const CURRENT_UPDATE = null

export function storageKey(section) {
  return `tv_onboarding_${section}`
}

export function isTourDisabled() {
  return localStorage.getItem('tv_onboarding_disabled') === '1'
}

export function isTourComplete(section) {
  return localStorage.getItem(storageKey(section)) === 'done'
}

export function completeTour(section) {
  localStorage.setItem(storageKey(section), 'done')
}

export function disableTours() {
  localStorage.setItem('tv_onboarding_disabled', '1')
}

export function resetTours() {
  localStorage.removeItem('tv_onboarding_disabled')
  for (const section of Object.keys(TOUR_STEPS)) localStorage.removeItem(storageKey(section))
}

export function updateStorageKey(update) {
  return `tv_onboarding_update_${update.id}`
}

export function isUpdateSeen(update) {
  return localStorage.getItem(updateStorageKey(update)) === 'done'
}

export function completeUpdate(update) {
  localStorage.setItem(updateStorageKey(update), 'done')
}

export function areUpdatesDisabled() {
  return localStorage.getItem('tv_onboarding_updates_disabled') === '1'
}

export function disableUpdates() {
  localStorage.setItem('tv_onboarding_updates_disabled', '1')
}
