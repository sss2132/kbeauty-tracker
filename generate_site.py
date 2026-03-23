"""
K-Beauty Trend Tracker - 정적 사이트 생성기 v4
weekly_ranking JSON -> docs/index.html (단일 파일, 5탭)
3소스(OY/NV/YT), RISING 배지, Outside OY, 3슬라이더
data_status 경고 배너, rank_change 표시, dropped_products
"""

import glob
import json
import os
import urllib.parse
from datetime import datetime

TH_MONTHS = {
    1: "ม.ค.", 2: "ก.พ.", 3: "มี.ค.", 4: "เม.ย.",
    5: "พ.ค.", 6: "มิ.ย.", 7: "ก.ค.", 8: "ส.ค.",
    9: "ก.ย.", 10: "ต.ค.", 11: "พ.ย.", 12: "ธ.ค."
}

def get_thai_date():
    now = datetime.now()
    return f"อัปเดต: {now.day} {TH_MONTHS[now.month]} {now.year}"

DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

CAT_COLORS = {
    "skincare": "#e8547a", "makeup": "#6c5ce7", "suncare": "#fdcb6e",
    "maskpack": "#00b894", "haircare": "#0984e3", "bodycare": "#a29bfe",
}

CAT_EMOJIS = {
    "skincare": "&#128167;",   # 💧
    "makeup": "&#128132;",     # 💄
    "suncare": "&#9728;&#65039;",  # ☀️
    "maskpack": "&#129526;",   # 🧖
    "haircare": "&#128135;",   # 💇
    "bodycare": "&#129524;",   # 🧴
}


def load_latest_ranking():
    files = sorted(glob.glob(os.path.join(DATA_DIR, "weekly_ranking_*.json")))
    if not files:
        return None
    with open(files[-1], "r", encoding="utf-8") as f:
        return json.load(f)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def build_rank_change_html(rc):
    """rank_change -> HTML span."""
    if rc == "NEW":
        return '<span class="rc rc-new">NEW</span>'
    elif rc.startswith("+") and rc != "+0":
        return f'<span class="rc rc-up">&#9650;{rc[1:]}</span>'
    elif rc.startswith("-"):
        return f'<span class="rc rc-down">&#9660;{rc[1:]}</span>'
    else:
        return '<span class="rc rc-same">--</span>'


def build_warning_banner(data_status):
    """data_status를 읽어 사용 불가능한 소스 경고 배너 생성."""
    nv_ok = data_status.get("naver_search", {}).get("available", False)
    yt_ok = data_status.get("youtube", {}).get("available", False)

    if nv_ok and yt_ok:
        return ""

    msgs = []
    if not yt_ok and nv_ok:
        msgs.append("&#9888;&#65039; ครั้งนี้ไม่มีข้อมูล YouTube -- คะแนนคำนวณจาก Olive Young + Naver เท่านั้น")
        msgs.append("&#9203; รอติดตาม อาจตรวจจับได้ไม่สมบูรณ์ในครั้งนี้")
    elif not nv_ok and yt_ok:
        msgs.append("&#9888;&#65039; ครั้งนี้ไม่มีข้อมูล Naver Shopping -- คะแนนคำนวณจาก Olive Young + YouTube เท่านั้น")
    elif not nv_ok and not yt_ok:
        msgs.append("&#9888;&#65039; ครั้งนี้ใช้เฉพาะข้อมูล Olive Young -- ข้อมูลอาจไม่ครบถ้วน")

    lines = "<br>".join(msgs)
    return f'''<div class="warn-banner" id="warn-banner">
  <div class="warn-text">{lines}</div>
  <button class="warn-close" onclick="document.getElementById('warn-banner').style.display='none'">&#10005;</button>
</div>'''


def build_product_cards(products):
    cards = []
    for p in products:
        rank = p["rank"]
        brand_en = esc(p.get("brand_en", p["brand"]))
        name_ko = esc(p["name_ko"])
        name_th = esc(p.get("name_th", ""))
        # 표시: 영문명(name_en) 상단, 한글명(name_ko) 하단
        name_en = esc(p.get("name_en", "").strip())
        display_name = name_en if name_en else name_ko
        cat = p["category"]
        cat_color = CAT_COLORS.get(cat, "#999")
        cat_emoji = CAT_EMOJIS.get(cat, "&#10024;")
        total = p["scores"]["total"]
        oy_rank = p.get("oliveyoung_rank", 0)

        rc_html = build_rank_change_html(p.get("rank_change", "0"))

        rc = {1: "rank-gold", 2: "rank-silver", 3: "rank-bronze"}.get(rank, "")

        badges = ""
        if p.get("signal") == "hot":
            badges += '<span class="badge badge-hot" title="สินค้าขายดีและเป็นกระแสบนโซเชียล">HOT</span><span class="badge-desc">สินค้าขายดีและเป็นกระแสบนโซเชียล</span>'
        elif p.get("signal") == "rising":
            badges += '<span class="badge badge-rising" title="อันดับสูงขึ้นมากจากครั้งก่อน">RISING</span><span class="badge-desc">อันดับสูงขึ้นมากจากครั้งก่อน</span>'
        for f in p.get("flags", []):
            if f == "buzz_trap":
                badges += '<span class="badge badge-buzz" title="เป็นกระแสในโซเชียล แต่ข้อมูลการขายยังต้องรอดูเพิ่ม">&#9203; รอติดตาม</span><span class="badge-desc">เป็นกระแสในโซเชียล แต่ข้อมูลการขายยังต้องรอดูเพิ่ม</span>'
            elif f == "hidden_gem":
                badges += '<span class="badge badge-gem" title="สินค้าขายดีในเกาหลี แต่ยังไม่เป็นกระแสในโซเชียล">HIDDEN GEM</span><span class="badge-desc">สินค้าขายดีในเกาหลี แต่ยังไม่เป็นกระแสในโซเชียล</span>'
            elif f == "steady_seller":
                badges += '<span class="badge badge-steady" title="สินค้าขายดีสม่ำเสมอ มีรีวิวมากมาย">STEADY SELLER</span><span class="badge-desc">สินค้าขายดีสม่ำเสมอ มีรีวิวมากมาย</span>'
        g = p.get("seller_grade", "")
        if g:
            gc = {"source_now": "grade-now", "watch": "grade-watch", "hold": "grade-hold", "proven": "grade-proven"}.get(g, "")
            label = {"source_now": "ซื้อเลย", "watch": "จับตา", "hold": "รอดู", "proven": "การันตี"}.get(g, g)
            badges += f'<span class="seller-grade {gc}">{esc(label)}</span>'

        shopee = esc(p.get("shopee_url", "#"))
        lazada = esc(p.get("lazada_url", "#"))
        yesstyle = esc(p.get("yesstyle_url", "#"))
        amazon = esc(p.get("amazon_url", "#"))

        cards.append(f'''<div class="product-card" data-category="{cat}">
  <div class="product-rank {rc}">{rank}{rc_html}</div>
  <div class="product-emoji">{cat_emoji}</div>
  <div class="product-info">
    <div class="product-brand">{brand_en}</div>
    <div class="product-name">{display_name}</div>
    <div class="product-name-ko">{name_ko}</div>
    <div class="product-badges">{badges}</div>
  </div>
  <div class="product-right">
    <button class="btn-buy" onclick="this.parentElement.parentElement.querySelector('.buy-links').classList.toggle('open')">ซื้อสินค้า &#9662;</button>
  </div>
  <div class="buy-links">
    <a href="{shopee}" target="_blank" rel="noopener"><span class="bl-icon">&#128722;</span><span class="bl-name">Shopee TH</span><span class="bl-desc">จัดส่งในไทย</span></a>
    <a href="{lazada}" target="_blank" rel="noopener"><span class="bl-icon">&#128722;</span><span class="bl-name">Lazada TH</span><span class="bl-desc">จัดส่งในไทย</span></a>
    <a href="{yesstyle}" target="_blank" rel="noopener"><span class="bl-icon">&#127760;</span><span class="bl-name">YesStyle</span><span class="bl-desc">จัดส่งทั่วโลก</span></a>
    <a href="{amazon}" target="_blank" rel="noopener"><span class="bl-icon">&#128230;</span><span class="bl-name">Amazon</span><span class="bl-desc">จัดส่งทั่วโลก</span></a>
    <div class="bl-note">อาจไม่มีสินค้าในบางแพลตฟอร์ม</div>
  </div>
</div>''')
    return "\n".join(cards)


