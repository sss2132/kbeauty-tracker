"""
키워드 재시도 모듈 - 검색량 0인 제품의 키워드를 개선하여 재조회

Step 3 (API 수집) 이후 실행:
  python scripts/keyword_retry.py

동작:
1. naver_YYYYMMDD.json에서 search_volume == 0인 항목 추출
2. youtube_YYYYMMDD.json에서 video_count == 0인 항목 추출
3. 네이버 자동완성 API로 대안 키워드 탐색
4. 단어 축소 전략으로 키워드 변형
5. 개선된 키워드로 API 재조회 후 원본 JSON 업데이트
"""

import json
import os
import sys
import time
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, YOUTUBE_API_KEY
from scripts.naver_trend import fetch_batch, REF_KEYWORD
from scripts.youtube_trend import fetch_keyword_trend

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

AUTOCOMPLETE_URL = (
    "https://ac.search.naver.com/nx/ac"
    "?q={query}&con=1&frm=nv&ans=2&r_format=json&r_enc=UTF-8"
    "&r_unicode=0&t_koreng=1&run=2&rev=4&q_enc=UTF-8"
)


# ================================================================
#  키워드 개선 전략
# ================================================================

def fetch_naver_autocomplete(query):
    """네이버 자동완성 API에서 추천 키워드 목록 반환."""
    url = AUTOCOMPLETE_URL.format(query=requests.utils.quote(query))
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        # 자동완성 결과는 items 배열 안에 [키워드, ...] 형태
        items = data.get("items", [])
        suggestions = []
        for item_group in items:
            if isinstance(item_group, list):
                for entry in item_group:
                    if isinstance(entry, list) and len(entry) > 0:
                        suggestions.append(entry[0])
                    elif isinstance(entry, str):
                        suggestions.append(entry)
        return suggestions
    except Exception as e:
        print(f"    [자동완성 오류] {query}: {e}")
        return []


def shorten_keyword(keyword):
    """키워드에서 단어를 하나씩 줄여 변형 목록 생성.

    예: "라로슈포제 시카플라스트 밤" → ["라로슈포제 시카플라스트", "라로슈포제 밤"]
    """
    words = keyword.split()
    if len(words) <= 1:
        return []
    variants = []
    # 뒤에서부터 단어 제거 (가장 일반적인 축소)
    variants.append(" ".join(words[:-1]))
    # 가운데 단어 제거 (브랜드 + 마지막 단어)
    if len(words) >= 3:
        variants.append(f"{words[0]} {words[-1]}")
    return variants


def find_best_autocomplete(keyword):
    """자동완성에서 원본 키워드와 가장 유사한 대안을 찾는다.

    Returns: (대안 키워드, 출처 설명) 또는 (None, None)
    """
    suggestions = fetch_naver_autocomplete(keyword)
    if not suggestions:
        return None, None

    # 원본 키워드의 첫 단어(브랜드)가 포함된 자동완성만 후보
    brand = keyword.split()[0] if keyword.split() else ""
    candidates = [s for s in suggestions if brand and brand in s]

    if not candidates:
        # 브랜드 매칭 실패 시 전체 자동완성 중 첫 번째
        candidates = suggestions

    if candidates:
        best = candidates[0]
        if best != keyword:
            return best, "자동완성"

    return None, None


def generate_naver_alternatives(keyword):
    """네이버 검색량 0인 키워드의 대안 목록 생성 (우선순위순).

    Returns: [(대안키워드, 출처설명), ...]
    """
    alternatives = []

    # 전략 1: 네이버 자동완성
    ac_kw, ac_src = find_best_autocomplete(keyword)
    if ac_kw:
        alternatives.append((ac_kw, ac_src))

    # 전략 2: 단어 축소
    for short_kw in shorten_keyword(keyword):
        alternatives.append((short_kw, "단어축소"))

    # 전략 3: 축소된 키워드로도 자동완성 시도
    for short_kw in shorten_keyword(keyword):
        ac_kw2, _ = find_best_autocomplete(short_kw)
        if ac_kw2 and ac_kw2 not in [a[0] for a in alternatives]:
            alternatives.append((ac_kw2, "축소+자동완성"))

    return alternatives


