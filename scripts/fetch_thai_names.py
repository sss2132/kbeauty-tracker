"""Shopee Thailand에서 태국어 제품명을 수집하여 thai_names.json에 저장.

파이프라인 완료 후 별도 실행:
  python scripts/fetch_thai_names.py

동작:
  1. 최신 weekly_ranking JSON에서 제품 목록 로드
  2. 각 제품의 english_name으로 Shopee Thailand 검색
  3. 매칭되는 제품의 태국어 제품명을 수집
  4. data/thai_names.json에 {product_code: name_th} 형태로 저장
"""

import json
import os
import re
import sys
import time
from glob import glob

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

SHOPEE_SEARCH_URL = "https://shopee.co.th/search?keyword={}"
THAI_NAMES_PATH = os.path.join(DATA_DIR, "thai_names.json")


def load_existing():
    if os.path.exists(THAI_NAMES_PATH):
        with open(THAI_NAMES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_products():
    """최신 weekly_ranking에서 제품 목록 로드."""
    files = sorted(glob(os.path.join(DATA_DIR, "weekly_ranking_*.json")))
    if not files:
        print("[THAI] weekly_ranking 파일 없음")
        return []
    with open(files[-1], "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("products", [])


def search_shopee(page, english_name, brand_en):
    """Shopee Thailand에서 검색하여 태국어 제품명 반환."""
    query = english_name.replace(" ", "+")
    url = SHOPEE_SEARCH_URL.format(query)
    try:
        page.goto(url, timeout=20000)
        page.wait_for_timeout(4000)
    except Exception as e:
        print(f"  [WARN] 페이지 로드 실패: {e}")
        return None

    # 검색 결과에서 제품명 추출
    try:
        items = page.query_selector_all("[data-sqe='item'] .shopee-search-item-result__item")
        if not items:
            items = page.query_selector_all(".shopee-search-item-result__item")
        if not items:
            # fallback: 모든 상품 카드 시도
            items = page.query_selector_all("[data-sqe='item']")

        for item in items[:5]:  # 상위 5개만 확인
            name_el = item.query_selector(".ie3A\\+n, .wjwUB\\+, [data-sqe='name']")
            if not name_el:
                # fallback
                name_el = item.query_selector("div[class*='name'], span[class*='name']")
            if name_el:
                name = name_el.inner_text().strip()
                # 브랜드명이 포함된 결과만 (관련성 확인)
                brand_lower = brand_en.lower()
                if brand_lower in name.lower():
                    return name
        return None
    except Exception as e:
        print(f"  [WARN] 결과 파싱 실패: {e}")
        return None


def main():
    existing = load_existing()
    products = load_products()
    if not products:
        return

    # 이미 태국어 이름이 있는 제품은 건너뜀
    to_fetch = [p for p in products if p["product_code"] not in existing]
    if not to_fetch:
        print("[THAI] 모든 제품의 태국어 이름이 이미 수집됨")
        return

    print(f"[THAI] {len(to_fetch)}개 제품 태국어 이름 수집 시작 (기존 {len(existing)}개)")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            locale="th-TH",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        for i, p in enumerate(to_fetch):
            code = p["product_code"]
            en_name = p.get("name_en", "")
            brand_en = p.get("brand_en", "")

            if not en_name or not brand_en:
                print(f"  [{i+1}/{len(to_fetch)}] {code} — 영문명/브랜드 없음, 건너뜀")
                continue

            print(f"  [{i+1}/{len(to_fetch)}] {en_name}")
            th_name = search_shopee(page, en_name, brand_en)

            if th_name:
                existing[code] = th_name
                print(f"    → {th_name}")
            else:
                print(f"    → 못 찾음")

            time.sleep(2)  # rate limit

        browser.close()

    # 저장
    with open(THAI_NAMES_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f"\n[THAI] 완료 — {len(existing)}개 저장: {THAI_NAMES_PATH}")


if __name__ == "__main__":
    main()
