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

const SHORTCUTS = [
  ['← / →', '前一個／後一個群組'],
  ['Home / End', '跳到首端／末端群組'],
  ['Ctrl + G', '搜尋里程跳轉'],
  ['Enter', '為當前群組釘錨點（里程校正）'],
  ['M', '檢閱邊界（相鄰群組合併）'],
  ['R', '原圖檢視中：旋轉照片 90°'],
  ['Tab / Shift+Tab', '原圖檢視中：切換下一個／上一個視角'],
  ['Esc', '關閉目前開啟的視窗／面板'],
  ['?', '開啟本說明'],
]

const VIEWER_FEATURES = [
  ['照片呈現', '頂部「完整／填滿」切換只影響畫面呈現：完整模式保留照片全貌；填滿模式放大至格位邊緣，便於查看表面細節。照片格可滾輪縮放、拖曳平移、雙擊還原，點擊開啟原圖。'],
  ['異狀標註', '點擊照片格開啟原圖，右側常駐「異狀標註」面板：可為該照片新增多筆異狀（裂縫、滲漏水、剝落、白華、鋼筋外露等類型）與備註，也可撰寫整張照片的備註。類型可在面板內自行新增，全隧道專案共用；已被使用的類型刪除時自動封存。預覽網格中已標註的照片會顯示類型標籤，里程軌也會標出異狀位置。'],
  ['異狀總覽', '頂部「異狀總覽」模式一次瀏覽全部異狀卡片（縮圖＋樁號＋類型），支援類型篩選、關鍵字搜尋與排序；點卡片可直接編輯，「定位」則跳回檢視並閃爍該照片格。'],
  ['里程導航軌', '底部軌道以專業樁號刻度呈現（滾輪縮放、拖曳平移、點擊跳轉）。紫色標記＝該處有異狀（hover 看摘要、點擊直達）；藍方塊＝錨點；紅色短條＝缺照；琥珀菱形＝比例異常。'],
  ['錨點校正', '實際里程與推算不符時，走到該群組按 Enter 輸入真實樁號，全線里程即自動重算。右側錨點列可檢視／刪除既有錨點。'],
  ['合併邊界', '對齊產生多餘的群組邊界時，按 M 開啟檢閱模式將當前群組與前／後合併；衝突時可指定保留哪一側（另一側改判缺照）。'],
  ['資訊面板', '頂部「資訊」開啟右側面板。匯入報告頁提供容差、群組、相機偏移、缺照分佈、重新對齊、比例異常及已隱藏群組；相機頁可重新命名相機、調整旋轉與拖曳排序版型。'],
]

const PAGE_FEATURES = {
  home: [
    ['專案與隧道', '專案用來收納同一案子的多條隧道，例如西行、東行或不同年度。按「新增專案」建立分類；按隧道卡片開啟檢視，卡片內的「移動」可重新歸檔。'],
    ['搜尋', '搜尋欄可同時比對專案名稱與隧道名稱。若符合專案名稱，會顯示該專案下的所有隧道。'],
    ['建立新隧道', '按「建立新隧道」進入三步流程。照片來源只會被讀取與分析，不會移動、刪除或改寫原始檔。'],
  ],
  wizard: [
    ['基本設定', '填入隧道名稱與拍攝起迄樁號。起迄順序代表車行與拍攝方向，系統會據此決定群組的里程遞增或遞減。'],
    ['相機與版型', '每台相機選擇一個照片資料夾，可調整名稱、旋轉方向與網格位置。時間容差預設 2 秒，一般情況不需調整。'],
    ['對齊預覽', '分析會讀取 EXIF 拍攝時間並將同時間的照片組成群組。預覽中可檢查各機位張數與缺照分佈，確認後才寫入隧道資料。'],
  ],
  viewer: VIEWER_FEATURES,
}

const PAGE_GUIDES = {
  home: ['總覽', '用搜尋快速找到既有專案或隧道；「新增專案」用來整理同一案子的多次拍攝，「建立新隧道」則開始匯入照片。'],
  wizard: ['建立隧道', '先設定拍攝方向與樁號範圍，再為每台相機選照片資料夾並執行對齊分析。確認預覽後才會建立隧道資料，來源照片不會被修改。'],
  viewer: ['隧道檢視', '下方里程軌控制目前照片群組；點擊照片可看原圖、縮放與標註異狀。實際里程不符時，按 Enter 建立錨點即可校正。'],
}

export default function HelpModal({ section = 'viewer', onClose }) {
  const [pageTitle, pageText] = PAGE_GUIDES[section] || PAGE_GUIDES.viewer
  const features = PAGE_FEATURES[section] || VIEWER_FEATURES
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog help-dialog">
        <div className="help-head">
          <span className="display" style={{ fontSize: 17 }}>說明 · {pageTitle}</span>
          <button type="button" className="btn small" onClick={onClose}>關閉（Esc）</button>
        </div>
        <div className="help-body">
          <section>
            <span className="label">目前頁面</span>
            <p className="hint">{pageText}</p>
          </section>
          {section === 'viewer' && <section>
            <span className="label">快捷鍵</span>
            <table className="help-table">
              <tbody>
                {SHORTCUTS.map(([k, d]) => (
                  <tr key={k}>
                    <td><kbd className="mono">{k}</kbd></td>
                    <td>{d}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>}
          <section>
            <span className="label">功能指南</span>
            {features.map(([t, d]) => (
              <div key={t} className="help-feature">
                <b>{t}</b>
                <p>{d}</p>
              </div>
            ))}
          </section>
          {section === 'viewer' && <section>
            <span className="label">滑鼠操作</span>
            <p className="hint">
              照片格：滾輪縮放、拖曳平移、雙擊復原、點擊開原圖。
              里程軌：滾輪縮放時間窗、拖曳平移、點擊異狀標記直接跳轉。
            </p>
          </section>}
        </div>
      </div>
    </div>
  )
}
