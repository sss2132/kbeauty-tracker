"""
K-Beauty Trend Tracker - 종합 트렌드 점수 계산기 v5
3소스 체계: OY 45% + NS 30% + YT 25%
로그 스케일 정규화 + 상위 보너스.
Buzz Trap / Hidden Gem / RISING 감지.

v5 변경:
- 고정 3일 구간 평균 순위
- 오톡(오늘의 특가) 프로모션 패널티
- RISING: 현재 구간 vs 직전 구간 종합 순위 비교
- 연속 유지 보너스 (2구간+ TOP 30)
"""

import glob
import json
import math
import os
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


def detect_flags(scores):
    flags = []
    oy = scores.get("oliveyoung", 0)
    ns = scores.get("naver_search", 0)
    yt = scores.get("youtube", 0)
    social = max(ns, yt)
    if social > 70 and oy < 40:
        flags.append("buzz_trap")
    if oy > 70 and ns < 30 and yt < 30:
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
    return " / ".join(parts)


def seller_grade(total, flags):
    if "buzz_trap" in flags:
        return "hold"
    if total >= 80 and "hidden_gem" in flags:
        return "source_now"
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
    sample = os.path.join(DATA_DIR, pattern_or_name.replace("_*.json", "_sample.json"))
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

            # 오톡 패널티
            if item.get("is_promotion", False):
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


