"""
키워드 재시도 모듈 - 검색량 0인 제품의 키워드를 연관검색어 기반으로 개선

Step 3 (API 수집) 이후 실행:
  python scripts/keyword_retry.py

전략 우선순위:
1. 네이버 자동완성 API (연관검색어)
2. 구글 연관검색어
3. 단어 축소 (올리브영 검색으로 검증 후에만 사용)
"""

import json
import os
import re
import sys
import time
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, YOUTUBE_API_KEY
from scripts.naver_trend import fetch_batch, REF_KEYWORD
from scripts.youtube_trend import fetch_keyword_trend

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


# ================================================================
#  연관검색어 수집
# ================================================================

def fetch_naver_autocomplete(query):
    """네이버 자동완성 API에서 추천 키워드 목록 반환."""
    url = (
        "https://ac.search.naver.com/nx/ac"
        f"?q={requests.utils.quote(query)}&con=1&frm=nv&ans=2"
        "&r_format=json&r_enc=UTF-8&r_unicode=0&t_koreng=1&run=2&rev=4&q_enc=UTF-8"
    )
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        suggestions = []
        for item_group in data.get("items", []):
            if isinstance(item_group, list):
                for entry in item_group:
                    if isinstance(entry, list) and len(entry) > 0:
                        suggestions.append(entry[0])
                    elif isinstance(entry, str):
                        suggestions.append(entry)
        return suggestions
    except Exception:
        return []


def fetch_naver_shopping_autocomplete(query):
    """네이버 쇼핑 자동완성 (쇼핑 카테고리 특화)."""
    url = (
        "https://ac.shopping.naver.com/ac"
        f"?q={requests.utils.quote(query)}&frm=shopping&r_format=json&r_enc=UTF-8&r_unicode=0"
    )
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        suggestions = []
        for item_group in data.get("items", []):
            if isinstance(item_group, list):
                for entry in item_group:
                    if isinstance(entry, list) and len(entry) > 0:
                        suggestions.append(entry[0])
                    elif isinstance(entry, str):
                        suggestions.append(entry)
        return suggestions
    except Exception:
        return []


def fetch_google_suggestions(query):
    """구글 연관검색어 (자동완성 API)."""
    url = f"https://suggestqueries.google.com/complete/search?client=firefox&q={requests.utils.quote(query)}"
    try:
        resp = requests.get(url, timeout=5, headers={"Accept-Language": "ko-KR,ko"})
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and len(data) >= 2:
            return data[1]
        return []
    except Exception:
        return []


def filter_brand_suggestions(suggestions, brand):
    """브랜드명이 포함된 추천만 필터링."""
    return [s for s in suggestions if brand.lower() in s.lower()]


# ================================================================
#  키워드 축소 + 올리브영 검증
# ================================================================

def shorten_keyword(keyword):
    """키워드에서 단어를 줄여 변형 목록 생성."""
    words = keyword.split()
    if len(words) <= 1:
        return []
    variants = []
    variants.append(" ".join(words[:-1]))  # 마지막 단어 제거
    if len(words) >= 3:
        variants.append(f"{words[0]} {words[-1]}")  # 브랜드 + 마지막
    return variants


def verify_keyword_on_oliveyoung(keyword, target_brand):
    """올리브영 검색으로 축소 키워드가 타겟 제품만 나오는지 검증.

    Returns: True if most results are from target brand (safe to use)
    """
    url = f"https://www.oliveyoung.co.kr/store/search/getSearchMain.do?query={requests.utils.quote(keyword)}"
    try:
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        text = resp.text

        # 검색 결과에서 브랜드명 출현 횟수 체크
        brand_count = text.lower().count(target_brand.lower())
        # 간단한 검증: 브랜드명이 여러 번 나오면 해당 브랜드 제품이 주로 나온다고 판단
        return brand_count >= 3
    except Exception:
        return False


# ================================================================
#  대안 키워드 생성 (우선순위: 연관검색어 > 검증된 축소)
# ================================================================

