"""
네이버 쇼핑 트렌드 API - 배치 비교 방식으로 제품별 검색량 조회
기준 키워드를 모든 배치에 포함시켜 제품 간 상대적 비교 가능.
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

# 기준 키워드: 모든 배치에 포함되어 제품 간 비교 기준점 역할
# 꾸준한 검색량이 있는 제품을 선택 (0이 되면 정규화 불가)
REF_KEYWORD = "라운드랩 선크림"

BATCH_SIZE = 4  # 기준 1개 + 제품 4개 = API 최대 5개


def make_keyword(product):
    """제품 정보에서 네이버 검색 키워드 생성 - 핵심 단어만 추출"""
    brand = product["brand"]
    name = product["name"]
    import re
    short = re.sub(r"\d+\s*(ml|g|매입|매|개입|개|ea)\b", "", name, flags=re.IGNORECASE).strip()
    short = re.sub(r"\d+\+\d+/?", "", short).strip()
    short = re.sub(r"\(.*?\)", "", short).strip()
    short = re.sub(r"[/+]$", "", short).strip()
    words = short.split()
    if len(words) > 2:
        short = " ".join(words[:2])
    return f"{brand} {short}".strip()


def fetch_batch(keywords, weeks=4):
    """여러 키워드를 한 번에 조회 (최대 5개). 같은 스케일로 비교 가능."""
    end_date = datetime.now()
    start_date = end_date - timedelta(weeks=weeks)

    body = {
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": end_date.strftime("%Y-%m-%d"),
        "timeUnit": "week",
        "category": CATEGORY_CODE,
        "keyword": [{"name": kw, "param": [kw]} for kw in keywords],
    }

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json",
    }

    resp = requests.post(API_URL, headers=headers, json=body, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    result = {}
    for r in data.get("results", []):
        title = r.get("title", "")
        periods = r.get("data", [])
        if len(periods) >= 2:
            this_week = periods[-1].get("ratio", 0)
            last_week = periods[-2].get("ratio", 0)
        elif len(periods) == 1:
            this_week = periods[0].get("ratio", 0)
            last_week = 0
        else:
            this_week = 0
            last_week = 0
        result[title] = {"this_week": this_week, "last_week": last_week}
    return result


def _load_keyword_map(today):
    """Claude가 생성한 키워드 파일이 있으면 로드."""
    kw_path = os.path.join(DATA_DIR, f"_keywords_{today}.json")
    if not os.path.exists(kw_path):
        return {}
    with open(kw_path, "r", encoding="utf-8") as f:
        kw_list = json.load(f)
    return {k["product_code"]: k for k in kw_list}


def run_with_api(products):
    """배치 비교 방식으로 네이버 데이터 수집.
    기준 키워드를 모든 배치에 포함시켜 제품 간 상대적 비교 가능."""
    print(f"[네이버] 배치 비교 모드 - {len(products)}개 제품 조회 시작")
    print(f"[네이버] 기준 키워드: '{REF_KEYWORD}'")
    today = datetime.now().strftime("%Y%m%d")
    keyword_map = _load_keyword_map(today)

    if keyword_map:
        products = [p for p in products if p["product_code"] in keyword_map]
        print(f"[네이버] Claude 키워드 기준 {len(products)}개 처리")

    # 키워드 리스트 구성
    kw_list = []
    for product in products:
        pc = product["product_code"]
        if pc in keyword_map:
            keyword = keyword_map[pc]["naver_keyword"]
        else:
            keyword = make_keyword(product)
        kw_list.append((pc, keyword))

    # 배치 구성: 기준 1개 + 제품 4개씩
    batches = [kw_list[i:i + BATCH_SIZE] for i in range(0, len(kw_list), BATCH_SIZE)]
    all_results = {}

    for batch_idx, batch in enumerate(batches):
        batch_keywords = [REF_KEYWORD] + [kw for _, kw in batch]
        print(f"  [{batch_idx + 1}/{len(batches)}] {len(batch)}개 + 기준...", end=" ")

        try:
            result = fetch_batch(batch_keywords)

            ref_data = result.get(REF_KEYWORD, {"this_week": 0, "last_week": 0})
            ref_this = ref_data["this_week"]
            ref_last = ref_data["last_week"]

            for code, kw in batch:
                prod_data = result.get(kw, {"this_week": 0, "last_week": 0})
                norm_this = round(prod_data["this_week"] / ref_this * 100, 2) if ref_this > 0 else 0
                norm_last = round(prod_data["last_week"] / ref_last * 100, 2) if ref_last > 0 else 0
                all_results[code] = {
                    "keyword": kw,
                    "normalized_this": norm_this,
                    "normalized_last": norm_last,
                }

            print("OK")
        except requests.RequestException as e:
            print(f"실패 ({e})")
            for code, kw in batch:
                all_results[code] = {
                    "keyword": kw,
                    "normalized_this": 0,
                    "normalized_last": 0,
                }

        time.sleep(0.5)

    # 결과 조립
    results = []
    for pc, kw in kw_list:
        r = all_results.get(pc, {"keyword": kw, "normalized_this": 0, "normalized_last": 0})
        norm_this = r["normalized_this"]
        norm_last = r["normalized_last"]

        if norm_last == 0:
            change_rate = 100.0 if norm_this > 0 else 0.0
        else:
            change_rate = round((norm_this - norm_last) / norm_last * 100, 1)

        results.append({
            "product_code": pc,
            "keyword": r["keyword"],
            "search_volume": norm_this,
            "search_volume_last_week": norm_last,
            "change_rate": change_rate,
        })

    api_calls = len(batches)
    print(f"[네이버] 완료: {len(results)}개 제품, {api_calls}회 API 호출 (기준: {REF_KEYWORD} = 100)")
    return results


def run_with_sample():
    """API 키 없음 - 샘플 데이터 사용"""
    sample_path = os.path.join(DATA_DIR, "samples", "naver_sample.json")
    if not os.path.exists(sample_path):
        print("[네이버] 오류: naver_sample.json 없음")
        return []

    with open(sample_path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    today = datetime.now().strftime("%Y%m%d")
    output_path = os.path.join(DATA_DIR, f"naver_{today}.json")

    import glob as _glob
    oy_files = sorted(_glob.glob(os.path.join(DATA_DIR, "oliveyoung_*.json")))
    oy_files = [f for f in oy_files if "sample" not in os.path.basename(f) and "keywords" not in os.path.basename(f)]
    if oy_files:
        oy_path = oy_files[-1]
    else:
        oy_path = os.path.join(DATA_DIR, "samples", "oliveyoung_sample.json")
    if not os.path.exists(oy_path):
        print("[네이버] 오류: 올리브영 데이터 없음")
        return

    with open(oy_path, "r", encoding="utf-8") as f:
        products = json.load(f)
    print(f"[네이버] OY 데이터: {os.path.basename(oy_path)}")

    if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET:
        print("[네이버] API 키 확인됨")
        results = run_with_api(products)
        has_data = any(r.get("search_volume", 0) > 0 for r in results)
        if not has_data:
            print("[네이버] API 결과 없음 - dated 파일 미생성, sample 사용")
            return output_path
    else:
        print("[네이버] API 키 없음 - 샘플 데이터 사용")
        results = run_with_sample()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"[네이버] 저장 완료: {output_path} ({len(results)}개)")
    return output_path


if __name__ == "__main__":
    main()
