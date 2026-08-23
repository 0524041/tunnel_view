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

const FEATURES = [
  ['異狀標註', '點擊照片格開啟原圖，右側常駐「異狀標註」面板：可為該照片新增多筆異狀（裂縫、滲漏水、剝落、白華、鋼筋外露等類型）與備註，也可撰寫整張照片的備註。類型可在面板內自行新增，全隧道專案共用；已被使用的類型刪除時自動封存。預覽網格中已標註的照片會顯示類型標籤。'],
  ['異狀總覽', '頂部「異狀總覽」模式一次瀏覽全部異狀卡片（縮圖＋樁號＋類型），支援類型篩選、關鍵字搜尋與排序；點卡片可直接編輯，「定位」則跳回檢視並閃爍該照片格。'],
  ['里程導航軌', '底部軌道以專業樁號刻度呈現（滾輪縮放、拖曳平移、點擊跳轉）。紫色標記＝該處有異狀（hover 看摘要、點擊直達）；藍方塊＝錨點；紅色短條＝缺照；琥珀菱形＝比例異常。'],
  ['錨點校正', '實際里程與推算不符時，走到該群組按 Enter 輸入真實樁號，全線里程即自動重算。右側錨點列可檢視／刪除既有錨點。'],
  ['合併邊界', '對齊產生多餘的群組邊界時，按 M 開啟檢閱模式將當前群組與前／後合併；衝突時可指定保留哪一側（另一側改判缺照）。'],
]

export default function HelpModal({ onClose }) {
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog help-dialog">
        <div className="help-head">
          <span className="display" style={{ fontSize: 17 }}>說明 · 快捷鍵與功能</span>
          <button type="button" className="btn small" onClick={onClose}>關閉（Esc）</button>
        </div>
        <div className="help-body">
          <section>
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
          </section>
          <section>
            <span className="label">功能指南</span>
            {FEATURES.map(([t, d]) => (
              <div key={t} className="help-feature">
                <b>{t}</b>
                <p>{d}</p>
              </div>
            ))}
          </section>
          <section>
            <span className="label">滑鼠操作</span>
            <p className="hint">
              照片格：滾輪縮放、拖曳平移、雙擊復原、點擊開原圖。
              里程軌：滾輪縮放時間窗、拖曳平移、點擊異狀標記直接跳轉。
            </p>
          </section>
        </div>
      </div>
    </div>
  )
}
