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
from config import YOUTUBE_API_KEY

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


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
        "key": YOUTUBE_API_KEY,
    }
    resp = requests.get(SEARCH_URL, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_video_stats(video_ids):
    """영상 통계(조회수 등) 조회"""
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part": "statistics",
        "id": ",".join(video_ids),
        "key": YOUTUBE_API_KEY,
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


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
        print(f"    API 오류: {e}")
        return 0, 0, 0, 0, 0.0


def run_with_api(products):
    """실제 API로 유튜브 데이터 수집"""
    print(f"[유튜브] API 모드 - {len(products)}개 제품 조회 시작")
    results = []

    for i, product in enumerate(products):
        keyword = product.get("search_keyword",
                              product.get("brand_en", product["brand"]) + " " + product["name"])
        print(f"  [{i+1}/{len(products)}] {keyword}...", end=" ")

        video_count, total_views, vc_lw, tv_lw, change_rate = fetch_keyword_trend(keyword)
        yt_available = video_count >= 3
        results.append({
            "product_code": product["product_code"],
            "keyword": keyword,
            "video_count": video_count,
            "total_views": total_views if yt_available else None,
            "video_count_last_week": vc_lw,
            "total_views_last_week": tv_lw,
            "change_rate": change_rate if yt_available else None,
            "youtube_available": yt_available,
        })
        flag = "" if yt_available else " [SKIP: <3 videos]"
        print(f"videos:{video_count} views:{total_views} change:{change_rate:+.1f}%{flag}")
        time.sleep(0.2)

    return results


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
    oy_files = [f for f in oy_files if "sample" not in os.path.basename(f)]
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
        results = run_with_api(products)
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