def generate_alternatives(keyword, source_type="naver"):
    """연관검색어 기반으로 대안 키워드 생성.

    Args:
        keyword: 원본 키워드
        source_type: "naver" or "youtube"

    Returns: [(대안키워드, 출처설명), ...]
    """
    alternatives = []
    brand = keyword.split()[0] if keyword.split() else ""
    seen = set()

    # 전략 1: 네이버 자동완성 (일반 검색)
    nv_suggestions = fetch_naver_autocomplete(keyword)
    for s in filter_brand_suggestions(nv_suggestions, brand):
        if s != keyword and s not in seen:
            alternatives.append((s, "네이버 자동완성"))
            seen.add(s)
    time.sleep(0.2)

    # 전략 2: 네이버 쇼핑 자동완성
    nv_shop = fetch_naver_shopping_autocomplete(keyword)
    for s in filter_brand_suggestions(nv_shop, brand):
        if s != keyword and s not in seen:
            alternatives.append((s, "네이버 쇼핑 자동완성"))
            seen.add(s)
    time.sleep(0.2)

    # 전략 3: 구글 연관검색어
    google_suggestions = fetch_google_suggestions(keyword)
    for s in filter_brand_suggestions(google_suggestions, brand):
        if s != keyword and s not in seen:
            alternatives.append((s, "구글 연관검색어"))
            seen.add(s)
    time.sleep(0.2)

    # 전략 4: 브랜드명으로 자동완성 (더 넓은 범위)
    if len(alternatives) < 3:
        brand_suggestions = fetch_naver_autocomplete(brand)
        for s in brand_suggestions[:5]:
            if s != keyword and s not in seen and brand.lower() in s.lower():
                alternatives.append((s, "브랜드 자동완성"))
                seen.add(s)

    # 전략 5: 단어 축소 (연관검색어로 못 찾았을 때만, 올리브영 검증 후)
    if not alternatives:
        for short_kw in shorten_keyword(keyword):
            if short_kw not in seen:
                is_safe = verify_keyword_on_oliveyoung(short_kw, brand)
                if is_safe:
                    alternatives.append((short_kw, "단어축소(검증됨)"))
                    seen.add(short_kw)
                else:
                    print(f"    [단어축소 거부] '{short_kw}' → 다른 제품이 섞임")
                time.sleep(0.3)

    return alternatives


# ================================================================
#  재조회
# ================================================================

def retry_naver_keyword(original_keyword, alternatives):
    """대안 키워드들로 네이버 검색량 재조회."""
    for alt_kw, source in alternatives:
        try:
            result = fetch_batch([REF_KEYWORD, alt_kw])
            ref_data = result.get(REF_KEYWORD, {"this_week": 0, "last_week": 0})
            alt_data = result.get(alt_kw, {"this_week": 0, "last_week": 0})
            ref_this = ref_data["this_week"]
            ref_last = ref_data["last_week"]

            norm_this = round(alt_data["this_week"] / ref_this * 100, 2) if ref_this > 0 else 0
            norm_last = round(alt_data["last_week"] / ref_last * 100, 2) if ref_last > 0 else 0

            if norm_this > 0:
                change_rate = (100.0 if norm_last == 0
                               else round((norm_this - norm_last) / norm_last * 100, 1))
                print(f"    -> [{source}] '{alt_kw}' = {norm_this} (성공)")
                return alt_kw, norm_this, norm_last, change_rate

            print(f"    -> [{source}] '{alt_kw}' = 0 (스킵)")
            time.sleep(0.3)
        except Exception as e:
            print(f"    -> [{source}] '{alt_kw}' 오류: {e}")
            time.sleep(0.3)
    return None