def build_discover_html(products):
    """뷰 모드 2: 주목할 상품 (4섹션 그룹)."""
    used = set()
    sections = []

    # 1) 급상승 (RISING signal)
    rising = [p for p in products if p.get("signal") == "rising" and "buzz_trap" not in p.get("flags", []) and p["rank"] <= 20]
    for p in rising:
        used.add(p["rank"])
    sections.append(("rising", "&#128640; สินค้ามาแรง", "สินค้าที่อันดับสูงขึ้นมากจากครั้งก่อน", rising))

    # 2) Hidden Gem
    gems = [p for p in products if "hidden_gem" in p.get("flags", []) and p["rank"] not in used]
    for p in gems:
        used.add(p["rank"])
    sections.append(("gem", "&#128142; Hidden Gem", "สินค้าขายดีในเกาหลี แต่ยังไม่เป็นกระแสในโซเชียล", gems))

    # 2.5) Steady Seller
    steadies = [p for p in products if "steady_seller" in p.get("flags", []) and p["rank"] not in used]
    for p in steadies:
        used.add(p["rank"])
    sections.append(("steady", "&#127942; Steady Seller", "สินค้าขายดีสม่ำเสมอ มีรีวิวมากมาย เชื่อถือได้", steadies))

    # 3) 신규진입 (NEW)
    newbies = [p for p in products if p.get("rank_change") == "NEW" and p["rank"] <= 20 and p["rank"] not in used]
    for p in newbies:
        used.add(p["rank"])
    sections.append(("new", "&#127381; สินค้าใหม่ประจำครั้งนี้", "เพิ่งเข้า TOP 30 เป็นครั้งแรก!", newbies))


    html = ""
    for sec_type, title, desc, items in sections:
        cards = ""
        for p in items:
            rank = p["rank"]
            brand_en = esc(p.get("brand_en", p["brand"]))
            name_ko = esc(p["name_ko"])
            name_th = esc(p.get("name_th", ""))
            name_en = esc(p.get("name_en", "").strip())
            display_name = name_en if name_en else name_ko
            cat = p["category"]
            cat_emoji = CAT_EMOJIS.get(cat, "&#10024;")
            total = p["scores"]["total"]
            rc_html = build_rank_change_html(p.get("rank_change", "0"))

            badges = ""
            if p.get("signal") == "rising":
                badges += '<span class="badge badge-rising" title="อันดับสูงขึ้นมากจากครั้งก่อน">RISING</span><span class="badge-desc">อันดับสูงขึ้นมากจากครั้งก่อน</span>'
            for f in p.get("flags", []):
                if f == "hidden_gem":
                    badges += '<span class="badge badge-gem" title="สินค้าขายดีในเกาหลี แต่ยังไม่เป็นกระแสในโซเชียล">HIDDEN GEM</span><span class="badge-desc">สินค้าขายดีในเกาหลี แต่ยังไม่เป็นกระแสในโซเชียล</span>'
                elif f == "steady_seller":
                    badges += '<span class="badge badge-steady" title="สินค้าขายดีสม่ำเสมอ มีรีวิวมากมาย">STEADY SELLER</span><span class="badge-desc">สินค้าขายดีสม่ำเสมอ มีรีวิวมากมาย</span>'

            cards += f'''<div class="disc-card" data-category="{cat}">
  <div class="disc-rank">#{rank} {rc_html}</div>
  <div class="disc-emoji">{cat_emoji}</div>
  <div class="disc-info">
    <div class="product-brand">{brand_en}</div>
    <div class="product-name">{display_name}</div>
    <div class="product-name-ko">{name_ko}</div>
    <div class="product-badges">{badges}</div>
  </div>
</div>'''
        if not cards:
            cards = '<div class="disc-empty-sec">ยังไม่มีในครั้งนี้</div>'
        html += f'''<div class="disc-section disc-{sec_type}">
  <div class="disc-title">{title}</div>
  <div class="disc-desc">{desc}</div>
  {cards}
</div>'''
    return html


def build_keywords_html(data):
    keywords = data.get("keywords", {})
    html = ""

    nv_rising = keywords.get("naver_rising", [])
    if nv_rising:
        mx = max(k["change_rate"] for k in nv_rising)
        items = ""
        for i, kw in enumerate(nv_rising[:10], 1):
            w = min(100, (kw["change_rate"] / mx) * 100) if mx > 0 else 0
            display_kw = kw.get("keyword_en") or kw["keyword"]
            items += f'''<div class="kw-item">
  <span class="kw-rank">#{i}</span><span class="kw-text">{esc(display_kw)}</span>
  <div class="kw-bar-wrap"><div class="kw-bar" style="width:{w:.0f}%"></div></div>
  <span class="kw-rate">+{kw["change_rate"]:.0f}%</span>
</div>'''
        html += f'<div class="kw-section"><h3>&#128269; Naver Shopping คีย์เวิร์ดยอดนิยม</h3>{items}</div>'

    yt_rising = keywords.get("youtube_rising", [])
    if yt_rising:
        mx = max(k["change_rate"] for k in yt_rising)
        items = ""
        for i, kw in enumerate(yt_rising[:10], 1):
            w = min(100, (kw["change_rate"] / mx) * 100) if mx > 0 else 0
            items += f'''<div class="kw-item">
  <span class="kw-rank">#{i}</span><span class="kw-text">{esc(kw["keyword"])}</span>
  <div class="kw-bar-wrap"><div class="kw-bar kw-bar-yt" style="width:{w:.0f}%"></div></div>
  <span class="kw-rate">+{kw["change_rate"]:.0f}%</span>
</div>'''
        html += f'<div class="kw-section" style="margin-top:20px"><h3>&#9654; YouTube คีย์เวิร์ดยอดนิยม</h3>{items}</div>'

    if not html:
        html = '<p class="empty-msg">ยังไม่มีข้อมูลคีย์เวิร์ด</p>'
    return html