def main(use_period=True):
    today = datetime.now()
    date_str = today.strftime("%Y%m%d")

    # ── 3일 구간 확인 ──
    daily_dates = get_daily_dates()
    periods = compute_periods(daily_dates)
    current_period = None
    previous_period = None
    all_period_rankings = []  # 각 구간별 정렬된 제품 리스트

    if use_period and periods:
        current_period = periods[-1]
        if len(periods) >= 2:
            previous_period = periods[-2]
        print(f"[calc] 구간 {len(periods)}개 감지, 현재 구간: {current_period['start']} ~ {current_period['end']}")
    elif use_period and daily_dates:
        # 3일치 안 모임
        latest_period_start = daily_dates[0]
        needed_end = latest_period_start + timedelta(days=PERIOD_DAYS - 1)
        collected = len(daily_dates)
        print(f"[calc] 데이터 수집 완료. 아직 {collected}일치. 사이트 갱신 안 함.")
        print(f"[calc] 다음 갱신: {PERIOD_DAYS}일치 모이면 ({needed_end} 이후)")
        return None

    # ── 데이터 로드 ──
    if current_period:
        # 3일 구간 평균 모드
        oy_avg_scores, oy_info = compute_period_oy_scores(current_period)
        # 최신 날짜의 원본 데이터를 기반으로
        oy_data = load_daily_oliveyoung(current_period["dates"][-1])
        oy_real = True

        # 네이버/유튜브는 최신 날짜 사용
        latest_date = current_period["dates"][-1]
        nv_data = load_daily_data(latest_date, "naver")
        yt_data = load_daily_data(latest_date, "youtube")
        nv_real = bool(nv_data)
        yt_real = bool(yt_data)

        # daily에 네이버/유튜브 없으면 기존 폴더 fallback
        if not nv_data:
            nv_data, nv_real = load_json("naver_*.json")
        if not yt_data:
            yt_data, yt_real = load_json("youtube_*.json")
    else:
        # 기존 방식 fallback (daily 폴더 없을 때)
        oy_data, oy_real = load_json("oliveyoung_*.json")
        if not oy_data:
            path = os.path.join(DATA_DIR, "oliveyoung_sample.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    oy_data = json.load(f)
                oy_real = False

        nv_data, nv_real = load_json("naver_*.json")
        yt_data, yt_real = load_json("youtube_*.json")
        oy_avg_scores = None
        oy_info = None

    # Load translations
    trans_path = os.path.join(DATA_DIR, "translations.json")
    translations = {}
    if os.path.exists(trans_path):
        with open(trans_path, "r", encoding="utf-8") as f:
            translations = json.load(f)

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

    # Collect absolute values for log normalization
    nv_volumes = []
    yt_views = []
    yt_vcounts = []
    for oy in oy_data:
        code = oy["product_code"]
        nv = nv_map.get(code, {})
        yt = yt_map.get(code, {})
        nv_volumes.append(nv.get("search_volume", nv.get("search_volume_this_week", 0)))
        yt_views.append(yt.get("total_views", 0))
        yt_vcounts.append(yt.get("video_count", 0))

    nv_norm = log_normalize_with_bonus(nv_volumes) if nv_data else [0] * len(oy_data)
    yt_norm = log_normalize_with_bonus(yt_views) if yt_data else [0] * len(oy_data)

    all_products = []
    naver_rising = []
    youtube_rising = []
    translation_lines = []

    for i, oy in enumerate(oy_data):
        code = oy["product_code"]
        nv = nv_map.get(code, {})
        yt = yt_map.get(code, {})

        # 올리브영 점수: 구간 평균 or 단일
        if oy_avg_scores and code in oy_avg_scores:
            oy_score = oy_avg_scores[code]
        else:
            oy_score = calc_oliveyoung_score(oy["rank"], oy.get("review_count", 0))
            # 단일 날짜에서도 프로모션 패널티 적용
            if oy.get("is_promotion", False):
                oy_score = round(oy_score * PROMOTION_PENALTY)

        nv_score = nv_norm[i] if nv_data else 0

        yt_product_available = yt.get("youtube_available", True) if yt_data else False
        if yt_data and yt_product_available:
            yt_base = yt_norm[i]
            yt_bonus = calc_youtube_bonus(yt.get("video_count", 0))
            yt_score = min(100, yt_base + yt_bonus)
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

        nv_change = nv.get("change_rate", None)
        yt_change = yt.get("change_rate", yt.get("view_change_rate", None))

        flags = detect_flags(scores)
        grade = seller_grade(total, flags)
        note = seller_note(scores, flags)
        sk = oy.get("search_keyword", oy.get("brand_en", "") + " " + oy["name"])

        product = {
            "rank": 0,
            "oliveyoung_rank": oy["rank"],
            "brand": oy["brand"],
            "brand_en": oy.get("brand_en", ""),
            "name_ko": oy["name"],
            "name_en": oy.get("name_en", ""),
            "search_keyword": oy.get("search_keyword", ""),
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
            "shopee_url": make_affiliate_url(sk, platform="shopee"),
            "lazada_url": make_affiliate_url(sk, platform="lazada"),
            "yesstyle_url": make_affiliate_url(sk, platform="yesstyle"),
            "amazon_url": make_affiliate_url(sk, platform="amazon"),
            "oliveyoung_global_url": make_affiliate_url("", product_code=code, platform="oliveyoung"),
            "seller_note": note,
            "youtube_available": yt_score is not None,
            "is_promotion": oy.get("is_promotion", False),
            "consecutive_periods": 0,
        }
        all_products.append(product)
        translation_lines.append(f'{code}|{oy.get("brand_en", "")}|{oy["name"]}')

        if nv.get("change_rate", 0) >= 20:
            naver_rising.append({"keyword": nv.get("keyword", ""), "change_rate": nv.get("change_rate", 0)})
        if yt.get("change_rate", yt.get("view_change_rate", 0)) >= 30:
            youtube_rising.append({"keyword": yt.get("keyword", ""), "change_rate": yt.get("change_rate", yt.get("view_change_rate", 0)), "video_count": yt.get("video_count", 0)})

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

    # Buzz Trap / Hidden Gem
    buzz_traps = []
    hidden_gems = []
    for p in all_products:
        if "buzz_trap" in p["flags"]:
            buzz_traps.append({"rank": p["rank"], "brand": p["brand"], "name_ko": p["name_ko"], "scores": p["scores"],
                               "reason": "social buzz high but OY sales rank low"})
        if "hidden_gem" in p["flags"]:
            hidden_gems.append({"rank": p["rank"], "brand": p["brand"], "name_ko": p["name_ko"], "scores": p["scores"],
                                "reason": "สินค้าขายดีในเกาหลี แต่ยังไม่เป็นกระแสในโซเชียล"})

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
        "keywords": {"naver_rising": naver_rising[:10], "youtube_rising": youtube_rising[:10]},
        "outside_oliveyoung": {"naver": outside_naver, "youtube": outside_youtube},
        "stats": {
            "total_products": len(products_top),
            "total_analyzed": len(all_products),
            "new_entries": new_count,
            "buzz_trap_count": len(buzz_traps),
            "hidden_gem_count": len(hidden_gems),
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

    if dropped_products:
        print(f"\n=== DROPPED ({len(dropped_products)}) ===")
        for dp in dropped_products[:5]:
            print(f"  prev#{dp['rank']} {dp['brand']} {dp['name_ko'][:25]}")

    print(f"\n=== STATS ===")
    st = output["stats"]
    print(f"  analyzed:{st['total_analyzed']} displayed:{st['total_products']} new:{st['new_entries']} dropped:{st['dropped_count']} buzz:{st['buzz_trap_count']} gem:{st['hidden_gem_count']}")

    for src, info in data_status.items():
        status = "OK" if info["available"] else "MISSING"
        src_type = info.get("source", "none")
        print(f"  {src}: {status} ({src_type}, {info['product_count']})")

    return out_path


if __name__ == "__main__":
    main()
