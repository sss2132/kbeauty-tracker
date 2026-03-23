"""
YouTube Data API v3 - K-Beauty 리뷰 영상 트렌드 조회
API 키가 없으면 샘플 데이터로 폴백.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import YOUTUBE_API_KEY, YOUTUBE_API_KEYS

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

# 키 로테이션: 할당량 초과(403) 시 다음 키로 전환
_current_key_idx = 0


def _get_key():
    """현재 활성 API 키 반환."""
    if not YOUTUBE_API_KEYS:
        return YOUTUBE_API_KEY
    return YOUTUBE_API_KEYS[_current_key_idx % len(YOUTUBE_API_KEYS)]


def _rotate_key():
    """다음 키로 전환. 전환 성공 시 True, 더 이상 없으면 False."""
    global _current_key_idx
    if len(YOUTUBE_API_KEYS) <= 1:
        return False
    _current_key_idx += 1
    if _current_key_idx >= len(YOUTUBE_API_KEYS):
        return False  # 모든 키 소진
    print(f"    [KEY ROTATE] 키 #{_current_key_idx + 1}로 전환")
    return True


def _api_get(url, params):
    """API 호출 + 403 시 키 로테이션 후 재시도."""
    params["key"] = _get_key()
    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code == 403 and _rotate_key():
        params["key"] = _get_key()
        resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def search_videos(keyword, published_after, max_results=10):
    """YouTube 검색 API로 최근 영상 조회"""
    params = {
        "part": "snippet",
        "q": keyword,
        "type": "video",
        "order": "date",
        "publishedAfter": published_after,
        "maxResults": max_results,
        "relevanceLanguage": "ko",
    }
    return _api_get(SEARCH_URL, params)


def get_video_stats(video_ids):
    """영상 통계(조회수 등) 조회"""
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part": "statistics",
        "id": ",".join(video_ids),
    }
    return _api_get(url, params)


def fetch_keyword_trend(keyword):
    """키워드별 최근 2주 영상 수/조회수 비교"""
    now = datetime.utcnow()
    this_week_start = (now - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z")
    last_week_start = (now - timedelta(days=14)).strftime("%Y-%m-%dT00:00:00Z")
    last_week_end = (now - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z")

    try:
        # 이번 주 영상
        this_data = search_videos(keyword, this_week_start, 20)
        this_ids = [item["id"]["videoId"] for item in this_data.get("items", [])]
        this_views = 0
        if this_ids:
            stats = get_video_stats(this_ids)
            for item in stats.get("items", []):
                this_views += int(item["statistics"].get("viewCount", 0))

        # 지난 주 영상
        last_data = search_videos(keyword, last_week_start, 20)
        last_items = [item for item in last_data.get("items", [])
                      if item["snippet"]["publishedAt"] < last_week_end]
        last_ids = [item["id"]["videoId"] for item in last_items]
        last_views = 0
        if last_ids:
            stats = get_video_stats(last_ids)
            for item in stats.get("items", []):
                last_views += int(item["statistics"].get("viewCount", 0))

        video_count = len(this_ids)
        total_views = this_views
        video_count_last_week = len(last_ids)
        total_views_last_week = last_views

        if last_views == 0:
            change_rate = 100.0 if this_views > 0 else 0.0
        else:
            change_rate = round((this_views - last_views) / last_views * 100, 1)

        return video_count, total_views, video_count_last_week, total_views_last_week, change_rate

    except requests.RequestException as e:
        print(f"    [API ERROR] {e}")
        return -1, -1, -1, -1, 0.0  # -1 = API 에러 (정상 0과 구분)


def fetch_3month_video_count(keyword):
    """키워드의 최근 3개월 영상 수 조회 (totalResults 사용)"""
    now = datetime.utcnow()
    three_months_ago = (now - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00Z")
    try:
        params = {
            "part": "snippet",
            "q": keyword,
            "type": "video",
            "publishedAfter": three_months_ago,
            "maxResults": 1,  # totalResults만 필요
            "relevanceLanguage": "ko",
        }
        data = _api_get(SEARCH_URL, params)
        total = data.get("pageInfo", {}).get("totalResults", 0)
        return total
    except requests.RequestException as e:
        print(f"    [6M API ERROR] {e}")
        return -1


def _load_keyword_map(today):
    """Claude가 생성한 키워드 파일이 있으면 로드."""
    kw_path = os.path.join(DATA_DIR, f"_keywords_{today}.json")
    if not os.path.exists(kw_path):
        return {}
    with open(kw_path, "r", encoding="utf-8") as f:
        kw_list = json.load(f)
    return {k["product_code"]: k for k in kw_list}


def run_with_api(products):
    """실제 API로 유튜브 데이터 수집"""
    print(f"[유튜브] API 모드 - {len(products)}개 제품 조회 시작")
    today = datetime.now().strftime("%Y%m%d")
    keyword_map = _load_keyword_map(today)
    if keyword_map:
        print(f"[유튜브] Claude 키워드 사용 ({len(keyword_map)}개)")
    results = []
    api_errors = []

    # 키워드 파일이 있으면 해당 제품만 처리 (Claude가 비화장품 제외 + 50개 선별)
    if keyword_map:
        products = [p for p in products if p["product_code"] in keyword_map]
        print(f"[유튜브] 키워드 파일 기준 {len(products)}개 처리")
    else:
        products = products[:50]
        print(f"[유튜브] 키워드 파일 없음 - Top {len(products)}개 처리")

    for i, product in enumerate(products):
        pc = product["product_code"]
        if pc in keyword_map:
            keyword = keyword_map[pc]["youtube_keyword"]
        else:
            keyword = product.get("search_keyword",
                                  product.get("brand_en", product["brand"]) + " " + product["name"])
        print(f"  [{i+1}/{len(products)}] {keyword}...", end=" ")

        video_count, total_views, vc_lw, tv_lw, change_rate = fetch_keyword_trend(keyword)
        api_error = video_count == -1
        yt_available = (not api_error) and video_count >= 3
        results.append({
            "product_code": product["product_code"],
            "keyword": keyword,
            "video_count": video_count,
            "total_views": total_views if yt_available else None,
            "video_count_last_week": vc_lw,
            "total_views_last_week": tv_lw,
            "change_rate": change_rate if yt_available else None,
            "youtube_available": yt_available,
            "api_error": api_error,
        })
        if api_error:
            flag = " [API ERROR]"
            api_errors.append(keyword)
        elif not yt_available:
            flag = " [SKIP: <3 videos]"
        else:
            flag = ""
        print(f"videos:{video_count} views:{total_views} change:{change_rate:+.1f}%{flag}")
        time.sleep(0.2)

    # Phase 2: 3개월 영상 수 조회 (hidden_gem 후보만 — steady_seller 판정용)
    # 최근 2주 영상 < 3인 제품만 대상 (이 제품들이 hidden_gem/steady_seller 후보)
    candidates = [r for r in results if not r["youtube_available"] and not r["api_error"]]
    print(f"\n[유튜브] 3개월 영상 수 조회 ({len(candidates)}개 hidden_gem 후보)")
    for i, r in enumerate(candidates):
        keyword = r["keyword"]
        print(f"  [{i+1}/{len(candidates)}] {keyword} 3M...", end=" ")
        count_3m = fetch_3month_video_count(keyword)
        r["video_count_3month"] = count_3m
        if count_3m == -1:
            print("[API ERROR]")
        else:
            print(f"{count_3m} videos")
        time.sleep(0.2)

    if api_errors:
        print(f"\n[경고] API 에러 {len(api_errors)}건: {', '.join(api_errors[:5])}")

    return results, api_errors


def run_with_sample():
    """API 키 없음 - 샘플 데이터 사용"""
    sample_path = os.path.join(DATA_DIR, "youtube_sample.json")
    if not os.path.exists(sample_path):
        print("[유튜브] 오류: youtube_sample.json 없음")
        return []

    with open(sample_path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    today = datetime.now().strftime("%Y%m%d")
    output_path = os.path.join(DATA_DIR, f"youtube_{today}.json")

    # 올리브영 데이터 로드 (최신 dated 파일 우선, 없으면 sample)
    import glob as _glob
    oy_files = sorted(_glob.glob(os.path.join(DATA_DIR, "oliveyoung_*.json")))
    oy_files = [f for f in oy_files if "sample" not in os.path.basename(f) and "keywords" not in os.path.basename(f)]
    if oy_files:
        oy_path = oy_files[-1]
    else:
        oy_path = os.path.join(DATA_DIR, "oliveyoung_sample.json")
    if not os.path.exists(oy_path):
        print("[유튜브] 오류: 올리브영 데이터 없음")
        return

    with open(oy_path, "r", encoding="utf-8") as f:
        products = json.load(f)
    print(f"[유튜브] OY 데이터: {os.path.basename(oy_path)}")

    if YOUTUBE_API_KEY:
        print("[유튜브] API 키 확인됨")
        results, api_errors = run_with_api(products)
        if api_errors:
            error_msg = f"[유튜브 API 에러] {len(api_errors)}건 발생: {', '.join(api_errors[:10])}"
            print(error_msg)
            # run_daily_collect.py에서 이 반환값으로 텔레그램 알림 전송
            with open(os.path.join(DATA_DIR, "_youtube_api_errors.txt"), "w", encoding="utf-8") as ef:
                ef.write("\n".join(api_errors))
        # API가 전부 0 반환 시 dated 파일 미생성 (sample 폴백)
        has_data = any((r.get("total_views") or 0) > 0 for r in results)
        if not has_data:
            print("[유튜브] API 결과 없음 - dated 파일 미생성, sample 사용")
            return output_path
    else:
        print("[유튜브] API 키 없음 - 샘플 데이터 사용")
        results = run_with_sample()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"[유튜브] 저장 완료: {output_path} ({len(results)}개)")
    return output_path


if __name__ == "__main__":
    main()
