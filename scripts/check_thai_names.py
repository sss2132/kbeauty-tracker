"""웹사이트 올리기 전 태국어 이름 전수 검증.

weekly_ranking의 상위 30개 제품이 모두 태국어 이름을 가지고 있는지 확인.
영문만 있거나 누락된 항목이 있으면 exit code 1 반환.

Usage:
    python scripts/check_thai_names.py
    python scripts/check_thai_names.py data/weekly_ranking_20260405.json
"""

import json
import sys
import os
import glob

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def has_thai(text):
    """태국어 문자 포함 여부."""
    return any("\u0e00" <= c <= "\u0e7f" for c in text)


def main():
    # 파일 경로 결정
    if len(sys.argv) > 1:
        ranking_path = sys.argv[1]
    else:
        files = sorted(glob.glob(os.path.join(DATA_DIR, "weekly_ranking_*.json")))
        if not files:
            print("[TH_CHECK] FAIL - weekly_ranking 파일 없음")
            sys.exit(1)
        ranking_path = files[-1]

    with open(ranking_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    products = data.get("products", [])
    if not products:
        print("[TH_CHECK] FAIL - products 비어있음")
        sys.exit(1)

    issues = []
    for p in products:
        rank = p.get("display_rank", p.get("rank", "?"))
        name = p.get("name", "")
        name_th = p.get("name_th", "")

        if not name_th:
            issues.append(f"  #{rank} {name} — name_th 누락")
        elif not has_thai(name_th):
            issues.append(f"  #{rank} {name} — 영문만 있음: {name_th}")

    if issues:
        print(f"[TH_CHECK] FAIL - 태국어 이름 문제 {len(issues)}건:")
        for issue in issues:
            print(issue)
        sys.exit(1)
    else:
        print(f"[TH_CHECK] PASS - {len(products)}개 제품 태국어 이름 정상")
        sys.exit(0)


if __name__ == "__main__":
    main()