def retry_youtube_keyword(original_keyword, alternatives):
    """대안 키워드들로 유튜브 영상 수 재조회."""
    for alt_kw, source in alternatives:
        try:
            vc, tv, vc_lw, tv_lw, cr = fetch_keyword_trend(alt_kw)
            if vc > 0:
                print(f"    -> [{source}] '{alt_kw}' = {vc}건 (성공)")
                return alt_kw, vc, tv, vc_lw, tv_lw, cr
            print(f"    -> [{source}] '{alt_kw}' = 0건 (스킵)")
            time.sleep(0.3)
        except Exception as e:
            print(f"    -> [{source}] '{alt_kw}' 오류: {e}")
            time.sleep(0.3)
    return None


# ================================================================
#  메인
# ================================================================

def main():
    today = datetime.now().strftime("%Y%m%d")
    nv_path = os.path.join(DATA_DIR, f"naver_{today}.json")
    yt_path = os.path.join(DATA_DIR, f"youtube_{today}.json")

    # 인자로 naver/youtube만 지정 가능 (병렬 실행용)
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    run_naver = target in ("all", "naver")
    run_youtube = target in ("all", "youtube")

    nv_updated = 0
    yt_updated = 0

    # 네이버 재시도
    if run_naver and os.path.exists(nv_path):
        with open(nv_path, "r", encoding="utf-8") as f:
            nv_data = json.load(f)

        zero_items = [n for n in nv_data if (n.get("search_volume", 0) or 0) == 0]
        if zero_items:
            print(f"[RETRY] 네이버 검색량 0: {len(zero_items)}건 재시도")
            for item in zero_items:
                kw = item["keyword"]
                print(f"  '{kw}':")
                alts = generate_alternatives(kw, "naver")
                if not alts:
                    print(f"    대안 없음")
                    continue
                result = retry_naver_keyword(kw, alts)
                if result:
                    new_kw, sv, sv_lw, cr = result
                    item["keyword_original"] = kw
                    item["keyword"] = new_kw
                    item["search_volume"] = sv
                    item["search_volume_last_week"] = sv_lw
                    item["change_rate"] = cr
                    item["keyword_source"] = "retry"
                    nv_updated += 1

            with open(nv_path, "w", encoding="utf-8") as f:
                json.dump(nv_data, f, ensure_ascii=False, indent=2)
            print(f"[RETRY] 네이버 {nv_updated}건 개선")
        else:
            print("[RETRY] 네이버 검색량 0 없음 — 스킵")

    # 유튜브 재시도
    if run_youtube and os.path.exists(yt_path):
        with open(yt_path, "r", encoding="utf-8") as f:
            yt_data = json.load(f)

        zero_items = [y for y in yt_data
                      if y.get("youtube_available", True)
                      and (y.get("video_count", 0) or 0) == 0
                      and not y.get("api_error", False)]
        if zero_items:
            print(f"[RETRY] 유튜브 영상 0: {len(zero_items)}건 재시도")
            for item in zero_items:
                kw = item["keyword"]
                print(f"  '{kw}':")
                alts = generate_alternatives(kw, "youtube")
                if not alts:
                    print(f"    대안 없음")
                    continue
                result = retry_youtube_keyword(kw, alts)
                if result:
                    new_kw, vc, tv, vc_lw, tv_lw, cr = result
                    item["keyword_original"] = kw
                    item["keyword"] = new_kw
                    item["video_count"] = vc
                    item["total_views"] = tv
                    item["video_count_last_week"] = vc_lw
                    item["total_views_last_week"] = tv_lw
                    item["change_rate"] = cr
                    item["keyword_source"] = "retry"
                    yt_updated += 1

            with open(yt_path, "w", encoding="utf-8") as f:
                json.dump(yt_data, f, ensure_ascii=False, indent=2)
            print(f"[RETRY] 유튜브 {yt_updated}건 개선")
        else:
            print("[RETRY] 유튜브 영상 0 없음 — 스킵")

    print(f"\n[RETRY] 완료: 네이버 {nv_updated}건, 유튜브 {yt_updated}건 개선")
    return nv_updated + yt_updated


if __name__ == "__main__":
    main()