def generate_youtube_alternatives(keyword):
    """유튜브 video_count 0인 키워드의 대안 목록 생성 (우선순위순).

    Returns: [(대안키워드, 출처설명), ...]
    """
    alternatives = []
    words = keyword.split()

    # 전략 1: 단어 축소 (브랜드 + 핵심 단어)
    for short_kw in shorten_keyword(keyword):
        alternatives.append((short_kw, "단어축소"))

    # 전략 2: "리뷰" 추가
    alternatives.append((f"{keyword} 리뷰", "리뷰추가"))

    # 전략 3: 브랜드명만
    if len(words) >= 2:
        brand_only = words[0]
        # 브랜드만으로는 너무 넓으므로 브랜드 + 첫 제품어
        alternatives.append((f"{words[0]} {words[1]}", "브랜드+핵심어"))

    return alternatives


# ================================================================
#  네이버 재조회
# ================================================================

def retry_naver_keyword(original_keyword, alternatives):
    """대안 키워드들로 네이버 검색량 재조회. 0이 아닌 첫 결과 반환.

    Returns: (새 키워드, search_volume, search_volume_last_week, change_rate) 또는 None
    """
    for alt_kw, source in alternatives:
        try:
            batch_keywords = [REF_KEYWORD, alt_kw]
            result = fetch_batch(batch_keywords)

            ref_data = result.get(REF_KEYWORD, {"this_week": 0, "last_week": 0})
            alt_data = result.get(alt_kw, {"this_week": 0, "last_week": 0})

            ref_this = ref_data["this_week"]
            ref_last = ref_data["last_week"]

            norm_this = round(alt_data["this_week"] / ref_this * 100, 2) if ref_this > 0 else 0
            norm_last = round(alt_data["last_week"] / ref_last * 100, 2) if ref_last > 0 else 0

            if norm_this > 0:
                if norm_last == 0:
                    change_rate = 100.0
                else:
                    change_rate = round((norm_this - norm_last) / norm_last * 100, 1)

                print(f"    -> [{source}] '{alt_kw}' = {norm_this} (성공)")
                return alt_kw, norm_this, norm_last, change_rate

            print(f"    -> [{source}] '{alt_kw}' = 0 (스킵)")
            time.sleep(0.3)

        except Exception as e:
            print(f"    -> [{source}] '{alt_kw}' 오류: {e}")
            time.sleep(0.3)

    return None


def retry_youtube_keyword(original_keyword, alternatives):
    """대안 키워드들로 유튜브 영상 수 재조회. 0이 아닌 첫 결과 반환.

    Returns: (새 키워드, video_count, total_views, vc_lw, tv_lw, change_rate) 또는 None
    """
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
#  메인 로직
# ================================================================

def find_latest_file(prefix):
    """data/ 디렉터리에서 prefix_YYYYMMDD.json 중 최신 파일 경로 반환."""
    import glob as _glob
    pattern = os.path.join(DATA_DIR, f"{prefix}_*.json")
    files = sorted(_glob.glob(pattern))
    files = [f for f in files if "sample" not in os.path.basename(f)
             and "keywords" not in os.path.basename(f)]
    return files[-1] if files else None


def run_naver_retry(naver_path):
    """네이버 검색량 0인 항목을 키워드 개선하여 재조회."""
    with open(naver_path, "r", encoding="utf-8") as f:
        naver_data = json.load(f)

    zero_items = [item for item in naver_data if item.get("search_volume", 0) == 0]
    if not zero_items:
        print("[키워드개선/네이버] 검색량 0 항목 없음 - 스킵")
        return 0

    print(f"[키워드개선/네이버] 검색량 0 항목 {len(zero_items)}개 발견")
    updated_count = 0
    change_log = []

    for item in zero_items:
        original_kw = item["keyword"]
        print(f"  [{item['product_code']}] '{original_kw}' 대안 탐색...")

        alternatives = generate_naver_alternatives(original_kw)
        if not alternatives:
            print(f"    -> 대안 없음")
            continue

        result = retry_naver_keyword(original_kw, alternatives)
        if result:
            new_kw, sv, sv_lw, cr = result
            # 원본 데이터 업데이트
            item["keyword"] = new_kw
            item["search_volume"] = sv
            item["search_volume_last_week"] = sv_lw
            item["change_rate"] = cr
            item["keyword_original"] = original_kw
            item["keyword_source"] = "retry"

            change_log.append({
                "product_code": item["product_code"],
                "before": original_kw,
                "after": new_kw,
                "search_volume": sv,
            })
            updated_count += 1
        else:
            print(f"    -> 모든 대안 실패")

        time.sleep(0.3)

    # 결과 저장
    if updated_count > 0:
        with open(naver_path, "w", encoding="utf-8") as f:
            json.dump(naver_data, f, ensure_ascii=False, indent=2)
        print(f"\n[키워드개선/네이버] {updated_count}개 키워드 개선 완료 -> {naver_path}")

    # 변경 로그 출력
    if change_log:
        print("\n--- 네이버 키워드 변경 로그 ---")
        for log in change_log:
            print(f"  {log['product_code']}: '{log['before']}' -> '{log['after']}' (vol: {log['search_volume']})")

    return updated_count


