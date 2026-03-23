"""올리브영 글로벌 몰에서 공식 영문 제품명 수집.

국내 올리브영 제품의 브랜드별로 글로벌 몰 검색 → 영문명 매칭.
결과: data/_global_names_{YYYYMMDD}.json
"""

import json
import os
import re
import sys
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

GLOBAL_SEARCH_URL = "https://global.oliveyoung.com/display/search?query={}"


def search_brand(page, brand_en):
    """글로벌 몰에서 브랜드 검색 → 영문 제품명 목록 반환."""
    url = GLOBAL_SEARCH_URL.format(brand_en.replace(" ", "+"))
    try:
        page.goto(url, timeout=15000)
        page.wait_for_timeout(3000)
    except Exception as e:
        print(f"  [WARN] {brand_en} 페이지 로드 실패: {e}")
        return []

    content = page.content()
    # 영문 제품명 추출: "BRAND Product Name 50ml" 패턴
    pattern = re.escape(brand_en.split()[0]) if brand_en else ""
    if not pattern:
        return []

    matches = re.findall(
        rf'({re.escape(brand_en.split()[0])}[^<"&]{{5,80}})',
        content,
        re.IGNORECASE
    )

    # 정제: HTML 엔티티 제거, 중복 제거
    names = []
    seen = set()
    for m in matches:
        m = m.strip()
        if "&" in m or "%" in m or len(m) < 10:
            continue
        # 용량/기획 포함된 풀네임 → 핵심만 추출은 키워드 agent가 함
        key = m.lower()
        if key not in seen:
            seen.add(key)
            names.append(m)

    return names


def match_products(oy_products, global_names_by_brand):
    """올리브영 제품과 글로벌 몰 영문명 매칭."""
    results = {}

    for p in oy_products:
        code = p["product_code"]
        brand_en = p.get("brand_en", "").strip()
        name_ko = p.get("search_keyword", p["name"])

        if not brand_en:
            continue

        brand_key = brand_en.upper().split()[0]
        candidates = global_names_by_brand.get(brand_key, [])

        if not candidates:
            continue

        # 간단한 매칭: 제품 타입 키워드로 필터
        # search_keyword에서 제품 타입 추출 (세럼, 크림, 패드 등)
        type_keywords = extract_type_keywords(name_ko)

        best_match = None
        best_score = 0
        for gname in candidates:
            score = compute_match_score(gname, type_keywords, brand_en)
            if score > best_score:
                best_score = score
                best_match = gname

        if best_match and best_score >= 2:
            results[code] = {
                "global_name": best_match,
                "match_score": best_score,
                "brand_en": brand_en,
            }

    return results


def extract_type_keywords(name_ko):
    """한국어 제품명에서 영문 매칭용 타입 키워드 추출."""
    mapping = {
        "세럼": ["serum"],
        "크림": ["cream"],
        "로션": ["lotion"],
        "선크림": ["sun", "sunscreen", "spf"],
        "쿠션": ["cushion"],
        "파운데이션": ["foundation"],
        "마스크팩": ["mask", "sheet"],
        "마스크": ["mask"],
        "패드": ["pad", "toner pad"],
        "앰플": ["ampoule", "ampule"],
        "클렌징": ["cleansing", "cleanser"],
        "틴트": ["tint"],
        "립": ["lip"],
        "아이섀도우": ["eye shadow", "eyeshadow"],
        "팔레트": ["palette"],
        "프라이머": ["primer"],
        "블러셔": ["blusher", "blush"],
        "글로스": ["gloss"],
        "라이너": ["liner"],
        "트리트먼트": ["treatment"],
        "핸드크림": ["hand cream"],
        "바디": ["body"],
        "스크럽": ["scrub"],
        "패치": ["patch"],
    }
    keywords = []
    for ko, en_list in mapping.items():
        if ko in name_ko:
            keywords.extend(en_list)
    return keywords


def compute_match_score(global_name, type_keywords, brand_en):
    """영문명과 타입 키워드의 매칭 점수."""
    gname_lower = global_name.lower()
    score = 0

    # 브랜드명 매칭
    if brand_en.lower().split()[0] in gname_lower:
        score += 1

    # 타입 키워드 매칭
    for kw in type_keywords:
        if kw.lower() in gname_lower:
            score += 1

    return score


def main():
    today = datetime.now().strftime("%Y%m%d")
    oy_path = os.path.join(DATA_DIR, f"oliveyoung_{today}.json")

    if not os.path.exists(oy_path):
        print(f"[글로벌] 올리브영 데이터 없음: {oy_path}")
        return None

    with open(oy_path, "r", encoding="utf-8") as f:
        oy_products = json.load(f)

    # 브랜드 목록 추출 (중복 제거)
    brands = {}
    for p in oy_products:
        brand_en = p.get("brand_en", "").strip()
        if brand_en:
            key = brand_en.upper().split()[0]
            if key not in brands:
                brands[key] = brand_en

    print(f"[글로벌] {len(brands)}개 브랜드 검색 시작")

    global_names_by_brand = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()

        for i, (key, brand_en) in enumerate(brands.items()):
            print(f"  [{i+1}/{len(brands)}] {brand_en}...", end=" ")
            names = search_brand(page, brand_en)
            global_names_by_brand[key] = names
            print(f"{len(names)}개")
            time.sleep(1)

        browser.close()

    # 매칭
    matched = match_products(oy_products, global_names_by_brand)
    print(f"\n[글로벌] 매칭 완료: {len(matched)}/{len(oy_products)}개")

    # 저장
    output = {
        "date": today,
        "total_products": len(oy_products),
        "matched": len(matched),
        "products": matched,
        "global_names_raw": {k: v for k, v in global_names_by_brand.items() if v},
    }

    out_path = os.path.join(DATA_DIR, f"_global_names_{today}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[글로벌] 저장: {out_path}")
    return out_path


if __name__ == "__main__":
    main()
