"""
K-Beauty Trend Tracker - 종합 트렌드 점수 계산기 v6
3소스 체계: OY 45% + NS 30% + YT 25%
로그 스케일 정규화 + 상위 보너스.
Buzz Trap / Hidden Gem / RISING 감지.

v6 변경:
- 매일 독립 스코어 → 구간 평균 방식
- 전체 구간에서 한 번이라도 등장한 모든 제품 포함
- 동일 search_keyword 중복 병합은 하루 내에서만 수행
- 비화장품 카테고리 필터 전 단계 적용
"""

import glob
import json
import math
import os
import sys
from collections import OrderedDict
from datetime import datetime, timedelta

from config import make_affiliate_url, PROMOTION_PENALTY

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DAILY_DIR = os.path.join(DATA_DIR, "daily")

DEFAULT_WEIGHTS = {
    "oliveyoung": 0.45,
    "naver_search": 0.30,
    "youtube": 0.25,
}

TOP_N = 30
PERIOD_DAYS = 3


def calc_oliveyoung_score(rank, review_count):
    base = max(0, 102 - rank * 2)
    if review_count >= 10000:
        bonus = 10
    elif review_count >= 5000:
        bonus = 5
    else:
        bonus = 0
    return min(100, base + bonus)


def log_normalize_with_bonus(values):
    """로그 정규화 + 상위 보너스."""
    if not values:
        return []
    log_values = [math.log(v + 1) if v > 0 else 0 for v in values]
    min_val = min(log_values)
    max_val = max(log_values)
    if max_val == min_val:
        return [50] * len(values)
    normalized = [(v - min_val) / (max_val - min_val) * 85 for v in log_values]

    sorted_indices = sorted(range(len(values)), key=lambda i: values[i], reverse=True)
    bonuses = {}
    for idx, bonus in zip(sorted_indices[:5], [15, 10, 7, 4, 2]):
        bonuses[idx] = bonus

    return [min(100, round(normalized[i] + bonuses.get(i, 0))) for i in range(len(values))]


def calc_youtube_bonus(video_count):
    return 10 if video_count >= 30 else 0


def compute_active_weights(data_status):
    available = {k: v for k, v in DEFAULT_WEIGHTS.items()
                 if data_status.get(k, {}).get("available", False)}
    if not available:
        return {"oliveyoung": 1.0}
    total = sum(available.values())
    return {k: round(v / total, 2) for k, v in available.items()}


def calc_total_score(scores, weights):
    total = 0
    for source, weight in weights.items():
        total += scores.get(source, 0) * weight
    return round(total)


def detect_flags(scores, video_count_3month=0, consecutive_periods=0):
    flags = []
    oy = scores.get("oliveyoung", 0)
    ns = scores.get("naver_search", 0)
    yt = scores.get("youtube", 0)
    social = max(ns, yt)
    if social > 70 and oy < 40:
        flags.append("buzz_trap")
    if oy > 70 and ns < 30 and yt < 30:
        # steady_seller vs hidden_gem 구분
        # TODO: 데이터 축적 후 consecutive_periods 기반으로 steady_seller 판정 추가
        is_steady = consecutive_periods >= 10
        if is_steady:
            flags.append("steady_seller")
        else:
            flags.append("hidden_gem")
    return flags


def seller_note(scores, flags):
    parts = []
    oy = scores.get("oliveyoung", 0)
    ns = scores.get("naver_search", 0)
    if oy >= 90:
        parts.append("OY TOP5")
    elif oy >= 70:
        parts.append("OY TOP15")
    if ns >= 75:
        parts.append("search rising")
    elif ns < 40:
        parts.append("search low")
    if "buzz_trap" in flags:
        parts.append("BUZZ TRAP")
    if "hidden_gem" in flags:
        parts.append("hidden gem")
    if "steady_seller" in flags:
        parts.append("steady seller")
    return " / ".join(parts)


def seller_grade(total, flags):
    if "buzz_trap" in flags:
        return "hold"
    if total >= 80 and "hidden_gem" in flags:
        return "source_now"
    if "steady_seller" in flags:
        return "proven"
    if 60 <= total <= 79:
        return "watch"
    return ""


def load_json(pattern_or_name):
    """Load latest dated JSON or fall back to sample."""
    if "*" in pattern_or_name:
        files = sorted(glob.glob(os.path.join(DATA_DIR, pattern_or_name)))
        files = [f for f in files if "sample" not in os.path.basename(f)]
        if files:
            with open(files[-1], "r", encoding="utf-8") as f:
                return json.load(f), True
    sample = os.path.join(DATA_DIR, "samples", pattern_or_name.replace("_*.json", "_sample.json"))
    if os.path.exists(sample):
        with open(sample, "r", encoding="utf-8") as f:
            return json.load(f), False
    return [], False


# ── 3일 구간 관련 함수 ──

def get_daily_dates():
    """data/daily/ 폴더에서 oliveyoung 파일이 있는 날짜 목록 반환 (정렬됨)."""
    if not os.path.isdir(DAILY_DIR):
        return []
    dates = []
    for folder in sorted(os.listdir(DAILY_DIR)):
        folder_path = os.path.join(DAILY_DIR, folder)
        if not os.path.isdir(folder_path):
            continue
        oy_files = glob.glob(os.path.join(folder_path, "oliveyoung_*.json"))
        if oy_files:
            try:
                dates.append(datetime.strptime(folder, "%Y-%m-%d").date())
            except ValueError:
                continue
    return sorted(dates)


def compute_periods(dates):
    """고정 3일 구간 계산. 첫 날짜 기준으로 겹치지 않는 구간."""
    if not dates:
        return []
    start = dates[0]
    periods = []
    current_start = start
    while current_start <= dates[-1]:
        current_end = current_start + timedelta(days=PERIOD_DAYS - 1)
        period_dates = [d for d in dates if current_start <= d <= current_end]
        if len(period_dates) == PERIOD_DAYS:
            periods.append({
                "start": current_start,
                "end": current_end,
                "dates": period_dates,
            })
        current_start = current_end + timedelta(days=1)
    return periods


