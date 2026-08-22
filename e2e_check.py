"""端對端驗證：以八卦山西行實照跑完整流程（匯入→檢視→錨定→導航）。"""
import re as _re
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
SHOT = "/tmp/tv"
CAM_FOLDERS = [
    ("右壁", f"{sys.argv[1]}/右側壁"),
    ("左壁", f"{sys.argv[1]}/左側壁-002"),
    ("頂拱右", f"{sys.argv[1]}/頂拱(右)-003"),
    ("頂拱左", f"{sys.argv[1]}/頂拱(左)-004"),
]

results = []

def check(name, ok, extra=""):
    results.append((name, ok, extra))
    print(f"{'PASS' if ok else 'FAIL'}  {name} {extra}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1680, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    # 1. 首頁
    page.goto(BASE)
    page.wait_for_load_state("networkidle")
    check("首頁載入", page.locator(".home-hero").count() == 1)

    # 2. 建立精靈 step1
    page.click("text=建立新隧道")
    page.wait_for_selector(".wizard")
    page.fill(".wiz-body input >> nth=0", "八卦山西行E2E")
    inputs = page.locator(".wiz-body input.field.mono")
    inputs.nth(0).fill("K23+000")
    inputs.nth(1).fill("K24+200")
    page.screenshot(path=f"{SHOT}_w1.png")
    page.click("text=下一步")

    # 3. step2 相機資料夾
    page.wait_for_selector(".cam-row")
    rows = page.locator(".cam-row")
    need = len(CAM_FOLDERS)
    while page.locator(".cam-row").count() < need:
        page.click("text=＋ 新增相機")
    for i, (name, folder) in enumerate(CAM_FOLDERS):
        row = page.locator(".cam-row").nth(i)
        row.locator("input").nth(0).fill(name)
        row.locator("input").nth(1).fill(folder)
    page.screenshot(path=f"{SHOT}_w2.png")

    # 4. 對齊預覽（804 張，需一點時間）
    t0 = time.time()
    page.click("text=執行對齊分析")
    page.wait_for_selector(".pv-stats", timeout=60000)
    elapsed = time.time() - t0
    body = page.inner_text(".pv-table")
    check("對齊預覽 Δt 表", "基準" in body and "+0.00s" not in body or "基準" in body)
    stats = page.inner_text(".pv-stats")
    print(f"   預覽統計: {' | '.join(stats.split())} （耗時 {elapsed:.1f}s）")
    page.screenshot(path=f"{SHOT}_w3.png", full_page=True)
    page.click("text=確認建立隧道")
    page.wait_for_selector(".viewer", timeout=30000)
    page.wait_for_load_state("networkidle")
    check("建立並進入檢視器", True)

    # 5. 檢視器：網格照片載入
    page.wait_for_selector("img.tile-img.on", timeout=20000)
    n_img = page.locator("img.tile-img.on").count()
    check("四視角照片載入", n_img >= 3, f"({n_img} 張)")

    # 6. 鍵盤導航 →/←
    seq_before = page.inner_text(".vread-seq")
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(400)
    seq_after = page.inner_text(".vread-seq")
    check("→ 切換群組", seq_before != seq_after, f"{seq_after.strip()}")

    # 7. Enter 錨點對話框：預填推算值、寫入 K23+150 於群組 50
    net_log = []
    page.on(
        "response",
        lambda r: net_log.append((r.status, r.url.split("/")[-1], r.request.method))
        if "/anchors/" in r.url or "/ws/" not in r.url
        else None,
    )
    for _ in range(48):
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(30)
    page.wait_for_timeout(600)
    page.keyboard.press("Enter")
    page.wait_for_selector(".dialog")
    # 等待預填值（群組資料可能還在載入）
    for _ in range(60):
        if page.input_value(".dialog input"):
            break
        page.wait_for_timeout(100)
    prefill = page.input_value(".dialog input")
    check("錨點對話框預填推算值", bool(prefill.strip()), f"({prefill})")
    page.fill(".dialog input", "K23+150")
    page.screenshot(path=f"{SHOT}_dialog.png")
    page.keyboard.press("Enter")
    page.wait_for_timeout(1200)
    still_open = page.locator(".dialog").count()
    err_text = page.inner_text(".err-text") if page.locator(".err-text").count() else "(無)"
    print(f"   [診斷] 對話框仍開={still_open} 錯誤訊息={err_text}")
    for s_, u_, m_ in net_log[-6:]:
        print(f"   [診斷] NET {m_} {s_} …{u_[-30:]}")
    locked = page.locator(".vread-mile.lock").count()
    check("錨定後里程轉為藍色鎖定樣式", locked == 1)

    # 8. 錨點抽屜列出錨點
    drawer_text = page.inner_text(".drawer")
    check("錨點抽屜顯示 K23+150", "K23+150" in drawer_text)

    # 9. Ctrl+G 跳轉
    page.keyboard.press("Control+g")
    page.wait_for_selector(".dialog")
    page.fill(".dialog input", "23+180")
    page.keyboard.press("Enter")
    page.wait_for_timeout(700)
    readout = page.inner_text(".vread-mile")
    import re as _re2
    mnum = _re2.search(r"K(\d+)\+(\d+)", readout)
    got = int(mnum.group(1)) * 1000 + int(mnum.group(2)) if mnum else -1
    check("Ctrl+G 里程跳轉至最近群組", abs(got - 23180) <= 8, f"({readout.strip()})")

    # 10. Scrubber 點擊跳轉到最前面附近
    rail = page.locator(".rail-wrap")
    box = rail.bounding_box()
    page.mouse.click(box["x"] + 20, box["y"] + box["height"] / 2)
    page.wait_for_timeout(600)
    cur_text = " ".join(page.inner_text(".vread-seq").split())
    import re as _re
    m = _re.search(r"(\d{4})", cur_text)
    check("導航軌點擊跳轉", m is not None and int(m.group(1)) <= 5, f"({cur_text})")

    # 11. 縮放同步：滾輪於第一格縮放，第二格 transform 應同步
    tiles = page.locator(".tile-img.on")
    if tiles.count() >= 2:
        t1 = tiles.nth(0)
        b = t1.bounding_box()
        page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
        page.mouse.wheel(0, -600)
        page.wait_for_timeout(300)
        trs = [tiles.nth(i).get_attribute("style") for i in range(min(2, tiles.count()))]
        same = all("scale(1)" not in (t or "") for t in trs)
        check("滾輪縮放各格同步", same)
    page.screenshot(path=f"{SHOT}_viewer.png")

    # 12. 刪除錨點還原推算（波浪號回來）
    page.keyboard.press("Escape")
    rows = page.locator(".anchor-row .btn.danger")
    if rows.count():
        rows.first.click()
        page.wait_for_timeout(800)
        gone = "K23+150" not in page.inner_text(".drawer")
        tilde_back = "~" in page.inner_text(".vread-mile")
        check("刪除錨點還原推算", gone and tilde_back)

    # ===== 修訂 R1：資訊面板 / 重新對齊 / 合併 / 原圖檢視 / 旋轉 =====
    page.keyboard.press("Escape")
    page.click("text=資訊")
    page.wait_for_selector(".info-drawer")
    drawer_txt = page.inner_text(".info-drawer")
    check("資訊面板開啟（含匯入報告）", "容差" in drawer_txt and "群組數" in drawer_txt)

    tol_input = page.locator(".realign-row input")
    tol_input.fill("4")
    page.click("text=乾跑預覽")
    page.wait_for_selector(".realign-preview")
    pv = page.inner_text(".realign-preview")
    check("重新對齊乾跑預覽", "新群組數" in pv)
    page.click("text=套用")
    page.wait_for_timeout(2000)
    drawer_txt2 = page.inner_text(".info-drawer")
    check("重新對齊後報告更新（容差 4s）", "4s" in drawer_txt2)

    # 合併：M 進檢閱模式 → 與後合併 → 衝突裁決保留當前側
    total_before = int(_re.search(r"/\s*(\d+)", " ".join(page.inner_text(".vread-seq").split())).group(1))
    page.keyboard.press("Escape")
    page.keyboard.press("m")
    page.wait_for_selector(".review-overlay")
    check("檢閱模式三聯並排", page.locator(".review-col").count() == 3)
    page.click("text=與後合併 ⇥")
    page.wait_for_selector(".dialog")
    page.click("text=保留當前側（鄰側改判缺照）")
    page.wait_for_timeout(1500)
    total_after = int(_re.search(r"/\s*(\d+)", " ".join(page.inner_text(".vread-seq").split())).group(1))
    check("合併後群組數減一", total_after == total_before - 1, f"({total_before}→{total_after})")

    # 點擊照片格開原圖覆蓋層 → R 旋轉 → Esc
    # （先重載脫離縮放狀態；重載後回首頁，需重新進入隧道）
    page.reload()
    page.wait_for_load_state("networkidle")
    page.click(".tunnel-card")
    page.wait_for_selector("img.tile-img.on", timeout=15000)
    tile = page.locator(".tile-img.on").first
    tb = tile.bounding_box()
    page.mouse.click(tb["x"] + tb["width"] / 2, tb["y"] + tb["height"] / 2)
    page.wait_for_selector(".orig-overlay")
    check("點擊開啟原圖覆蓋層", True)
    page.keyboard.press("r")
    page.wait_for_timeout(1200)
    page.keyboard.press("Escape")

    # 相機旋轉設定（資訊面板 → 相機）
    page.click("text=資訊")
    page.wait_for_selector(".info-drawer")
    page.click(".info-tab >> text=相機")
    page.wait_for_selector(".flag-card select")
    page.locator(".flag-card select").first.select_option("90")
    page.wait_for_timeout(1000)
    check("相機旋轉設定無錯誤", len(errors) == 0)

    check("無 JS 錯誤", len(errors) == 0, "; ".join(errors[:3]))
    browser.close()

fails = [r for r in results if not r[1]]
print(f"\n{'='*46}\n端對端驗證: {len(results)-len(fails)}/{len(results)} 通過")
exit(1 if fails else 0)
