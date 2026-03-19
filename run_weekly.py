"""
K-Beauty Trend Tracker - 주간 파이프라인
실행: python run_weekly.py

1. 올리브영 데이터 확인
2. 네이버 검색량 조회
3. 유튜브 트렌드 조회
4. 점수 계산 (3소스: OY 45% + NS 30% + YT 25%)
5. 사이트 생성
"""

import glob
import os
import subprocess
import sys
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


def log(step, msg, ok=True):
    status = "OK" if ok else "FAIL"
    print(f"[{step}] {status} - {msg}")


def step_oliveyoung():
    """1. 올리브영 데이터 확인"""
    files = sorted(glob.glob(os.path.join(DATA_DIR, "oliveyoung_*.json")))
    real_files = [f for f in files if "sample" not in os.path.basename(f)]

    if real_files:
        latest = real_files[-1]
        log("1/5 OY", f"데이터 발견: {os.path.basename(latest)}")
        return True
    else:
        sample = os.path.join(DATA_DIR, "oliveyoung_sample.json")
        if os.path.exists(sample):
            log("1/5 OY", "실제 데이터 없음 - oliveyoung_sample.json 사용", ok=False)
            return True
        else:
            log("1/5 OY", "데이터 파일 없음!", ok=False)
            return False


def step_naver_search():
    """2. 네이버 검색량 조회"""
    script = os.path.join(BASE_DIR, "scripts", "naver_trend.py")
    if not os.path.exists(script):
        log("2/5 NS", "naver_trend.py 없음", ok=False)
        return False
    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0:
            log("2/5 NS", "네이버 검색량 완료")
            return True
        else:
            log("2/5 NS", f"실패: {result.stderr[:200]}", ok=False)
            return False
    except subprocess.TimeoutExpired:
        log("2/5 NS", "타임아웃 (120초)", ok=False)
        return False
    except Exception as e:
        log("2/5 NS", f"오류: {e}", ok=False)
        return False


# -- 네이버 인기도순 비활성화 (OY와 상관 0.848) --
# def step_naver_rank():
#     """네이버 인기도순 조회 (비활성화: OY와 거의 동일 지표)"""
#     script = os.path.join(BASE_DIR, "scripts", "naver_shopping_rank.py")
#     ...


def step_youtube():
    """3. 유튜브 트렌드 조회"""
    script = os.path.join(BASE_DIR, "scripts", "youtube_trend.py")
    if not os.path.exists(script):
        log("3/5 YT", "youtube_trend.py 없음", ok=False)
        return False
    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0:
            log("3/5 YT", "유튜브 트렌드 완료")
            return True
        else:
            log("3/5 YT", f"실패: {result.stderr[:200]}", ok=False)
            return False
    except subprocess.TimeoutExpired:
        log("3/5 YT", "타임아웃 (120초)", ok=False)
        return False
    except Exception as e:
        log("3/5 YT", f"오류: {e}", ok=False)
        return False


def step_calculate():
    """4. 점수 계산"""
    script = os.path.join(BASE_DIR, "score_calculator.py")
    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0:
            log("4/5 CALC", "점수 계산 완료")
            for line in result.stdout.split("\n"):
                if "analyzed:" in line or "TOP 5" in line:
                    print(f"       {line.strip()}")
            return True
        else:
            log("4/5 CALC", f"실패: {result.stderr[:200]}", ok=False)
            return False
    except Exception as e:
        log("4/5 CALC", f"오류: {e}", ok=False)
        return False


def step_generate_site():
    """5. 사이트 생성"""
    script = os.path.join(BASE_DIR, "generate_site.py")
    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0:
            log("5/5 SITE", "사이트 생성 완료")
            for line in result.stdout.split("\n"):
                if line.strip():
                    print(f"       {line.strip()}")
            return True
        else:
            log("5/5 SITE", f"실패: {result.stderr[:200]}", ok=False)
            return False
    except Exception as e:
        log("5/5 SITE", f"오류: {e}", ok=False)
        return False


def main():
    start = time.time()
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*50}")
    print(f"  K-Beauty Trend Tracker - Weekly Pipeline")
    print(f"  {today}")
    print(f"{'='*50}\n")

    results = {}

    # Step 1: OY data check
    results["oliveyoung"] = step_oliveyoung()
    if not results["oliveyoung"]:
        print("\n[ABORT] 올리브영 데이터 없음. 파이프라인 중단.")
        return False

    # Step 2: Naver Search
    results["naver_search"] = step_naver_search()

    # Step 3: YouTube
    results["youtube"] = step_youtube()

    # Step 4: Calculate scores
    results["calculate"] = step_calculate()
    if not results["calculate"]:
        print("\n[ABORT] 점수 계산 실패. 이전 사이트 유지.")
        return False

    # Step 5: Generate site
    results["site"] = step_generate_site()

    # Summary
    elapsed = time.time() - start
    print(f"\n{'='*50}")
    print(f"  Pipeline Summary")
    print(f"{'='*50}")
    for step, ok in results.items():
        mark = "OK" if ok else "FAIL"
        print(f"  {step:15s} [{mark}]")
    print(f"\n  Total time: {elapsed:.1f}s")

    success = all(results.values())
    if success:
        print(f"\n  All steps completed successfully.")
    else:
        failed = [k for k, v in results.items() if not v]
        print(f"\n  Warning: {', '.join(failed)} failed.")
        print(f"  Site may have incomplete data (warning banner shown).")

    index_path = os.path.join(BASE_DIR, "docs", "index.html")
    if os.path.exists(index_path):
        size_kb = os.path.getsize(index_path) / 1024
        print(f"\n  Output: docs/index.html ({size_kb:.0f}KB)")

    print()
    return success


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