def load_daily_oliveyoung(date_obj):
    """특정 날짜의 oliveyoung JSON 로드."""
    folder = date_obj.strftime("%Y-%m-%d")
    folder_path = os.path.join(DAILY_DIR, folder)
    files = glob.glob(os.path.join(folder_path, "oliveyoung_*.json"))
    if not files:
        return []
    with open(files[0], "r", encoding="utf-8") as f:
        return json.load(f)


def load_daily_data(date_obj, source_prefix):
    """특정 날짜의 데이터 JSON 로드."""
    folder = date_obj.strftime("%Y-%m-%d")
    folder_path = os.path.join(DAILY_DIR, folder)
    files = glob.glob(os.path.join(folder_path, f"{source_prefix}_*.json"))
    if not files:
        return []
    with open(files[0], "r", encoding="utf-8") as f:
        return json.load(f)


def compute_period_oy_scores(period):
    """3일 구간의 올리브영 평균 점수 계산 (프로모션 패널티 적용)."""
    product_scores = {}  # product_code -> list of scores
    product_info = {}    # product_code -> latest product info

    for date_obj in period["dates"]:
        oy_data = load_daily_oliveyoung(date_obj)
        for item in oy_data:
            code = item["product_code"]
            score = calc_oliveyoung_score(item["rank"], item.get("review_count", 0))

            # 오특 패널티
            if item.get("is_promotion", item.get("is_oteuk", False)):
                score = score * PROMOTION_PENALTY

            if code not in product_scores:
                product_scores[code] = []
            product_scores[code].append(score)
            product_info[code] = item  # 최신 정보 유지

    # 3일 평균
    avg_scores = {}
    for code, scores in product_scores.items():
        avg_scores[code] = round(sum(scores) / len(scores))

    return avg_scores, product_info


def load_previous_ranking(current_date_str):
    """이전 주기 weekly_ranking 파일 탐색."""
    files = sorted(glob.glob(os.path.join(DATA_DIR, "weekly_ranking_*.json")))
    files = [f for f in files if current_date_str not in os.path.basename(f)]
    if not files:
        return None
    with open(files[-1], "r", encoding="utf-8") as f:
        return json.load(f)


def compute_rank_changes(products_top, prev_data):
    """이전 회차 데이터와 비교하여 rank_change 계산."""
    if not prev_data:
        for p in products_top:
            p["rank_change"] = "NEW"
        return [], len(products_top)

    prev_map = {}
    for p in prev_data.get("products", []):
        prev_map[p["product_code"]] = p["rank"]

    new_count = 0
    for p in products_top:
        code = p["product_code"]
        if code in prev_map:
            diff = prev_map[code] - p["rank"]
            if diff > 0:
                p["rank_change"] = f"+{diff}"
            elif diff < 0:
                p["rank_change"] = str(diff)
            else:
                p["rank_change"] = "0"
        else:
            p["rank_change"] = "NEW"
            new_count += 1

    current_codes = {p["product_code"] for p in products_top}
    dropped = []
    for p in prev_data.get("products", []):
        if p["product_code"] not in current_codes:
            dropped.append({
                "rank": p["rank"],
                "brand": p["brand"],
                "brand_en": p.get("brand_en", ""),
                "name_ko": p["name_ko"],
                "scores": p["scores"],
                "product_code": p["product_code"],
            })

    return dropped, new_count


def compute_consecutive_periods(product_code, periods, all_period_rankings):
    """현재 구간까지 연속 TOP 30 구간 수 계산."""
    count = 0
    for period_ranking in reversed(all_period_rankings):
        top_codes = {p["product_code"] for p in period_ranking[:TOP_N]}
        if product_code in top_codes:
            count += 1
        else:
            break
    return count


def compute_consistency_bonus(consecutive_periods):
    """연속 유지 보너스 계산."""
    if consecutive_periods >= 4:
        return 8
    elif consecutive_periods >= 3:
        return 5
    elif consecutive_periods >= 2:
        return 3
    return 0


NON_COSMETIC_CATEGORIES = {"health", "food", "snack", "supplement", "medical", "other"}

NON_COSMETIC_KEYWORDS = [
    "단백질", "쉐이크", "베이글", "Album", "앨범", "치아미백", "칫솔",
    "구강", "비타민정", "영양제", "Mini Album",
]