def run_youtube_retry(youtube_path):
    """유튜브 video_count 0인 항목을 키워드 개선하여 재조회."""
    if not YOUTUBE_API_KEY:
        print("[키워드개선/유튜브] API 키 없음 - 스킵")
        return 0

    with open(youtube_path, "r", encoding="utf-8") as f:
        youtube_data = json.load(f)

    zero_items = [item for item in youtube_data
                  if item.get("video_count", 0) == 0 and not item.get("api_error", False)]
    if not zero_items:
        print("[키워드개선/유튜브] video_count 0 항목 없음 - 스킵")
        return 0

    print(f"[키워드개선/유튜브] video_count 0 항목 {len(zero_items)}개 발견")
    updated_count = 0
    change_log = []

    for item in zero_items:
        original_kw = item["keyword"]
        print(f"  [{item['product_code']}] '{original_kw}' 대안 탐색...")

        alternatives = generate_youtube_alternatives(original_kw)
        if not alternatives:
            print(f"    -> 대안 없음")
            continue

        result = retry_youtube_keyword(original_kw, alternatives)
        if result:
            new_kw, vc, tv, vc_lw, tv_lw, cr = result
            # 원본 데이터 업데이트
            item["keyword"] = new_kw
            item["video_count"] = vc
            item["total_views"] = tv
            item["video_count_last_week"] = vc_lw
            item["total_views_last_week"] = tv_lw
            item["change_rate"] = cr
            item["youtube_available"] = vc >= 3
            item["keyword_original"] = original_kw
            item["keyword_source"] = "retry"

            change_log.append({
                "product_code": item["product_code"],
                "before": original_kw,
                "after": new_kw,
                "video_count": vc,
                "total_views": tv,
            })
            updated_count += 1
        else:
            print(f"    -> 모든 대안 실패")

        time.sleep(0.3)

    # 결과 저장
    if updated_count > 0:
        with open(youtube_path, "w", encoding="utf-8") as f:
            json.dump(youtube_data, f, ensure_ascii=False, indent=2)
        print(f"\n[키워드개선/유튜브] {updated_count}개 키워드 개선 완료 -> {youtube_path}")

    # 변경 로그 출력
    if change_log:
        print("\n--- 유튜브 키워드 변경 로그 ---")
        for log in change_log:
            print(f"  {log['product_code']}: '{log['before']}' -> '{log['after']}' "
                  f"(videos: {log['video_count']}, views: {log['total_views']})")

    return updated_count


def main():
    print("=" * 60)
    print("[키워드 재시도] 검색량 0 제품 키워드 개선 시작")
    print("=" * 60)

    # 최신 데이터 파일 찾기
    naver_path = find_latest_file("naver")
    youtube_path = find_latest_file("youtube")

    total_updated = 0

    if naver_path and os.path.exists(naver_path):
        print(f"\n[네이버] 파일: {os.path.basename(naver_path)}")
        if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET:
            total_updated += run_naver_retry(naver_path)
        else:
            print("[키워드개선/네이버] API 키 없음 - 스킵")
    else:
        print("[키워드개선/네이버] 데이터 파일 없음 - 스킵")

    if youtube_path and os.path.exists(youtube_path):
        print(f"\n[유튜브] 파일: {os.path.basename(youtube_path)}")
        total_updated += run_youtube_retry(youtube_path)
    else:
        print("[키워드개선/유튜브] 데이터 파일 없음 - 스킵")

    print(f"\n{'=' * 60}")
    print(f"[키워드 재시도] 완료 - 총 {total_updated}개 키워드 개선")
    print(f"{'=' * 60}")

    return total_updated


if __name__ == "__main__":
    main()