def build_seller_html(data):
    html = ""
    # &#9203; รอติดตาม - teaser only (full list in Pro tab)
    bts = data.get("buzz_traps", [])
    if bts:
        html += f'''<div class="ss ss-buzz"><h3>&#9203; รอติดตาม ({len(bts)} รายการ)</h3>
  <p class="ss-desc">สินค้าที่ยังต้องรอดูข้อมูลเพิ่มเติม ดูรายละเอียดใน Pro</p>
  <p class="ss-teaser">&#128274; ดูรายชื่อทั้งหมดได้ที่แท็บ <a href="#" onclick="document.querySelectorAll('.tab-btn')[3].click();return false" style="color:#e8547a;font-weight:700">รายงาน Pro</a></p>
</div>'''

    # Hidden Gem
    hgs = data.get("hidden_gems", [])
    if hgs:
        items = ""
        for hg in hgs:
            en_name = hg.get("name_en", "").strip()
            ko_name = hg.get("name_ko", "")
            items += f'''<div class="si si-gem"><div class="si-name">{esc(en_name) if en_name else esc(ko_name)}</div>
  <div class="si-reason">สินค้าขายดีในเกาหลี แต่ยังไม่เป็นกระแสในโซเชียล -- โอกาสเข้าตลาดก่อนคู่แข่ง</div></div>'''
        html += f'''<div class="ss ss-gem"><h3>&#128142; Hidden Gem - โอกาส ({len(hgs)})</h3>
  <p class="ss-desc">สินค้าขายดีในเกาหลี แต่ยังไม่เป็นกระแสในโซเชียล</p>{items}</div>'''

    # Steady Seller
    sss = data.get("steady_sellers", [])
    if sss:
        items = ""
        for ss in sss:
            en_name = ss.get("name_en", "").strip()
            ko_name = ss.get("name_ko", "")
            items += f'''<div class="si si-steady"><div class="si-name">{esc(en_name) if en_name else esc(ko_name)}</div>
  <div class="si-reason">สินค้าขายดีสม่ำเสมอ มีรีวิวมากมาย -- เหมาะสำหรับสต็อกระยะยาว</div></div>'''
        html += f'''<div class="ss ss-steady"><h3>&#127942; Steady Seller ({len(sss)})</h3>
  <p class="ss-desc">สินค้าที่ได้รับการพิสูจน์แล้วว่าขายดีต่อเนื่อง</p>{items}</div>'''

    # Dropped products
    dropped = data.get("dropped_products", [])
    if dropped:
        items = ""
        for dp in dropped:
            en_name = dp.get("name_en", "").strip()
            ko_name = dp.get("name_ko", "")
            display_name = en_name if en_name else ko_name
            items += f'''<div class="si si-dropped">
  <div class="si-name">{esc(display_name)}</div>
</div>'''
        html += f'''<div class="ss ss-dropped"><h3>&#128308; สินค้าที่หลุดจาก TOP 30 ครั้งนี้ ({len(dropped)})</h3>
  <p class="ss-desc">สินค้าที่อยู่ใน TOP 30 ครั้งก่อนแต่หลุดออกแล้ว</p>{items}</div>'''

    # TOP 5 sourcing
    top5 = sorted(
        [p for p in data["products"] if p["scores"]["total"] >= 60 and "buzz_trap" not in p.get("flags", [])],
        key=lambda x: x["scores"]["total"], reverse=True
    )[:5]
    if top5:
        items = ""
        for i, p in enumerate(top5, 1):
            en_name = p.get("name_en", "").strip()
            ko_name = p.get("name_ko", "")
            nm = esc(en_name if en_name else ko_name)
            note = esc(p.get("seller_note", ""))
            shopee = esc(p.get("shopee_url", "#"))
            lazada = esc(p.get("lazada_url", "#"))
            yesstyle = esc(p.get("yesstyle_url", "#"))
            amazon = esc(p.get("amazon_url", "#"))
            items += f'''<div class="src-item">
  <span class="src-rank">#{i}</span>
  <div class="src-info"><div class="src-name">{nm}</div><div class="src-note">{note}</div></div>
  <div class="src-right"><button class="btn-buy-sm" onclick="this.closest('.src-item').querySelector('.buy-links').classList.toggle('open')">ซื้อ &#9662;</button>
  </div>
  <div class="buy-links">
    <a href="{shopee}" target="_blank" rel="noopener"><span class="bl-icon">&#128722;</span><span class="bl-name">Shopee TH</span><span class="bl-desc">จัดส่งในไทย</span></a>
    <a href="{lazada}" target="_blank" rel="noopener"><span class="bl-icon">&#128722;</span><span class="bl-name">Lazada TH</span><span class="bl-desc">จัดส่งในไทย</span></a>
    <a href="{yesstyle}" target="_blank" rel="noopener"><span class="bl-icon">&#127760;</span><span class="bl-name">YesStyle</span><span class="bl-desc">จัดส่งทั่วโลก</span></a>
    <a href="{amazon}" target="_blank" rel="noopener"><span class="bl-icon">&#128230;</span><span class="bl-name">Amazon</span><span class="bl-desc">จัดส่งทั่วโลก</span></a>
    <div class="bl-note">อาจไม่มีสินค้าในบางแพลตฟอร์ม</div>
  </div>
</div>'''
        html += f'<div class="ss"><h3>&#127942; แนะนำซื้อขาย TOP 5</h3>{items}</div>'
    return html


