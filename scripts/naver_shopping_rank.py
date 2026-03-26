"""
네이버 쇼핑 검색 API - 인기도순 순위 조회
기본 정렬(sim)이 실질적으로 인기도+정확도 종합순.
API 키가 없으면 샘플 데이터로 폴백.
"""

import json
import os
import re
import sys
import time
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SEARCH_URL = "https://openapi.naver.com/v1/search/shop.json"

# 카테고리별 검색 키워드 보조어
CAT_KEYWORD = {
    "skincare": "스킨케어",
    "makeup": "메이크업",
    "suncare": "선크림",
    "maskpack": "마스크팩",
    "haircare": "헤어",
    "bodycare": "바디",
}


def make_search_keyword(product):
    """제품 정보에서 네이버 쇼핑 검색 키워드 생성."""
    brand = product["brand"]
    name = product["name"]
    # 용량 제거
    short = re.sub(r"\d+\s*(ml|g|매입|매)\b", "", name).strip()
    words = short.split()
    if len(words) > 3:
        short = " ".join(words[:3])
    return f"{brand} {short}".strip()


def search_shopping(keyword, display=100):
    """네이버 쇼핑 검색 API 호출."""
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {
        "query": keyword,
        "display": display,
        "sort": "sim",
    }
    resp = requests.get(SEARCH_URL, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def clean_html(text):
    """HTML 태그 제거."""
    return re.sub(r"<[^>]+>", "", text)


def fuzzy_match(product, item):
    """검색 결과 아이템이 해당 제품과 매칭되는지 확인."""
    brand = product["brand"].lower()
    brand_en = product.get("brand_en", "").lower()
    name_words = product["name"].lower().split()

    item_title = clean_html(item.get("title", "")).lower()
    item_brand = item.get("brand", "").lower() if item.get("brand") else ""

    # 브랜드 매칭 (한글 또는 영문)
    brand_match = (brand in item_title or brand in item_brand or
                   (brand_en and (brand_en in item_title or brand_en in item_brand)))
    if not brand_match:
        return False

    # 제품명 핵심 단어 매칭 (2개 이상 일치)
    # 용량 등 숫자 제외
    key_words = [w for w in name_words if len(w) > 1 and not re.match(r"\d+", w)]
    if not key_words:
        return True  # 브랜드만 매칭되어도 OK

    match_count = sum(1 for w in key_words[:4] if w in item_title)
    return match_count >= min(2, len(key_words[:4]))


def find_rank(product, search_results):
    """검색 결과에서 해당 제품의 순위(1-based) 찾기."""
    items = search_results.get("items", [])
    for i, item in enumerate(items, 1):
        if fuzzy_match(product, item):
            return i, clean_html(item.get("title", "")), int(item.get("lprice", 0))
    return None, None, None


def run_with_api(products):
    """실제 API로 네이버 쇼핑 인기도순 조회."""
    print(f"[네이버 인기도] API 모드 - {len(products)}개 제품 조회 시작")
    results = []

    for i, product in enumerate(products):
        keyword = make_search_keyword(product)
        print(f"  [{i+1}/{len(products)}] {keyword}...", end=" ")

        try:
            data = search_shopping(keyword)
            total = data.get("total", 0)
            rank, matched_title, matched_price = find_rank(product, data)

            if rank:
                print(f"#{rank} ({matched_title[:30] if matched_title else ''})")
            else:
                print("매칭 없음")

            results.append({
                "product_code": product["product_code"],
                "keyword": keyword,
                "naver_shopping_rank": rank if rank else None,
                "matched_title": matched_title or "",
                "matched_price": matched_price or 0,
                "total_results": min(total, 100),
            })
        except requests.RequestException as e:
            print(f"실패 ({e})")
            results.append({
                "product_code": product["product_code"],
                "keyword": keyword,
                "naver_shopping_rank": None,
                "matched_title": "",
                "matched_price": 0,
                "total_results": 0,
            })

        time.sleep(0.5)

    return results


def run_with_sample():
    """API 키 없음 - 샘플 데이터 사용."""
    sample_path = os.path.join(DATA_DIR, "samples", "naver_rank_sample.json")
    if not os.path.exists(sample_path):
        print("[네이버 인기도] 오류: naver_rank_sample.json 없음")
        return []

    with open(sample_path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    today = datetime.now().strftime("%Y%m%d")
    output_path = os.path.join(DATA_DIR, f"naver_rank_{today}.json")

    # 올리브영 데이터 로드
    import glob as _glob
    oy_files = sorted(_glob.glob(os.path.join(DATA_DIR, "oliveyoung_*.json")))
    oy_files = [f for f in oy_files if "sample" not in os.path.basename(f)]
    if oy_files:
        oy_path = oy_files[-1]
    else:
        oy_path = os.path.join(DATA_DIR, "samples", "oliveyoung_sample.json")
    if not os.path.exists(oy_path):
        print("[네이버 인기도] 오류: 올리브영 데이터 없음")
        return

    with open(oy_path, "r", encoding="utf-8") as f:
        products = json.load(f)
    print(f"[네이버 인기도] OY 데이터: {os.path.basename(oy_path)}")

    if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET:
        print("[네이버 인기도] API 키 확인됨")
        results = run_with_api(products)
        # API가 전부 매칭 실패 시 dated 파일 미생성
        has_data = any(r.get("naver_shopping_rank") is not None for r in results)
        if not has_data:
            print("[네이버 인기도] API 결과 없음 - dated 파일 미생성, sample 사용")
            return output_path
    else:
        print("[네이버 인기도] API 키 없음 - 샘플 데이터 사용")
        results = run_with_sample()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"[네이버 인기도] 저장 완료: {output_path} ({len(results)}개)")
    return output_path


if __name__ == "__main__":
    main()