def clean_product_name(name):
    """올리브영 원본 제품명에서 용량/기획/프로모션 텍스트를 제거하여 핵심 제품명만 추출.

    제거 대상: 용량(ml, g, 매, 입), 기획 텍스트(더블, 리필, 증정, 골라담기 등),
    수량 표현(N+N, N입, N종), 프로모션 괄호 내용
    유지 대상: 브랜드명 + 제품 라인명 + 제품 고유명
    """
    import re
    s = name.strip()
    # 대괄호 프로모션 제거 (앞쪽 [NEW], [오특] 등)
    s = re.sub(r'^\[.*?\]\s*', '', s)
    # 괄호 제거: 프로모션/옵션/기획 내용 (단, 제품 고유 괄호 아닌 것만)
    s = re.sub(r'\s*\([\+＋].*?\)', '', s)  # (+증정...), (+리필...)
    s = re.sub(r'\s*\([^)]*(?:기획|콜라보|단품|택\d+|수분/|진정/|종\s*중)[^)]*\)', '', s)
    # 뒤쪽 슬래시 옵션 제거 (벚꽃/더블/듀오, 본품+리필)
    s = re.sub(r'[/\s]+본품\+리필$', '', s)
    s = re.sub(r'\s+벚꽃/더블/듀오.*$', '', s)
    # 묶음 상품 정보 제거 (시카밤 B5++시카PRO마스크... 같은 패턴)
    s = re.sub(r'\+[^\s]*마스크.*$', '', s)
    s = re.sub(r'\+브러쉬.*$', '', s)
    # 더블기획, 듀오기획 등 (괄호 포함)
    s = re.sub(r'\s+더블기획(?:\([^)]*\))?', '', s)
    s = re.sub(r'\s+듀오기획(?:\([^)]*\))?', '', s)
    s = re.sub(r'\s+리필기획(?:\([^)]*\))?', '', s)
    # 용량 패턴 제거 (공백 있거나 바로 붙어있는 경우 모두)
    s = re.sub(r'\s*\d+(?:\.\d+)?(?:ml|ML|mL|g|G|mg|매|입|ea)\b', '', s)
    s = re.sub(r'/\d+(?:ml|ML|mL|g|G|매)\b', '', s)  # /10매, /50ml 등
    # N+N, N입, N개 등
    s = re.sub(r'\s+\d+\+\d+(?:매)?', '', s)
    s = re.sub(r'\s+\d+(?:입|개)\b', '', s)
    s = re.sub(r'\s+\d+종\s*(?:골라담기|택\s*\d+|중\s*택\s*\d+)?', '', s)
    # 기획/프로모션 키워드
    s = re.sub(r'\s+(?:더블|듀오|대용량|리필)?기획(?:세트)?(?:\s.*)?$', '', s)
    s = re.sub(r'\s+(?:더블|듀오)$', '', s)
    s = re.sub(r'\s+대용량$', '', s)
    s = re.sub(r'\s+중\s*택\d+$', '', s)
    # N매, NCOLOR 등 뒤쪽 수량
    s = re.sub(r'\s+\d+매$', '', s)
    s = re.sub(r'\s+\d+COLOR$', '', s)
    s = re.sub(r'\s+\d+colors?$', '', s, flags=re.IGNORECASE)
    # 증정 정보
    s = re.sub(r'\s*\+.*증정.*$', '', s)
    # 꼬리 정리: 뒤에 남은 "N+" 패턴 (7+1매에서 7+만 남는 경우)
    s = re.sub(r'\s+\d+\+$', '', s)
    s = re.sub(r'\s*/\s*$', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def is_non_cosmetic_by_keyword(product_name):
    """제품명에 비화장품 키워드가 포함되어 있는지 검사."""
    for kw in NON_COSMETIC_KEYWORDS:
        if kw in product_name:
            return True
    return False


def safe_print(text):
    """cp949 등 터미널 인코딩에서 깨지는 문자를 ? 로 대체하여 출력."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
            sys.stdout.encoding or "utf-8", errors="replace"
        ))


def compute_single_day_scores(date_obj, period_dates):
    """하루치 데이터로 독립적인 전체 스코어를 계산한다.

    Returns:
        dict: {search_keyword: {total, oliveyoung, naver_search, youtube,
               product_code, brand, brand_en, name_ko, search_keyword,
               category, ...metadata}} or None if no OY data
    """
    oy_data = load_daily_oliveyoung(date_obj)
    if not oy_data:
        return None

    # NV/YT: 해당 날짜 것 사용, 없으면 구간 내 최신 날짜 것 탐색
    nv_data = load_daily_data(date_obj, "naver")
    yt_data = load_daily_data(date_obj, "youtube")

    if not nv_data:
        for d in reversed(period_dates):
            if d != date_obj:
                nv_data = load_daily_data(d, "naver")
                if nv_data:
                    break
    if not yt_data:
        for d in reversed(period_dates):
            if d != date_obj:
                yt_data = load_daily_data(d, "youtube")
                if yt_data:
                    break

    nv_data = nv_data or []
    yt_data = yt_data or []

    nv_map = {item["product_code"]: item for item in nv_data}
    yt_map = {item["product_code"]: item for item in yt_data}

    # 비화장품 필터 (카테고리 + 키워드 블랙리스트)
    cosmetic_items = [oy for oy in oy_data
                      if oy.get("category", "") not in NON_COSMETIC_CATEGORIES
                      and not is_non_cosmetic_by_keyword(oy.get("name", ""))]
    if not cosmetic_items:
        return None

    # 정규화용 절대값 수집
    nv_volumes = []
    yt_views = []
    for oy in cosmetic_items:
        code = oy["product_code"]
        nv = nv_map.get(code, {})
        yt = yt_map.get(code, {})
        nv_volumes.append(nv.get("search_volume", nv.get("search_volume_this_week", 0)) or 0)
        yt_views.append(yt.get("total_views", 0) or 0)

    nv_norm = log_normalize_with_bonus(nv_volumes) if nv_data else [0] * len(cosmetic_items)
    yt_norm = log_normalize_with_bonus(yt_views) if yt_data else [0] * len(cosmetic_items)

    # data_status for weight computation
    data_status = {
        "oliveyoung": {"available": True},
        "naver_search": {"available": bool(nv_data)},
        "youtube": {"available": bool(yt_data)},
    }
    active_weights = compute_active_weights(data_status)

    # 제품별 스코어 계산
    day_products = {}  # product_code -> product dict
    for idx, oy in enumerate(cosmetic_items):
        code = oy["product_code"]
        nv = nv_map.get(code, {})
        yt = yt_map.get(code, {})

        oy_score = calc_oliveyoung_score(oy["rank"], oy.get("review_count", 0))
        if oy.get("is_promotion", oy.get("is_oteuk", False)):
            oy_score = round(oy_score * PROMOTION_PENALTY)

        nv_score = nv_norm[idx] if nv_data else 0

        yt_product_available = yt.get("youtube_available", True) if yt_data else False
        if yt_data and yt_product_available:
            yt_base = yt_norm[idx]
            yt_bonus = calc_youtube_bonus(yt.get("video_count", 0))
            yt_score = min(100, yt_base + yt_bonus)
            if yt.get("fallback_discount"):
                yt_score = round(yt_score * yt["fallback_discount"])
        else:
            yt_score = None

        if yt_score is not None:
            scores = {"oliveyoung": oy_score, "naver_search": nv_score, "youtube": yt_score}
            product_weights = active_weights
        else:
            scores = {"oliveyoung": oy_score, "naver_search": nv_score, "youtube": 0}
            oy_ns_total = DEFAULT_WEIGHTS["oliveyoung"] + DEFAULT_WEIGHTS["naver_search"]
            product_weights = {
                "oliveyoung": round(DEFAULT_WEIGHTS["oliveyoung"] / oy_ns_total, 2),
                "naver_search": round(DEFAULT_WEIGHTS["naver_search"] / oy_ns_total, 2),
                "youtube": 0,
            }

        total = calc_total_score(scores, product_weights)
        scores["total"] = total

        sk = oy.get("search_keyword", oy.get("brand_en", "") + " " + oy["name"])
        brand_en = oy.get("brand_en", "")

        day_products[code] = {
            "product_code": code,
            "search_keyword": sk,
            "brand": oy.get("brand", ""),
            "brand_en": brand_en,
            "name_ko": clean_product_name(oy.get("name", "")),
            "name": oy.get("name", ""),
            "category": oy.get("category", ""),
            "oliveyoung_rank": oy["rank"],
            "scores": scores,
            "youtube_available": yt_score is not None,
            "is_promotion": oy.get("is_promotion", oy.get("is_oteuk", False)),
            "url": oy.get("url", ""),
            "review_count": oy.get("review_count", 0),
            "naver_change_rate": nv.get("change_rate", None),
            "youtube_change_rate": yt.get("change_rate", yt.get("view_change_rate", None)),
            "nv_raw": nv,
            "yt_raw": yt,
        }

    # search_keyword 기준 중복 병합 (하루 내)
    # en_override의 영문명이 같은 제품도 동일 그룹으로 처리
    en_override_path = os.path.join(DATA_DIR, "english_names_override.json")
    _en_ov = {}
    if os.path.exists(en_override_path):
        with open(en_override_path, "r", encoding="utf-8") as f:
            _en_ov = json.load(f)
    # 영문명 → 대표 search_keyword 매핑 (동일 영문명 = 동일 제품)
    _en_to_sk = {}
    for code, p in day_products.items():
        en_name = _en_ov.get(code, "")
        if en_name and en_name in _en_to_sk:
            p["search_keyword"] = _en_to_sk[en_name]
        elif en_name:
            _en_to_sk[en_name] = p["search_keyword"]
    sk_groups = OrderedDict()
    for code, p in day_products.items():
        sk = p["search_keyword"]
        if sk not in sk_groups:
            sk_groups[sk] = []
        sk_groups[sk].append(p)

    merged = {}  # search_keyword -> merged product
    for sk, group in sk_groups.items():
        if len(group) == 1:
            merged[sk] = group[0]
            continue

        # 최고 순위(최저 rank) 제품을 primary로
        group.sort(key=lambda p: p["oliveyoung_rank"])
        primary = group[0].copy()
        primary["scores"] = dict(primary["scores"])
        extra_count = len(group) - 1
        oy_bonus = min(10, extra_count * 5)

        new_oy = min(100, primary["scores"]["oliveyoung"] + oy_bonus)
        primary["scores"]["oliveyoung"] = new_oy

        # 총점 재계산
        if primary.get("youtube_available"):
            pw = active_weights
        else:
            oy_ns_total = DEFAULT_WEIGHTS["oliveyoung"] + DEFAULT_WEIGHTS["naver_search"]
            pw = {
                "oliveyoung": round(DEFAULT_WEIGHTS["oliveyoung"] / oy_ns_total, 2),
                "naver_search": round(DEFAULT_WEIGHTS["naver_search"] / oy_ns_total, 2),
                "youtube": 0,
            }
        primary["scores"]["total"] = calc_total_score(primary["scores"], pw)

        primary["merged_from"] = [p["product_code"] for p in group]
        primary["merged_oy_ranks"] = [p["oliveyoung_rank"] for p in group]
        # 병합 시 가장 긴 name_ko를 사용 (올리브영이 축약 표기하는 경우 대비)
        longest_name = max((p.get("name_ko", "") for p in group), key=len)
        if len(longest_name) > len(primary.get("name_ko", "")):
            primary["name_ko"] = longest_name

        safe_print(f"  [{date_obj}] [병합] {sk}: OY rank {primary['merged_oy_ranks']} → 보너스 +{oy_bonus}")
        merged[sk] = primary

    return merged


def main(use_period=True):
    today = datetime.now()
    date_str = today.strftime("%Y%m%d")

    # ── 3일 구간 확인 ──
    daily_dates = get_daily_dates()
    periods = compute_periods(daily_dates)
    current_period = None
    all_period_rankings = []  # 각 구간별 정렬된 제품 리스트

    if use_period and periods:
        current_period = periods[-1]
        print(f"[calc] 구간 {len(periods)}개 감지, 현재 구간: {current_period['start']} ~ {current_period['end']}")
    elif use_period and daily_dates:
        # 3일치 안 모임
        latest_period_start = daily_dates[0]
        needed_end = latest_period_start + timedelta(days=PERIOD_DAYS - 1)
        collected = len(daily_dates)
        print(f"[calc] 데이터 수집 완료. 아직 {collected}일치. 사이트 갱신 안 함.")
        print(f"[calc] 다음 갱신: {PERIOD_DAYS}일치 모이면 ({needed_end} 이후)")
        return None

    # Load translations
    trans_path = os.path.join(DATA_DIR, "translations.json")
    translations = {}
    if os.path.exists(trans_path):
        with open(trans_path, "r", encoding="utf-8") as f:
            translations = json.load(f)

    # 영문명 override 로드 (사용자 확인된 영문명, 글로벌몰 매칭 실패분)
    en_override = {}
    override_path = os.path.join(DATA_DIR, "english_names_override.json")
    if os.path.exists(override_path):
        with open(override_path, "r", encoding="utf-8") as f:
            en_override = json.load(f)

    # 한글명 override 로드 (올리브영이 축약 표기한 제품의 공식 정식 이름)
    ko_override = {}
    ko_override_path = os.path.join(DATA_DIR, "korean_names_override.json")
    if os.path.exists(ko_override_path):
        with open(ko_override_path, "r", encoding="utf-8") as f:
            ko_override = json.load(f)

    # 키워드 맵 로드 (english_name 용)
    kw_map = {}
    kw_files = sorted(glob.glob(os.path.join(DATA_DIR, "_keywords_*.json")))
    if kw_files:
        try:
            with open(kw_files[-1], "r", encoding="utf-8") as f:
                kw_list = json.load(f)
                if isinstance(kw_list, list):
                    kw_map = {k["product_code"]: k for k in kw_list}
                elif isinstance(kw_list, dict) and "keywords" in kw_list:
                    kw_map = {k["product_code"]: k for k in kw_list["keywords"]}
        except (json.JSONDecodeError, KeyError):
            pass

    # 신제품 목록 로드 (daily 메타데이터에서)
    all_new_launches = set()
    for folder in sorted(os.listdir(DAILY_DIR)) if os.path.isdir(DAILY_DIR) else []:
        meta_path = os.path.join(DAILY_DIR, folder, "_collection_meta.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                for code in meta.get("new_launches", []):
                    all_new_launches.add(code)
            except (json.JSONDecodeError, KeyError):
                pass
    if all_new_launches:
        safe_print(f"[calc] 신제품 {len(all_new_launches)}개 감지")

    # ── v6: 매일 독립 스코어 → 평균 ──
    if current_period:
        period_dates = current_period["dates"]
        latest_date = period_dates[-1]

        # 각 날짜별 독립 스코어 계산
        daily_results = {}  # date -> {search_keyword -> product_with_scores}
        for d in period_dates:
            result = compute_single_day_scores(d, period_dates)
            if result:
                daily_results[d] = result
                print(f"[calc] {d}: {len(result)}개 제품 스코어 계산 완료")

        if not daily_results:
            print("[calc] 모든 날짜에 OY 데이터 없음. 중단.")
            return None

        num_days = len(period_dates)  # 구간 일수 (등장 안 한 날은 0점)

        # 전체 구간에서 한 번이라도 등장한 모든 search_keyword 수집
        all_keywords = set()
        for day_data in daily_results.values():
            all_keywords.update(day_data.keys())

        # 각 제품의 daily total 평균 계산
        averaged_products = {}  # search_keyword -> {avg scores + metadata}
        for sk in all_keywords:
            totals = []
            oy_scores = []
            nv_scores = []
            yt_scores = []
            latest_product = None

            for d in period_dates:
                day_data = daily_results.get(d, {})
                if sk in day_data:
                    p = day_data[sk]
                    totals.append(p["scores"]["total"])
                    oy_scores.append(p["scores"]["oliveyoung"])
                    nv_scores.append(p["scores"]["naver_search"])
                    yt_scores.append(p["scores"]["youtube"])
                    latest_product = p  # 가장 최신 날짜 데이터로 갱신
                else:
                    totals.append(0)
                    oy_scores.append(0)
                    nv_scores.append(0)
                    yt_scores.append(0)

            avg_total = round(sum(totals) / num_days)
            avg_oy = round(sum(oy_scores) / num_days)
            avg_nv = round(sum(nv_scores) / num_days)
            avg_yt = round(sum(yt_scores) / num_days)

            averaged_products[sk] = {
                "scores": {
                    "total": avg_total,
                    "oliveyoung": avg_oy,
                    "naver_search": avg_nv,
                    "youtube": avg_yt,
                },
                "product": latest_product,
                "days_appeared": sum(1 for t in totals if t > 0),
            }

        # 최신 날짜의 NV/YT/OY 데이터 (rising keywords, outside OY, data_status 용)
        oy_data = load_daily_oliveyoung(latest_date)
        nv_data = load_daily_data(latest_date, "naver") or []
        yt_data = load_daily_data(latest_date, "youtube") or []
        oy_real = True
        nv_real = bool(nv_data)
        yt_real = bool(yt_data)

    else:
        # 기존 방식 fallback (daily 폴더 없을 때)
        oy_data, oy_real = load_json("oliveyoung_*.json")
        if not oy_data:
            path = os.path.join(DATA_DIR, "samples", "oliveyoung_sample.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    oy_data = json.load(f)
                oy_real = False

        nv_data, nv_real = load_json("naver_*.json")
        yt_data, yt_real = load_json("youtube_*.json")

        # fallback: 단일 날짜로 compute_single_day_scores 사용 불가 → 직접 계산
        averaged_products = None

    # Build data_status
    data_status = {
        "oliveyoung": {
            "available": bool(oy_data),
            "product_count": len(oy_data),
            "source": "api" if oy_real else "sample",
        },
        "naver_search": {
            "available": bool(nv_data),
            "product_count": len([d for d in nv_data if not d.get("product_code", "").startswith("OUTSIDE")]),
            "source": "api" if nv_real else "sample",
        },
        "youtube": {
            "available": bool(yt_data),
            "product_count": len([d for d in yt_data if not d.get("product_code", "").startswith("OUTSIDE")]),
            "source": "api" if yt_real else "sample",
        },
    }

    if not nv_data:
        data_status["naver_search"]["reason"] = "API 키 없음 / 데이터 없음"
    if not yt_data:
        data_status["youtube"]["reason"] = "API 키 없음 / 데이터 없음"

    active_weights = compute_active_weights(data_status)
    print(f"[calc] active_weights: {active_weights}")

    nv_map = {item["product_code"]: item for item in nv_data}
    yt_map = {item["product_code"]: item for item in yt_data}
    oy_codes = {p["product_code"] for p in oy_data}

    # ── 제품 리스트 구성 ──
    all_products = []
    naver_rising = []
    youtube_rising = []
    translation_lines = []

    if averaged_products:
        # v6: 매일 스코어 평균 결과에서 제품 리스트 구성
        for sk, avg_data in averaged_products.items():
            p = avg_data["product"]  # 최신 날짜의 메타데이터
            code = p["product_code"]
            scores = avg_data["scores"]

            nv = nv_map.get(code, {})
            yt = yt_map.get(code, {})

            nv_change = nv.get("change_rate", p.get("naver_change_rate"))
            yt_change = yt.get("change_rate", yt.get("view_change_rate", p.get("youtube_change_rate")))

            yt_6m = yt.get("video_count_3month", 0)
            if yt_6m == -1:
                yt_6m = 0
            flags = detect_flags(scores, video_count_3month=yt_6m)
            grade = seller_grade(scores["total"], flags)
            note = seller_note(scores, flags)

            kw_entry = kw_map.get(code, {}) if kw_map else {}
            name_en_val = en_override.get(code) or kw_entry.get("english_name") or sk
            name_ko_val = ko_override.get(code) or p["name_ko"]

            product = {
                "rank": 0,
                "oliveyoung_rank": p["oliveyoung_rank"],
                "brand": p["brand"],
                "brand_en": p.get("brand_en", ""),
                "name_ko": name_ko_val,
                "name_en": name_en_val,
                "search_keyword": sk,
                "name_th": translations.get(code, {}).get("name_th", ""),
                "category": p["category"],
                "scores": scores,
                "naver_change_rate": nv_change,
                "youtube_change_rate": yt_change,
                "signal": "",
                "flags": flags,
                "seller_grade": grade,
                "rank_change": "0",
                "product_code": code,
                "oliveyoung_url": p.get("url", ""),
                "shopee_url": make_affiliate_url(name_en_val, platform="shopee"),
                "lazada_url": make_affiliate_url(name_en_val, platform="lazada"),
                "yesstyle_url": make_affiliate_url(name_en_val, platform="yesstyle"),
                "amazon_url": make_affiliate_url(name_en_val, platform="amazon"),
                "oliveyoung_global_url": make_affiliate_url("", product_code=code, platform="oliveyoung"),
                "seller_note": note,
                "youtube_available": p.get("youtube_available", False),
                "is_promotion": p.get("is_promotion", False),
                "is_new_launch": code in all_new_launches,
                "consecutive_periods": 0,
                "days_appeared": avg_data["days_appeared"],
            }
            if "merged_from" in p:
                product["merged_from"] = p["merged_from"]
                product["merged_oy_ranks"] = p["merged_oy_ranks"]

            all_products.append(product)
            translation_lines.append(f'{code}|{p.get("brand_en", "")}|{p.get("name", "")}')

            # rising keywords는 아래에서 순위 기반으로 계산

    else:
        # fallback: 기존 단일 데이터 방식 (daily 폴더 없을 때)
        cosmetic_items = [oy for oy in oy_data
                          if oy.get("category", "") not in NON_COSMETIC_CATEGORIES
                          and not is_non_cosmetic_by_keyword(oy.get("name", ""))]

        nv_volumes = []
        yt_views = []
        for oy in cosmetic_items:
            code = oy["product_code"]
            nv = nv_map.get(code, {})
            yt = yt_map.get(code, {})
            nv_volumes.append(nv.get("search_volume", nv.get("search_volume_this_week", 0)) or 0)
            yt_views.append(yt.get("total_views", 0) or 0)

        nv_norm = log_normalize_with_bonus(nv_volumes) if nv_data else [0] * len(cosmetic_items)
        yt_norm = log_normalize_with_bonus(yt_views) if yt_data else [0] * len(cosmetic_items)

        for idx, oy in enumerate(cosmetic_items):
            code = oy["product_code"]
            nv = nv_map.get(code, {})
            yt = yt_map.get(code, {})

            oy_score = calc_oliveyoung_score(oy["rank"], oy.get("review_count", 0))
            if oy.get("is_promotion", oy.get("is_oteuk", False)):
                oy_score = round(oy_score * PROMOTION_PENALTY)

            nv_score = nv_norm[idx] if nv_data else 0

            yt_product_available = yt.get("youtube_available", True) if yt_data else False
            if yt_data and yt_product_available:
                yt_base = yt_norm[idx]
                yt_bonus = calc_youtube_bonus(yt.get("video_count", 0))
                yt_score = min(100, yt_base + yt_bonus)
                # 폴백 키워드 할인 적용
                if yt.get("fallback_discount"):
                    yt_score = round(yt_score * yt["fallback_discount"])
            else:
                yt_score = None

            if yt_score is not None:
                scores = {"oliveyoung": oy_score, "naver_search": nv_score, "youtube": yt_score}
                product_weights = active_weights
            else:
                scores = {"oliveyoung": oy_score, "naver_search": nv_score, "youtube": 0}
                oy_ns_total = DEFAULT_WEIGHTS["oliveyoung"] + DEFAULT_WEIGHTS["naver_search"]
                product_weights = {
                    "oliveyoung": round(DEFAULT_WEIGHTS["oliveyoung"] / oy_ns_total, 2),
                    "naver_search": round(DEFAULT_WEIGHTS["naver_search"] / oy_ns_total, 2),
                    "youtube": 0,
                }

            total = calc_total_score(scores, product_weights)
            scores["total"] = total

            sk = oy.get("search_keyword", oy.get("brand_en", "") + " " + oy["name"])
            brand_en = oy.get("brand_en", "")
            name_ko_val = clean_product_name(oy.get("name", ""))

            nv_change = nv.get("change_rate", None)
            yt_change = yt.get("change_rate", yt.get("view_change_rate", None))

            yt_6m = yt.get("video_count_3month", 0)
            if yt_6m == -1:
                yt_6m = 0
            flags = detect_flags(scores, video_count_3month=yt_6m)
            grade = seller_grade(total, flags)
            note = seller_note(scores, flags)

            kw_entry = kw_map.get(code, {}) if kw_map else {}
            name_en_val = en_override.get(code) or kw_entry.get("english_name") or sk
            name_ko_val = ko_override.get(code) or name_ko_val

            product = {
                "rank": 0,
                "oliveyoung_rank": oy["rank"],
                "brand": oy["brand"],
                "brand_en": oy.get("brand_en", ""),
                "name_ko": name_ko_val,
                "name_en": name_en_val,
                "search_keyword": sk,
                "name_th": translations.get(code, {}).get("name_th", ""),
                "category": oy["category"],
                "scores": scores,
                "naver_change_rate": nv_change,
                "youtube_change_rate": yt_change,
                "signal": "",
                "flags": flags,
                "seller_grade": grade,
                "rank_change": "0",
                "product_code": code,
                "oliveyoung_url": oy.get("url", ""),
                "shopee_url": make_affiliate_url(name_en_val, platform="shopee"),
                "lazada_url": make_affiliate_url(name_en_val, platform="lazada"),
                "yesstyle_url": make_affiliate_url(name_en_val, platform="yesstyle"),
                "amazon_url": make_affiliate_url(name_en_val, platform="amazon"),
                "oliveyoung_global_url": make_affiliate_url("", product_code=code, platform="oliveyoung"),
                "seller_note": note,
                "youtube_available": yt_score is not None,
                "is_promotion": oy.get("is_promotion", oy.get("is_oteuk", False)),
                "is_new_launch": code in all_new_launches,
                "consecutive_periods": 0,
            }
            all_products.append(product)
            translation_lines.append(f'{code}|{oy.get("brand_en", "")}|{oy["name"]}')

            # rising keywords는 아래에서 순위 기반으로 계산

    # Sort by total score
    all_products.sort(key=lambda p: p["scores"]["total"], reverse=True)

    # Assign ranks
    for i, p in enumerate(all_products, 1):
        p["rank"] = i

    # ── 연속 유지 보너스 ──
    # 이전 구간 랭킹 로드 (이전 weekly_ranking 파일들)
    prev_rankings_files = sorted(glob.glob(os.path.join(DATA_DIR, "weekly_ranking_*.json")))
    prev_rankings_files = [f for f in prev_rankings_files if date_str not in os.path.basename(f)]

    if len(periods) >= 2:
        # 이전 구간들의 제품 목록으로 연속 TOP 30 체크
        prev_top_codes_list = []
        for f in prev_rankings_files:
            with open(f, "r", encoding="utf-8") as fh:
                prev_data_item = json.load(fh)
                prev_top_codes_list.append(
                    {p["product_code"] for p in prev_data_item.get("products", [])}
                )
        # 현재 구간 TOP 30
        current_top_codes = {p["product_code"] for p in all_products[:TOP_N]}

        for p in all_products:
            code = p["product_code"]
            consecutive = 0
            if code in current_top_codes:
                consecutive = 1
                for prev_codes in reversed(prev_top_codes_list):
                    if code in prev_codes:
                        consecutive += 1
                    else:
                        break
            p["consecutive_periods"] = consecutive

            bonus = compute_consistency_bonus(consecutive)
            if bonus > 0:
                p["scores"]["total"] = min(100, p["scores"]["total"] + bonus)

            # consecutive_periods 확정 후 flags 재판정
            yt_6m = yt_map.get(code, {}).get("video_count_3month", 0)
            if yt_6m == -1:
                yt_6m = 0
            p["flags"] = detect_flags(p["scores"], video_count_3month=yt_6m,
                                      consecutive_periods=consecutive)
            p["seller_grade"] = seller_grade(p["scores"]["total"], p["flags"])
            p["seller_note"] = seller_note(p["scores"], p["flags"])

        # 보너스 적용 후 재정렬
        all_products.sort(key=lambda p: p["scores"]["total"], reverse=True)
        for i, p in enumerate(all_products, 1):
            p["rank"] = i

    # ── RISING 판정 (v5: 현재 구간 vs 직전 구간 종합 순위 비교) ──
    prev_data = load_previous_ranking(date_str)
    prev_rank_map = {}
    if prev_data:
        for p in prev_data.get("products", []):
            prev_rank_map[p["product_code"]] = p["rank"]

    for p in all_products:
        t = p["scores"]["total"]
        code = p["product_code"]

        if "buzz_trap" in p["flags"]:
            p["signal"] = ""
        elif prev_rank_map and code in prev_rank_map:
            rank_diff = prev_rank_map[code] - p["rank"]
            if rank_diff >= 10:
                p["signal"] = "rising"
            elif t >= 85:
                p["signal"] = "hot"
            else:
                p["signal"] = ""
        elif prev_rank_map and code not in prev_rank_map:
            # 신규 진입 - RISING 아님 (NEW로 표시됨)
            if t >= 85:
                p["signal"] = "hot"
        else:
            # 직전 구간 없음 (첫 구간) - RISING 판정 안 함
            if t >= 85:
                p["signal"] = "hot"

    # Split TOP 30 / extended
    products_top = all_products[:TOP_N]
    products_ext = all_products[TOP_N:]

    # Time-series comparison
    dropped_products, new_count = compute_rank_changes(products_top, prev_data)

    # Buzz Trap / Hidden Gem / Steady Seller
    buzz_traps = []
    hidden_gems = []
    steady_sellers = []
    for p in all_products:
        if "buzz_trap" in p["flags"]:
            buzz_traps.append({"rank": p["rank"], "brand": p["brand"], "brand_en": p.get("brand_en", ""), "name_ko": p["name_ko"], "name_en": p.get("name_en", ""), "scores": p["scores"],
                               "reason": "social buzz high but OY sales rank low"})
        if "hidden_gem" in p["flags"]:
            hidden_gems.append({"rank": p["rank"], "brand": p["brand"], "brand_en": p.get("brand_en", ""), "name_ko": p["name_ko"], "name_en": p.get("name_en", ""), "scores": p["scores"],
                                "reason": "สินค้าขายดีในเกาหลี แต่ยังไม่เป็นกระแสในโซเชียล"})
        if "steady_seller" in p["flags"]:
            steady_sellers.append({"rank": p["rank"], "brand": p["brand"], "brand_en": p.get("brand_en", ""), "name_ko": p["name_ko"], "name_en": p.get("name_en", ""), "scores": p["scores"],
                                   "reason": "proven product with consistent sales and existing reviews"})

    # ── Rising Keywords: API 2주치 데이터로 순위 변동 계산 ──
    naver_rising = []
    youtube_rising = []

    nv_map_all = {item["product_code"]: item for item in nv_data}
    yt_map_all = {item["product_code"]: item for item in yt_data}

    # 네이버: 이번주/전주 검색량으로 순위 매기고 변동 계산
    nv_items = [(code, nv_map_all[code]) for code in nv_map_all
                if not nv_map_all[code].get("product_code", "").startswith("OUTSIDE")]
    if nv_items:
        nv_this_sorted = sorted(nv_items, key=lambda x: x[1].get("search_volume", 0) or 0, reverse=True)
        nv_last_sorted = sorted(nv_items, key=lambda x: x[1].get("search_volume_last_week", 0) or 0, reverse=True)
        nv_this_rank = {code: i + 1 for i, (code, _) in enumerate(nv_this_sorted)}
        nv_last_rank = {code: i + 1 for i, (code, _) in enumerate(nv_last_sorted)}
        for code, item in nv_items:
            rank_change = nv_last_rank.get(code, 50) - nv_this_rank.get(code, 50)
            if rank_change >= 3:
                yt_item = yt_map_all.get(code, {})
                naver_rising.append({
                    "keyword": item.get("keyword", ""),
                    "keyword_en": yt_item.get("keyword", ""),
                    "change_rate": rank_change,  # 순위 변동 (위)
                    "this_rank": nv_this_rank[code],
                    "last_rank": nv_last_rank[code],
                })

    # 유튜브: 이번주/전주 조회수로 순위 매기고 변동 계산
    yt_items = [(code, yt_map_all[code]) for code in yt_map_all
                if yt_map_all[code].get("youtube_available", True)
                and not yt_map_all[code].get("api_error", False)]
    if yt_items:
        yt_this_sorted = sorted(yt_items, key=lambda x: x[1].get("total_views", 0) or 0, reverse=True)
        yt_last_sorted = sorted(yt_items, key=lambda x: x[1].get("total_views_last_week", 0) or 0, reverse=True)
        yt_this_rank = {code: i + 1 for i, (code, _) in enumerate(yt_this_sorted)}
        yt_last_rank = {code: i + 1 for i, (code, _) in enumerate(yt_last_sorted)}
        for code, item in yt_items:
            rank_change = yt_last_rank.get(code, 50) - yt_this_rank.get(code, 50)
            if rank_change >= 3:
                youtube_rising.append({
                    "keyword": item.get("keyword", ""),
                    "change_rate": rank_change,  # 순위 변동 (위)
                    "video_count": item.get("video_count", 0),
                    "this_rank": yt_this_rank[code],
                    "last_rank": yt_last_rank[code],
                })

    naver_rising.sort(key=lambda x: x["change_rate"], reverse=True)
    youtube_rising.sort(key=lambda x: x["change_rate"], reverse=True)

    # Outside Olive Young keywords
    outside_naver = []
    for item in nv_data:
        if item["product_code"] not in oy_codes and item["product_code"].startswith("OUTSIDE"):
            outside_naver.append({
                "keyword": item["keyword"],
                "search_keyword_en": item.get("search_keyword_en", ""),
                "change_rate": item["change_rate"],
                "source": "naver",
            })
    outside_youtube = []
    for item in yt_data:
        if item["product_code"] not in oy_codes and item["product_code"].startswith("OUTSIDE"):
            outside_youtube.append({
                "keyword": item["keyword"],
                "search_keyword_en": item.get("search_keyword_en", ""),
                "change_rate": item.get("change_rate", item.get("view_change_rate", 0)),
                "video_count": item.get("video_count", 0),
                "source": "youtube",
            })
    outside_naver.sort(key=lambda x: x["change_rate"], reverse=True)
    outside_youtube.sort(key=lambda x: x["change_rate"], reverse=True)

    # 구간 정보
    period_info = None
    if current_period:
        period_info = {
            "period_number": len(periods),
            "start": current_period["start"].isoformat(),
            "end": current_period["end"].isoformat(),
            "days": PERIOD_DAYS,
        }

    output = {
        "week": today.strftime("%G-W%V"),
        "updated": today.strftime("%Y-%m-%d"),
        "period_info": period_info,
        "data_status": data_status,
        "active_weights": active_weights,
        "source_weights": DEFAULT_WEIGHTS,
        "products": products_top,
        "products_extended": products_ext,
        "dropped_products": dropped_products,
        "buzz_traps": buzz_traps,
        "hidden_gems": hidden_gems,
        "steady_sellers": steady_sellers,
        "keywords": {"naver_rising": naver_rising[:10], "youtube_rising": youtube_rising[:10]},
        "outside_oliveyoung": {"naver": outside_naver, "youtube": outside_youtube},
        "stats": {
            "total_products": len(products_top),
            "total_analyzed": len(all_products),
            "new_entries": new_count,
            "buzz_trap_count": len(buzz_traps),
            "hidden_gem_count": len(hidden_gems),
            "steady_seller_count": len(steady_sellers),
            "dropped_count": len(dropped_products),
        },
    }

    out_path = os.path.join(DATA_DIR, f"weekly_ranking_{date_str}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    trans_path = os.path.join(DATA_DIR, "translation_needed.txt")
    with open(trans_path, "w", encoding="utf-8") as f:
        f.write("\n".join(translation_lines))

    # Print summary
    print(f"[calc] saved: {out_path}")
    if period_info:
        print(f"[calc] 구간 #{period_info['period_number']}: {period_info['start']} ~ {period_info['end']}")
    print(f"\n=== TOP 5 ===")
    for p in products_top[:5]:
        s = p["scores"]
        sig = f" [{p['signal'].upper()}]" if p["signal"] else ""
        flags_s = " ".join(f"[{f.upper()}]" for f in p["flags"])
        rc = p["rank_change"]
        cp = p.get("consecutive_periods", 0)
        cp_str = f" (연속{cp}구간)" if cp >= 2 else ""
        print(f"  #{p['rank']} ({rc}) (OY#{p['oliveyoung_rank']}) {p['brand']} - {p['name_ko'][:28]}")
        print(f"     OY:{s['oliveyoung']} NS:{s['naver_search']} YT:{s['youtube']} => {s['total']}{sig} {flags_s}{cp_str}")

    if buzz_traps:
        print(f"\n=== BUZZ TRAP ({len(buzz_traps)}) ===")
        for bt in buzz_traps:
            print(f"  #{bt['rank']} {bt['brand']} {bt['name_ko'][:25]}")

    if hidden_gems:
        print(f"\n=== HIDDEN GEM ({len(hidden_gems)}) ===")
        for hg in hidden_gems:
            print(f"  #{hg['rank']} {hg['brand']} {hg['name_ko'][:25]}")

    if steady_sellers:
        print(f"\n=== STEADY SELLER ({len(steady_sellers)}) ===")
        for ss in steady_sellers:
            print(f"  #{ss['rank']} {ss['brand']} {ss['name_ko'][:25]}")

    if dropped_products:
        print(f"\n=== DROPPED ({len(dropped_products)}) ===")
        for dp in dropped_products[:5]:
            print(f"  prev#{dp['rank']} {dp['brand']} {dp['name_ko'][:25]}")

    print(f"\n=== STATS ===")
    st = output["stats"]
    print(f"  analyzed:{st['total_analyzed']} displayed:{st['total_products']} new:{st['new_entries']} dropped:{st['dropped_count']} buzz:{st['buzz_trap_count']} gem:{st['hidden_gem_count']} steady:{st['steady_seller_count']}")

    for src, info in data_status.items():
        status = "OK" if info["available"] else "MISSING"
        src_type = info.get("source", "none")
        print(f"  {src}: {status} ({src_type}, {info['product_count']})")

    return out_path


if __name__ == "__main__":
    main()
