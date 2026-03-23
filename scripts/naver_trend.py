"""
네이버 쇼핑 트렌드 API -제품별 검색량 추이 조회
API 키가 없으면 샘플 데이터로 폴백.
"""

import json
import os
import shutil
import sys
import time
from datetime import datetime, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
API_URL = "https://openapi.naver.com/v1/datalab/shopping/category/keywords"

# 네이버 쇼핑 카테고리 코드 (화장품/미용)
CATEGORY_CODE = "50000002"

KEYWORD_MAP = {
    "skincare": "{brand} {short}",
    "makeup": "{brand} {short}",
    "suncare": "{brand} 선크림",
    "maskpack": "{brand} 마스크팩",
    "haircare": "{brand} {short}",
    "bodycare": "{brand} {short}",
}


def make_keyword(product):
    """제품 정보에서 네이버 검색 키워드 생성 - 핵심 단어만 추출"""
    brand = product["brand"]
    name = product["name"]
    import re
    # 용량, 기획, 특수문자 등 제거
    short = re.sub(r"\d+\s*(ml|g|매입|매|개입|개|ea)\b", "", name, flags=re.IGNORECASE).strip()
    short = re.sub(r"\d+\+\d+/?", "", short).strip()  # 10+1/ 등
    short = re.sub(r"\(.*?\)", "", short).strip()  # 괄호 내용
    short = re.sub(r"[/+]$", "", short).strip()  # 후행 / +
    # 핵심 2단어만 (브랜드 + 2단어 = 충분한 검색 정밀도)
    words = short.split()
    if len(words) > 2:
        short = " ".join(words[:2])
    return f"{brand} {short}".strip()


def fetch_trend(keyword, weeks=4):
    """네이버 쇼핑 트렌드 API 호출 -최근 N주 검색량 비율 조회"""
    end_date = datetime.now()
    start_date = end_date - timedelta(weeks=weeks)

    body = {
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": end_date.strftime("%Y-%m-%d"),
        "timeUnit": "week",
        "category": CATEGORY_CODE,
        "keyword": [{"name": keyword, "param": [keyword]}],
    }

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json",
    }

    resp = requests.post(API_URL, headers=headers, json=body, timeout=10)
    resp.raise_for_status()
    return resp.json()


def calc_change_rate(data):
    """API 응답에서 전주 대비 변화율 계산"""
    results = data.get("results", [])
    if not results:
        return 0, 0, 0.0

    periods = results[0].get("data", [])
    if len(periods) < 2:
        return 0, 0, 0.0

    this_week = periods[-1].get("ratio", 0)
    last_week = periods[-2].get("ratio", 0)

    if last_week == 0:
        rate = 100.0 if this_week > 0 else 0.0
    else:
        rate = round((this_week - last_week) / last_week * 100, 1)

    return this_week, last_week, rate


def _load_keyword_map(today):
    """Claude가 생성한 키워드 파일이 있으면 로드."""
    kw_path = os.path.join(DATA_DIR, f"_keywords_{today}.json")
    if not os.path.exists(kw_path):
        return {}
    with open(kw_path, "r", encoding="utf-8") as f:
        kw_list = json.load(f)
    return {k["product_code"]: k for k in kw_list}


def run_with_api(products):
    """실제 API로 네이버 데이터 수집"""
    print(f"[네이버] API 모드 -{len(products)}개 제품 조회 시작")
    today = datetime.now().strftime("%Y%m%d")
    keyword_map = _load_keyword_map(today)
    # 키워드 파일이 있으면 해당 제품만 처리 (Claude가 비화장품 제외 + 50개 선별)
    if keyword_map:
        products = [p for p in products if p["product_code"] in keyword_map]
        print(f"[네이버] Claude 키워드 기준 {len(products)}개 처리")
    results = []

    for i, product in enumerate(products):
        pc = product["product_code"]
        if pc in keyword_map:
            keyword = keyword_map[pc]["naver_keyword"]
        else:
            keyword = make_keyword(product)
        print(f"  [{i+1}/{len(products)}] {keyword}...", end=" ")

        try:
            data = fetch_trend(keyword)
            this_week, last_week, change_rate = calc_change_rate(data)
            results.append({
                "product_code": product["product_code"],
                "keyword": keyword,
                "search_volume": this_week,
                "search_volume_last_week": last_week,
                "change_rate": change_rate,
            })
            print(f"변화율 {change_rate:+.1f}%")
        except requests.RequestException as e:
            print(f"실패 ({e})")
            results.append({
                "product_code": product["product_code"],
                "keyword": keyword,
                "search_volume_this_week": 0,
                "search_volume_last_week": 0,
                "change_rate": 0.0,
            })

        time.sleep(0.5)

    return results


def run_with_sample():
    """API 키 없음 -샘플 데이터 사용"""
    sample_path = os.path.join(DATA_DIR, "naver_sample.json")
    if not os.path.exists(sample_path):
        print("[네이버] 오류: naver_sample.json 없음")
        return []

    with open(sample_path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    today = datetime.now().strftime("%Y%m%d")
    output_path = os.path.join(DATA_DIR, f"naver_{today}.json")

    # 올리브영 데이터 로드 (최신 dated 파일 우선, 없으면 sample)
    import glob as _glob
    oy_files = sorted(_glob.glob(os.path.join(DATA_DIR, "oliveyoung_*.json")))
    oy_files = [f for f in oy_files if "sample" not in os.path.basename(f) and "keywords" not in os.path.basename(f)]
    if oy_files:
        oy_path = oy_files[-1]
    else:
        oy_path = os.path.join(DATA_DIR, "oliveyoung_sample.json")
    if not os.path.exists(oy_path):
        print("[네이버] 오류: 올리브영 데이터 없음")
        return

    with open(oy_path, "r", encoding="utf-8") as f:
        products = json.load(f)
    print(f"[네이버] OY 데이터: {os.path.basename(oy_path)}")

    # API 키 확인
    if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET:
        print("[네이버] API 키 확인됨")
        results = run_with_api(products)
        # API가 전부 0 반환 시 dated 파일 미생성 (sample 폴백)
        has_data = any(r.get("search_volume", r.get("search_volume_this_week", 0)) > 0 for r in results)
        if not has_data:
            print("[네이버] API 결과 없음 - dated 파일 미생성, sample 사용")
            return output_path
    else:
        print("[네이버] API 키 없음 - 샘플 데이터 사용")
        results = run_with_sample()

    # 저장
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"[네이버] 저장 완료: {output_path} ({len(results)}개)")
    return output_path


if __name__ == "__main__":
    main()