def generate_html(data):
    products = data["products"]
    stats = data["stats"]
    updated = data["updated"]
    date_th = get_thai_date()
    w = data.get("active_weights", data.get("source_weights", {"oliveyoung": 0.45, "naver_search": 0.30, "youtube": 0.25}))
    oy_pct = int(w.get("oliveyoung", 0) * 100)
    ns_pct = int(w.get("naver_search", 0) * 100)
    yt_pct = int(w.get("youtube", 0) * 100)
    oy_w = w.get("oliveyoung", 0.45)
    ns_w = w.get("naver_search", 0.30)
    yt_w = w.get("youtube", 0.25)

    data_status = data.get("data_status", {})
    warning_html = build_warning_banner(data_status)

    product_cards = build_product_cards(products)
    discover_html = build_discover_html(products)
    keywords_html = build_keywords_html(data)
    seller_html = build_seller_html(data)

    # Blurred &#9203; รอติดตาม list for Pro tab
    bts = data.get("buzz_traps", [])
    buzz_pro_html = ""
    if bts:
        bt_items = ""
        for bt in bts:
            en_name = bt.get("name_en", "").strip()
            ko_name = bt.get("name_ko", "")
            bt_display = en_name if en_name else ko_name
            bt_items += f'''<div class="si si-buzz"><div class="si-name">{esc(bt_display)}</div>
  <div class="si-reason">รอดูข้อมูลเพิ่มเติม</div></div>'''
        buzz_pro_html = f'''<div class="ss ss-buzz" style="margin-top:16px">
    <h3>&#9203; รอติดตาม ({len(bts)} รายการ)</h3>
    <p class="ss-desc">สินค้าที่ยังต้องรอดูข้อมูลเพิ่มเติม</p>
    <div class="blur-wrap">
      <div class="blur-list">{bt_items}</div>
      <a href="#" class="blur-cta" onclick="this.parentElement.querySelector('.blur-list').classList.remove('blur-list');this.remove();return false">&#128275; ปลดล็อกดูรายชื่อ</a>
    </div>
  </div>'''

    share_url = "https://kbeauty-th.github.io"
    share_text = "&#127472;&#127479; อันดับเทรนด์ K-Beauty อัปเดตล่าสุด จากข้อมูลจริง #KBeautyTH"

    # Weight bar segments (unused in current UI but kept for reference)
    wbar_parts = ""

    # Source descriptions (unused in current UI)
    src_descs = ""

    src_count = sum(1 for v in [oy_pct, ns_pct, yt_pct] if v > 0)

    return f'''<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>K-Beauty Trend Tracker Thailand</title>
<meta name="description" content="ติดตามเทรนด์เครื่องสำอางเกาหลียอดนิยม อัปเดตทุก 3 วัน พร้อมคะแนนจาก Olive Young, Naver Shopping และ YouTube">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700&family=Noto+Sans+Thai:wght@400;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
#kbeauty-app{{font-family:'Noto Sans Thai','Noto Sans KR',system-ui,sans-serif;background:#f8f9fa;color:#2d3436;max-width:520px;margin:0 auto;min-height:100vh;position:relative;padding-bottom:160px}}

/* Warning banner */
.warn-banner{{background:#fff3cd;border-bottom:2px solid #ffc107;padding:10px 36px 10px 14px;font-size:12px;color:#856404;line-height:1.5;position:relative}}
.warn-close{{position:absolute;top:6px;right:10px;background:none;border:none;font-size:16px;color:#856404;cursor:pointer}}

/* Header */
.hdr{{background:linear-gradient(135deg,#e8547a,#ff6b9d);color:#fff;padding:16px 20px;text-align:center}}
.hdr h1{{font-size:18px;font-weight:700}}.hdr .sub{{font-size:12px;opacity:.85;margin-top:2px}}.hdr .tagline{{font-size:11px;opacity:.7;margin-top:4px;letter-spacing:.3px}}
.update-cycle{{font-size:10px;opacity:.6;margin-top:4px;text-align:center}}.update-date{{font-size:10px;opacity:.6;margin-top:2px;text-align:center}}

/* Tabs */
.tab-bar{{display:flex;background:#fff;border-bottom:2px solid #eee;position:sticky;top:0;z-index:100}}
.tab-btn{{flex:1;padding:10px 2px;font-size:13px;font-weight:600;background:none;border:none;color:#999;cursor:pointer;border-bottom:3px solid transparent;transition:.2s;font-family:inherit}}
.tab-btn.active{{color:#e8547a;border-bottom-color:#e8547a}}

/* Stats */
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding:12px 16px}}
.st{{background:#fff;border-radius:10px;padding:10px 6px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.st-v{{font-size:20px;font-weight:700;color:#e8547a}}.st-l{{font-size:11px;color:#999;margin-top:2px}}

/* Filter */
.fbar{{display:flex;gap:6px;padding:8px 16px;overflow-x:auto;-webkit-overflow-scrolling:touch}}.fbar::-webkit-scrollbar{{display:none}}
.fbtn{{padding:7px 14px;border-radius:20px;border:1.5px solid #ddd;background:#fff;font-size:12px;font-weight:600;color:#666;cursor:pointer;white-space:nowrap;transition:.2s;font-family:inherit}}
.fbtn.active{{background:#e8547a;color:#fff;border-color:#e8547a}}

/* Rank change */
.rc{{display:block;font-size:10px;font-weight:700;margin-top:1px}}
.rc-up{{color:#2ed573}}.rc-down{{color:#ff4757}}.rc-same{{color:#999}}.rc-new{{color:#3742fa}}

/* Product Card */
.plist{{padding:8px 16px}}
.product-card{{display:flex;flex-wrap:wrap;align-items:center;gap:8px;background:#fff;border-radius:12px;padding:12px;margin-bottom:8px;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.product-card[data-hidden="true"]{{display:none}}
.product-rank{{min-width:32px;height:42px;border-radius:8px;display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:#666;background:#f0f0f0;flex-shrink:0}}
.rank-gold{{background:linear-gradient(135deg,#f9ca24,#f0932b);color:#fff}}
.rank-silver{{background:linear-gradient(135deg,#dfe6e9,#b2bec3);color:#fff}}
.rank-bronze{{background:linear-gradient(135deg,#e17055,#d63031);color:#fff}}
.rank-gold .rc,.rank-silver .rc,.rank-bronze .rc{{color:rgba(255,255,255,.85)}}
.product-emoji{{width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0}}
.product-info{{flex:1;min-width:0}}
.product-brand{{font-size:12px;font-weight:700;color:#e8547a;text-transform:uppercase}}
.product-name{{font-size:14px;color:#2d3436;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.product-name-ko{{font-size:11px;color:#999;margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.product-scores{{display:flex;gap:4px;margin-top:3px}}
.sb{{font-size:10px;font-weight:600;padding:2px 6px;border-radius:3px}}
.sb-oy{{background:#fff0f3;color:#e8547a}}.sb-nr{{background:#e8f4fd;color:#0984e3}}.sb-ns{{background:#f0fff4;color:#00b894}}.sb-yt{{background:#fff0f0;color:#ff0000}}
.trend-tag{{font-size:9px;font-weight:700}}
.product-badges{{display:flex;flex-wrap:wrap;gap:3px;margin-top:3px;align-items:center}}
.badge{{font-size:9px;font-weight:700;padding:2px 6px;border-radius:3px;letter-spacing:.3px}}
.badge-hot{{background:#ff4757;color:#fff}}.badge-rising{{background:#8854d0;color:#fff}}
.badge-buzz{{background:#ffa502;color:#fff}}.badge-gem{{background:#2ed573;color:#fff}}.badge-steady{{background:#3742fa;color:#fff}}
.rising-detail{{font-size:10px;color:#8854d0;font-weight:600}}
.badge-desc{{font-size:0.75rem;color:#999;display:block;margin-top:1px}}
@media(max-width:480px){{.badge-desc{{display:none}}}}
.seller-grade{{font-size:9px;font-weight:600;padding:2px 6px;border-radius:3px}}
.grade-now{{background:#2ed573;color:#fff}}.grade-watch{{background:#3742fa;color:#fff}}.grade-hold{{background:#ffa502;color:#fff}}.grade-proven{{background:#5352ed;color:#fff}}
.product-right{{text-align:center;flex-shrink:0;min-width:58px}}
.rank-big{{font-size:22px;font-weight:700;color:#e8547a}}
.score-small{{font-size:12px;color:#999;margin-top:1px}}
.btn-buy{{display:block;margin-top:3px;padding:5px 12px;background:#e8547a;color:#fff;border:none;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;font-family:inherit}}

/* Buy links dropdown */
.buy-links{{display:none;width:100%;padding:6px 0 0}}.buy-links.open{{display:block}}
.buy-links a{{display:flex;align-items:center;gap:8px;padding:8px 10px;margin:4px 0;background:#f8f9fa;border-radius:8px;text-decoration:none;color:#2d3436;transition:.15s}}
.buy-links a:hover{{background:#eee}}
.bl-icon{{font-size:18px;flex-shrink:0}}.bl-name{{font-size:13px;font-weight:600;flex:1}}.bl-desc{{font-size:11px;color:#999}}
.bl-note{{font-size:10px;color:#bbb;text-align:center;margin-top:4px;padding-bottom:2px}}

/* Panels */
.panel{{display:none;padding:16px}}.panel.active{{display:block}}

/* Keywords */
.kw-section{{margin-bottom:8px;background:#fff;border-radius:12px;padding:14px;border-left:4px solid #e8547a}}.kw-section h3{{font-size:15px;font-weight:700;margin-bottom:12px}}
.kw-sub{{font-size:12px;color:#999;margin-bottom:10px}}
.kw-item{{display:flex;align-items:center;gap:8px;margin-bottom:8px}}
.kw-rank{{font-size:12px;font-weight:700;color:#e8547a;min-width:24px}}
.kw-text{{font-size:12px;min-width:90px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.kw-bar-wrap{{flex:1;height:8px;background:#f0f0f0;border-radius:4px;overflow:hidden}}
.kw-bar{{height:100%;background:linear-gradient(90deg,#e8547a,#ff6b9d);border-radius:4px}}
.kw-bar-yt{{background:linear-gradient(90deg,#ff0000,#ff4444)}}
.kw-rate{{font-size:11px;font-weight:700;color:#00b894;min-width:45px;text-align:right}}
.kw-src{{font-size:9px;font-weight:700;padding:2px 6px;border-radius:3px;min-width:48px;text-align:center}}
.src-nv{{background:#f0fff4;color:#00b894}}.src-yt{{background:#fff0f0;color:#ff0000}}
.outside-section{{background:#fff;border-radius:12px;padding:14px;border-left:4px solid #6c5ce7}}
.outside-item{{background:#f8f9fa;border-radius:8px;padding:8px}}

/* Seller */
.ss{{margin-bottom:16px}}.ss h3{{font-size:15px;font-weight:700;margin-bottom:4px}}.ss-desc{{font-size:12px;color:#999;margin-bottom:10px}}
.ss-buzz{{background:#fff8f0;border-radius:12px;padding:14px;border-left:4px solid #ffa502}}
.ss-gem{{background:#f0fff8;border-radius:12px;padding:14px;border-left:4px solid #2ed573}}
.ss-steady{{background:#f0f0ff;border-radius:12px;padding:14px;border-left:4px solid #5352ed}}
.ss-outside{{background:#f8f0ff;border-radius:12px;padding:14px;border-left:4px solid #8854d0}}
.ss-dropped{{background:#f5f5f5;border-radius:12px;padding:14px;border-left:4px solid #999}}
.si{{background:#fff;border-radius:8px;padding:10px;margin-bottom:6px;box-shadow:0 1px 2px rgba(0,0,0,.04)}}
.si-dropped{{background:#fafafa;border:1px dashed #ddd}}
.si-name{{font-size:13px;font-weight:600}}.si-scores{{font-size:11px;color:#999;margin-top:2px}}.si-reason{{font-size:12px;color:#666;margin-top:4px}}
.si-outside{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.si-src{{font-size:9px;font-weight:700;background:#f0f0f0;padding:1px 5px;border-radius:3px;color:#666}}
.si-rate{{font-size:13px;font-weight:700;color:#00b894}}.si-shopee-link{{font-size:11px;color:#e8547a;text-decoration:none;font-weight:600}}
.src-item{{display:flex;flex-wrap:wrap;align-items:center;gap:8px;background:#fff;border-radius:10px;padding:10px 12px;margin-bottom:8px;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.src-rank{{font-size:14px;font-weight:700;color:#e8547a}}.src-info{{flex:1;min-width:0}}
.src-name{{font-size:12px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.src-note{{font-size:10px;color:#999;margin-top:1px}}
.src-right{{text-align:center;flex-shrink:0}}.src-score{{display:block;font-size:18px;font-weight:700}}
.btn-buy-sm{{display:block;margin-top:3px;padding:4px 10px;background:#e8547a;color:#fff;border:none;border-radius:5px;font-size:10px;font-weight:600;cursor:pointer;font-family:inherit}}

/* Pro tab */
.pro-hdr{{text-align:center;padding:20px 0 10px}}.pro-hdr h2{{font-size:18px;color:#e8547a}}.pro-hdr p{{font-size:13px;color:#666;margin-top:4px}}
.pro-table{{width:100%;border-collapse:collapse;margin:16px 0;font-size:12px}}
.pro-table th{{background:#e8547a;color:#fff;padding:8px;text-align:left}}.pro-table td{{padding:8px;border-bottom:1px solid #eee}}
.pro-table tr:nth-child(even) td{{background:#fafafa}}
.pro-price{{text-align:center;margin:16px 0;padding:16px;background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.06);border-left:4px solid #e8547a}}
.pro-price .price{{font-size:22px;font-weight:700;color:#e8547a}}
.email-form{{background:#fff;border-radius:12px;padding:16px;margin:16px 0;box-shadow:0 1px 3px rgba(0,0,0,.06);text-align:center;border-left:4px solid #e8547a}}
.email-form h3{{font-size:15px;margin-bottom:8px}}.email-form p{{font-size:12px;color:#666;margin-bottom:12px}}
.email-row{{display:flex;gap:8px}}.email-row input{{flex:1;padding:10px;border:1.5px solid #ddd;border-radius:8px;font-size:13px;font-family:inherit;outline:none}}
.email-row input:focus{{border-color:#e8547a}}.email-row button{{padding:10px 18px;background:#e8547a;color:#fff;border:none;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;white-space:nowrap}}
.email-thanks{{display:none;color:#00b894;font-weight:600;font-size:13px;padding:10px 0}}
.pro-trust{{text-align:center;font-size:11px;color:#999;margin-top:12px;line-height:1.6}}

/* Method */
.msec{{background:#fff;border-radius:12px;padding:16px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.06);border-left:4px solid #e8547a}}
.msec h3{{font-size:15px;font-weight:700;margin-bottom:10px}}.msec p{{font-size:13px;color:#555;line-height:1.6;margin-bottom:8px}}
.wbar{{display:flex;height:32px;border-radius:8px;overflow:hidden;margin:10px 0}}
.w-oy{{background:#e8547a;color:#fff;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700}}
.w-nv{{background:#00b894;color:#fff;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700}}
.w-yt{{background:#ff0000;color:#fff;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700}}
.sg{{margin-bottom:12px}}.sg-label{{display:flex;justify-content:space-between;font-size:13px;font-weight:600;margin-bottom:4px}}
.sslider{{width:100%;-webkit-appearance:none;height:6px;border-radius:3px;background:#eee;outline:none;cursor:pointer}}
.sslider::-webkit-slider-thumb{{-webkit-appearance:none;width:20px;height:20px;border-radius:50%;background:#e8547a;cursor:pointer;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.2)}}
.sslider.sl-nr::-webkit-slider-thumb{{background:#0984e3}}
.sslider.sl-ns::-webkit-slider-thumb{{background:#00b894}}
.sslider.sl-yt::-webkit-slider-thumb{{background:#ff0000}}
.sim-res{{background:#f8f9fa;border-radius:10px;padding:14px;text-align:center;margin-top:12px}}
.sim-total{{font-size:36px;font-weight:700}}.sim-signal{{margin-top:6px;font-size:13px;font-weight:600}}

/* Newsletter banner */
.nl-banner{{background:linear-gradient(135deg,#e8547a,#ff6b9d);border-radius:12px;margin:16px;padding:16px;text-align:center;color:#fff}}
.nl-banner h4{{font-size:14px;margin-bottom:8px}}.nl-banner .email-row input{{border-color:rgba(255,255,255,.3);background:rgba(255,255,255,.15);color:#fff}}
.nl-banner .email-row input::placeholder{{color:rgba(255,255,255,.6)}}
.nl-banner .email-row button{{background:#fff;color:#e8547a}}
.nl-thanks{{display:none;color:#fff;font-weight:600;font-size:13px;padding:8px 0}}

/* Share */
.share-bar{{display:flex;justify-content:center;gap:10px;padding:12px 16px;flex-wrap:wrap}}
.share-btn{{display:flex;align-items:center;gap:4px;padding:6px 12px;border-radius:20px;font-size:11px;font-weight:600;text-decoration:none;color:#fff;cursor:pointer;border:none;font-family:inherit}}
.share-line{{background:#06c755}}.share-fb{{background:#1877f2}}.share-tw{{background:#1da1f2}}.share-tiktok{{background:#010101}}.share-ig{{background:linear-gradient(45deg,#f09433,#e6683c,#dc2743,#cc2366,#bc1888)}}.share-yt{{background:#ff0000}}.share-copy{{background:#2d3436}}

/* Footer */
.footer{{position:absolute;bottom:0;left:0;right:0;background:#2d3436;color:#aaa;padding:14px 16px;font-size:11px;text-align:center;line-height:1.7}}

.cat-legend{{display:flex;gap:10px;padding:4px 16px 8px;overflow-x:auto;font-size:11px;color:#666}}
.cat-legend span{{white-space:nowrap}}
.ss-teaser{{font-size:13px;color:#666;margin-top:8px}}
.blur-list{{filter:blur(4px);pointer-events:none;user-select:none}}
.blur-wrap{{position:relative}}.blur-cta{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);background:#e8547a;color:#fff;padding:10px 20px;border-radius:8px;font-size:13px;font-weight:700;z-index:10;text-decoration:none;box-shadow:0 2px 8px rgba(0,0,0,.2)}}
.toast{{position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:#2d3436;color:#fff;padding:10px 20px;border-radius:8px;font-size:13px;font-weight:600;opacity:0;transition:opacity .3s;pointer-events:none;z-index:999}}
.toast.show{{opacity:1}}
.empty-msg{{text-align:center;color:#999;padding:40px 0;font-size:14px}}

/* View toggle */
.view-toggle{{display:flex;gap:6px;padding:8px 16px}}
.vt-btn{{flex:1;padding:10px;border-radius:10px;border:1.5px solid #ddd;background:#fff;font-size:13px;font-weight:700;color:#666;cursor:pointer;font-family:inherit;transition:.2s;text-align:center}}
.vt-btn.vt-active{{background:#e8547a;color:#fff;border-color:#e8547a}}

/* Discover view */
.discover-view{{padding:8px 16px}}
.disc-section{{border-radius:12px;padding:14px;margin-bottom:12px}}
.disc-rising{{background:#f3eeff;border-left:4px solid #8854d0}}
.disc-gem{{background:#f0fff8;border-left:4px solid #2ed573}}
.disc-new{{background:#eef6ff;border-left:4px solid #0984e3}}
.disc-steady{{background:#f0f0ff;border-left:4px solid #5352ed}}
.disc-title{{font-size:15px;font-weight:700;margin-bottom:2px}}
.disc-desc{{font-size:12px;color:#777;margin-bottom:10px}}
.disc-card{{display:flex;align-items:center;gap:8px;background:rgba(255,255,255,.85);border-radius:10px;padding:10px;margin-bottom:6px}}
.disc-card[data-hidden="true"]{{display:none}}
.disc-rank{{font-size:13px;font-weight:700;color:#e8547a;min-width:40px;text-align:center}}
.disc-rank .rc{{display:inline;margin-left:2px}}
.disc-emoji{{font-size:20px;flex-shrink:0}}
.disc-info{{flex:1;min-width:0}}
.disc-score{{font-size:18px;font-weight:700;color:#e8547a;flex-shrink:0;min-width:36px;text-align:center}}
.disc-empty{{text-align:center;color:#999;padding:40px 0;font-size:14px}}
.disc-empty-sec{{text-align:center;color:#aaa;padding:16px 0;font-size:13px}}
/* Mobile */
@media(max-width:380px){{
  .stats{{grid-template-columns:repeat(2,1fr)}}
  .product-card{{gap:6px;padding:10px}}.product-emoji{{width:30px;height:30px;font-size:18px}}.rank-big{{font-size:18px}}
  .tab-btn{{font-size:11px;padding:9px 1px}}
  .product-name{{font-size:13px}}.product-brand{{font-size:11px}}.product-name-ko{{font-size:10px}}
  .sb{{font-size:9px}}.badge{{font-size:8px}}
}}
</style>
</head>
<body>
<div id="kbeauty-app">

{warning_html}

<div class="hdr">
  <h1>K-Beauty Trend Tracker</h1>
  <div class="sub">เทรนด์ความงามเกาหลี | {date_th}</div>
  <div class="tagline">จัดอันดับเทรนด์ K-Beauty จากข้อมูลจริง ไม่ใช่โฆษณา</div>
  <div class="update-cycle">อัปเดตทุก 3 วัน | ข้อมูลจาก 3 วัน เพื่อความแม่นยำของอันดับ</div>
  <div class="update-date">อัปเดตล่าสุด: {date_th}</div>
</div>

<div class="tab-bar">
  <button class="tab-btn active" data-tab="ranking">อันดับ</button>
  <button class="tab-btn" data-tab="keywords">คีย์เวิร์ด</button>
  <button class="tab-btn" data-tab="seller">สำหรับเซลเลอร์</button>
  <button class="tab-btn" data-tab="pro">รายงาน Pro</button>
  <button class="tab-btn" data-tab="method">วิธีคำนวณ</button>
</div>

<!-- Tab 1: Rankings -->
<div class="panel active" id="p-ranking">
  <div class="stats">
    <div class="st"><div class="st-v">{sum(1 for p in products if p.get("signal") == "rising")}</div><div class="st-l">&#128640; Rising</div></div>
    <div class="st"><div class="st-v">{stats["buzz_trap_count"]}</div><div class="st-l">&#9203; รอติดตาม</div></div>
    <div class="st"><div class="st-v">{stats["hidden_gem_count"]}</div><div class="st-l">Hidden Gem</div></div>
    <div class="st"><div class="st-v">{stats.get("steady_seller_count", 0)}</div><div class="st-l">Steady Seller</div></div>
  </div>
  <div class="fbar">
    <button class="fbtn active" data-cat="all">ทั้งหมด</button>
    <button class="fbtn" data-cat="skincare">สกินแคร์</button>
    <button class="fbtn" data-cat="makeup">เมกอัพ</button>
    <button class="fbtn" data-cat="suncare">กันแดด</button>
    <button class="fbtn" data-cat="maskpack">มาสก์แพ็ค</button>
    <button class="fbtn" data-cat="haircare">แฮร์แคร์</button>
    <button class="fbtn" data-cat="bodycare">บอดี้แคร์</button>
  </div>
  <div class="view-toggle">
    <button class="vt-btn vt-active" data-view="discover">&#128293; น่าจับตา</button>
    <button class="vt-btn" data-view="ranking">&#128202; อันดับ</button>
  </div>
  <div class="cat-legend">
    <span>&#128167; สกินแคร์</span>
    <span>&#128132; เมกอัพ</span>
    <span>&#9728;&#65039; กันแดด</span>
    <span>&#129526; มาสก์แพ็ค</span>
    <span>&#128135; แฮร์แคร์</span>
    <span>&#129524; บอดี้แคร์</span>
  </div>
  <div class="ranking-view" style="display:none"><div class="plist">{product_cards}</div></div>
  <div class="discover-view">{discover_html}</div>
</div>

<!-- Tab 2: Keywords -->
<div class="panel" id="p-keywords">
  {keywords_html}
</div>

<!-- Tab 3: Seller -->
<div class="panel" id="p-seller">
  {seller_html}
</div>

<!-- Tab 4: Pro Report -->
<div class="panel" id="p-pro">
  <div class="pro-hdr">
    <h2>รายงานเทรนด์ K-Beauty</h2>
    <p>สำหรับเซลเลอร์และอินฟลูเอนเซอร์</p>
  </div>
  <table class="pro-table">
    <tr><th>ฟีเจอร์</th><th>ฟรี</th><th>Pro &#11088;</th></tr>
    <tr><td>TOP 10 อันดับ</td><td>&#10004;</td><td>&#10004;</td></tr>
    <tr><td>คะแนนรายแหล่ง (OY/NS/YT)</td><td>&#10060;</td><td>&#10004;</td></tr>
    <tr><td>TOP 30 รายละเอียด</td><td>&#10060;</td><td>&#10004;</td></tr>
    <tr><td>&#9203; รอติดตาม ทั้งหมด</td><td>บางส่วน</td><td>&#10004;</td></tr>
    <tr><td>Hidden Gem ทั้งหมด</td><td>บางส่วน</td><td>&#10004;</td></tr>
    <tr><td>Outside OY โอกาส</td><td>&#10060;</td><td>&#10004;</td></tr>
    <tr><td>คู่มือสำหรับเซลเลอร์</td><td>&#10060;</td><td>&#10004;</td></tr>
    <tr><td>วิเคราะห์ Shopee TH</td><td>&#10060;</td><td>&#10004;</td></tr>
    <tr><td>รายงานทางอีเมลทุก 3 วัน</td><td>&#10060;</td><td>&#10004;</td></tr>
  </table>
  <div class="pro-price">
    <div class="price">เร็วๆ นี้</div>
    <div style="font-size:12px;color:#999;margin-top:4px">กำลังเตรียมแพ็กเกจราคาพิเศษ</div>
  </div>
  <div class="email-form" id="pro-email-form">
    <h3>&#128233; ลงทะเบียนรับรายงานฟรีฉบับแรก</h3>
    <p>ใส่อีเมลเพื่อรับรายงานเทรนด์ K-Beauty ฟรี 1 ฉบับ</p>
    <div class="email-row">
      <input type="email" id="pro-email" placeholder="you@email.com">
      <button onclick="handleProEmail()">สมัคร</button>
    </div>
    <div class="email-thanks" id="pro-thanks">ขอบคุณ! เราจะส่งรายงานให้คุณเร็วๆ นี้ &#127881;</div>
  </div>
  {buzz_pro_html}
  <div class="pro-trust">
    ข้อมูลจาก Olive Young Korea, Naver Shopping, YouTube<br>
    อัปเดตทุก 3 วัน โดยทีมผู้เชี่ยวชาญ K-Beauty
  </div>
</div>

<!-- Tab 5: Method -->
<div class="panel" id="p-method">
  <div class="msec">
    <h3>&#128202; วิธีคำนวณคะแนน</h3>
    <p>คะแนนรวมคำนวณจาก <strong>อัลกอริทึมเฉพาะ</strong> ที่วิเคราะห์ข้อมูลจาก {src_count} แหล่งข้อมูล:</p>
    <p>&#128722; ยอดขายจริงจาก Olive Young Korea<br>
    &#128202; อันดับสินค้ายอดนิยมจาก Naver Shopping<br>
    &#128269; ปริมาณการค้นหาจาก Naver Shopping<br>
    &#128250; กระแสรีวิวจาก YouTube</p>
    <p style="color:#999;font-size:12px;margin-top:8px">สัดส่วนและเกณฑ์คะแนนเป็นสูตรเฉพาะของ K-Beauty Trend Tracker</p>
  </div>
  <div class="msec">
    <h3>&#128680; &#9203; รอติดตาม คืออะไร?</h3>
    <p>สินค้าที่คนค้นหาและรีวิวมากในโซเชียล แต่ยอดขายจริงยังไม่สูง -- อาจเป็นแค่กระแสชั่วคราว ควรระวังในการสต็อก</p>
    <h3 style="margin-top:12px">&#128142; Hidden Gem คืออะไร?</h3>
    <p>สินค้าขายดีในเกาหลี แต่ยังไม่เป็นกระแสในโซเชียล -- โอกาสทองสำหรับเซลเลอร์เข้าตลาดก่อนคู่แข่ง</p>
    <h3 style="margin-top:12px">&#127942; Steady Seller คืออะไร?</h3>
    <p>สินค้าที่ขายดีต่อเนื่องและมีรีวิวมากมายในช่วง 3 เดือนที่ผ่านมา -- สินค้าที่ได้รับการพิสูจน์แล้วว่าขายดีจริง เหมาะสำหรับสต็อกระยะยาว</p>
    <h3 style="margin-top:12px">&#128640; RISING คืออะไร?</h3>
    <p>สินค้าที่อันดับรวมสูงขึ้นมากจากครั้งก่อน (10 อันดับขึ้นไป) -- สินค้ากำลังจะมาแรง!</p>
  </div>
</div>

<!-- Newsletter Banner -->
<div class="nl-banner" id="nl-banner">
  <h4>&#128233; รับเทรนด์ K-Beauty ทุกครั้งที่อัปเดต</h4>
  <div class="email-row">
    <input type="email" id="nl-email" placeholder="you@email.com">
    <button onclick="handleNlEmail()">สมัคร</button>
  </div>
  <div class="nl-thanks" id="nl-thanks">ขอบคุณ! &#127881;</div>
</div>

<!-- Share -->
<div class="share-bar">
  <a class="share-btn share-line" href="https://social-plugins.line.me/lineit/share?url={share_url}&text={share_text}" target="_blank" rel="noopener">LINE</a>
  <a class="share-btn share-fb" href="https://www.facebook.com/sharer/sharer.php?u={share_url}" target="_blank" rel="noopener">Facebook</a>
  <a class="share-btn share-tw" href="https://twitter.com/intent/tweet?text={share_text}&url={share_url}" target="_blank" rel="noopener">X</a>
  <button class="share-btn share-tiktok" onclick="copyAndToast(this)">TikTok</button>
  <button class="share-btn share-ig" onclick="copyAndToast(this)">Instagram</button>
  <button class="share-btn share-yt" onclick="copyAndToast(this)">YouTube</button>
  <button class="share-btn share-copy" onclick="copyAndToast(this)">&#128203; Copy</button>
</div>
<div class="toast" id="copy-toast"></div>

<div class="footer">
  ข้อมูลเพื่อการอ้างอิงเท่านั้น ไม่ใช่คำแนะนำการลงทุนหรือการซื้อขาย<br>
  แหล่งข้อมูล: Olive Young Korea, Naver Shopping, YouTube | อัปเดตทุก 3 วัน<br>
  ลิงก์บางส่วนเป็นลิงก์พันธมิตร — รายได้จากการซื้อผ่านลิงก์ช่วยสนับสนุนการดำเนินงานของเว็บไซต์นี้
</div>

</div>

<script>
(function(){{
  /* Tabs */
  var tabs=document.querySelectorAll('.tab-btn'),panels=document.querySelectorAll('.panel');
  tabs.forEach(function(b){{b.addEventListener('click',function(){{
    tabs.forEach(function(t){{t.classList.remove('active')}});
    panels.forEach(function(p){{p.classList.remove('active')}});
    b.classList.add('active');
    document.getElementById('p-'+b.dataset.tab).classList.add('active');
  }})}});

  /* View toggle */
  var vtBtns=document.querySelectorAll('.vt-btn');
  var rankView=document.querySelector('.ranking-view');
  var discView=document.querySelector('.discover-view');
  vtBtns.forEach(function(b){{b.addEventListener('click',function(){{
    vtBtns.forEach(function(v){{v.classList.remove('vt-active')}});b.classList.add('vt-active');
    if(b.dataset.view==='ranking'){{rankView.style.display='block';discView.style.display='none'}}
    else{{rankView.style.display='none';discView.style.display='';applyCatFilter()}}
  }})}});

  /* Category filter */
  var fbs=document.querySelectorAll('.fbtn');
  function applyCatFilter(){{
    var active=document.querySelector('.fbtn.active');
    var c=active?active.dataset.cat:'all';
    var cards=document.querySelectorAll('.product-card');
    cards.forEach(function(card){{
      if(c==='all'||card.dataset.category===c){{card.style.display='flex';card.setAttribute('data-hidden','false')}}
      else{{card.style.display='none';card.setAttribute('data-hidden','true')}}
    }});
    var dcards=document.querySelectorAll('.disc-card');
    dcards.forEach(function(card){{
      if(c==='all'||card.dataset.category===c){{card.style.display='flex';card.setAttribute('data-hidden','false')}}
      else{{card.style.display='none';card.setAttribute('data-hidden','true')}}
    }});
    /* Hide empty sections */
    document.querySelectorAll('.disc-section').forEach(function(sec){{
      var visible=sec.querySelectorAll('.disc-card:not([data-hidden="true"])');
      sec.style.display=visible.length?'':'none';
    }});
  }}
  fbs.forEach(function(b){{b.addEventListener('click',function(){{
    fbs.forEach(function(f){{f.classList.remove('active')}});b.classList.add('active');
    applyCatFilter();
  }})}});

}})();

function saveEmail(email){{
  var list=JSON.parse(localStorage.getItem('kbeauty_emails')||'[]');
  if(list.indexOf(email)===-1)list.push(email);
  localStorage.setItem('kbeauty_emails',JSON.stringify(list));
}}
function handleProEmail(){{
  var e=document.getElementById('pro-email');
  if(e.value&&e.value.includes('@')){{
    saveEmail(e.value);
    document.querySelector('#pro-email-form .email-row').style.display='none';
    document.getElementById('pro-thanks').style.display='block';
  }}else{{e.style.borderColor='#ff4757';e.focus()}}
}}
function handleNlEmail(){{
  var e=document.getElementById('nl-email');
  if(e.value&&e.value.includes('@')){{
    saveEmail(e.value);
    document.querySelector('#nl-banner .email-row').style.display='none';
    document.getElementById('nl-thanks').style.display='block';
  }}else{{e.style.borderColor='#ff4757';e.focus()}}
}}
function copyAndToast(btn){{
  var url='{share_url}';
  navigator.clipboard.writeText(url).then(function(){{
    var t=document.getElementById('copy-toast');
    t.textContent='\\u0e25\\u0e34\\u0e07\\u0e01\\u0e4c\\u0e16\\u0e39\\u0e01\\u0e04\\u0e31\\u0e14\\u0e25\\u0e2d\\u0e01\\u0e41\\u0e25\\u0e49\\u0e27!';
    t.classList.add('show');
    setTimeout(function(){{t.classList.remove('show')}},2000);
  }});
}}
</script>
</body>
</html>'''


def main():
    data = load_latest_ranking()
    if not data:
        return
    os.makedirs(DOCS_DIR, exist_ok=True)
    html = generate_html(data)
    out = os.path.join(DOCS_DIR, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[site] {out}")
    st = data["stats"]
    print(f"  products: {st['total_products']}, analyzed: {st['total_analyzed']}, new: {st.get('new_entries',0)}, dropped: {st.get('dropped_count',0)}, buzz: {st['buzz_trap_count']}, gem: {st['hidden_gem_count']}")


if __name__ == "__main__":
    main()
