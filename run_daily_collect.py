"""
K-Beauty Trend Tracker - 매일 데이터 수집 스크립트
사용법: python run_daily_collect.py

1. 올리브영 스크린샷 캡처
2. 사용자 확인 대기
3. 스크린샷에서 제품 추출 → oliveyoung JSON
4. 네이버 API → naver JSON
5. 유튜브 API → youtube JSON
6. data/daily/YYYY-MM-DD/ 폴더에 저장
7. 3일치 데이터 확인 → 갱신 여부 결정
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DAILY_DIR = os.path.join(DATA_DIR, "daily")
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
PERIOD_DAYS = 3


def log(step, msg, ok=True):
    status = "OK" if ok else "SKIP"
    print(f"[{step}] {status} - {msg}")


def step_capture():
    """1. 올리브영 스크린샷 캡처."""
    script = os.path.join(SCRIPTS_DIR, "capture_oliveyoung.py")
    if not os.path.exists(script):
        log("1. CAPTURE", "capture_oliveyoung.py 없음", ok=False)
        return False
    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True, timeout=300,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0:
            log("1. CAPTURE", "올리브영 캡처 완료")
            for line in result.stdout.split("\n"):
                if line.strip():
                    print(f"       {line.strip()}")
            return True
        else:
            log("1. CAPTURE", f"실패: {result.stderr[:200]}", ok=False)
            return False
    except subprocess.TimeoutExpired:
        log("1. CAPTURE", "타임아웃 (300초)", ok=False)
        return False
    except Exception as e:
        log("1. CAPTURE", f"오류: {e}", ok=False)
        return False


def step_wait_confirmation():
    """2. 사용자 확인 대기."""
    print("\n" + "=" * 50)
    print("  캡처 완료. 확인 후 계속 진행하려면 Enter")
    print("  (취소하려면 Ctrl+C)")
    print("=" * 50)
    try:
        input()
        return True
    except (KeyboardInterrupt, EOFError):
        print("\n취소됨.")
        return False


def step_extract_products(today_str):
    """3. 스크린샷에서 제품 추출 → oliveyoung JSON.
    Note: 실제 OCR/추출은 별도 도구 필요. 여기서는 기존 데이터 복사 또는 수동 입력 안내."""
    oy_files = sorted(glob.glob(os.path.join(DATA_DIR, "oliveyoung_*.json")))
    oy_files = [f for f in oy_files if "sample" not in os.path.basename(f)]

    if oy_files:
        latest = oy_files[-1]
        log("3. EXTRACT", f"기존 올리브영 데이터 사용: {os.path.basename(latest)}")
        return latest
    else:
        sample = os.path.join(DATA_DIR, "oliveyoung_sample.json")
        if os.path.exists(sample):
            log("3. EXTRACT", "올리브영 샘플 데이터 사용 (실제 추출 필요)", ok=False)
            return sample
        log("3. EXTRACT", "올리브영 데이터 없음", ok=False)
        return None


def step_naver():
    """4. 네이버 API 호출."""
    script = os.path.join(SCRIPTS_DIR, "naver_trend.py")
    if not os.path.exists(script):
        log("4. NAVER", "naver_trend.py 없음", ok=False)
        return None
    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0:
            log("4. NAVER", "네이버 데이터 수집 완료")
            nv_files = sorted(glob.glob(os.path.join(DATA_DIR, "naver_*.json")))
            nv_files = [f for f in nv_files if "sample" not in os.path.basename(f) and "rank" not in os.path.basename(f)]
            return nv_files[-1] if nv_files else None
        else:
            log("4. NAVER", f"실패: {result.stderr[:200]}", ok=False)
            return None
    except Exception as e:
        log("4. NAVER", f"오류: {e}", ok=False)
        return None


def step_youtube():
    """5. 유튜브 API 호출."""
    script = os.path.join(SCRIPTS_DIR, "youtube_trend.py")
    if not os.path.exists(script):
        log("5. YOUTUBE", "youtube_trend.py 없음", ok=False)
        return None
    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0:
            log("5. YOUTUBE", "유튜브 데이터 수집 완료")
            yt_files = sorted(glob.glob(os.path.join(DATA_DIR, "youtube_*.json")))
            yt_files = [f for f in yt_files if "sample" not in os.path.basename(f)]
            return yt_files[-1] if yt_files else None
        else:
            log("5. YOUTUBE", f"실패: {result.stderr[:200]}", ok=False)
            return None
    except Exception as e:
        log("5. YOUTUBE", f"오류: {e}", ok=False)
        return None


def step_save_daily(today_str, oy_file, nv_file, yt_file):
    """6. data/daily/YYYY-MM-DD/ 폴더에 저장."""
    date_folder = datetime.strptime(today_str, "%Y%m%d").strftime("%Y-%m-%d")
    daily_path = os.path.join(DAILY_DIR, date_folder)
    os.makedirs(daily_path, exist_ok=True)

    saved = 0
    if oy_file and os.path.exists(oy_file):
        dest = os.path.join(daily_path, f"oliveyoung_{today_str}.json")
        shutil.copy2(oy_file, dest)
        saved += 1
        print(f"       -> {dest}")

    if nv_file and os.path.exists(nv_file):
        dest = os.path.join(daily_path, f"naver_{today_str}.json")
        shutil.copy2(nv_file, dest)
        saved += 1
        print(f"       -> {dest}")

    if yt_file and os.path.exists(yt_file):
        dest = os.path.join(daily_path, f"youtube_{today_str}.json")
        shutil.copy2(yt_file, dest)
        saved += 1
        print(f"       -> {dest}")

    log("6. SAVE", f"daily/{date_folder}/ 에 {saved}개 파일 저장")
    return daily_path


def count_daily_data():
    """data/daily/ 폴더에서 oliveyoung 데이터가 있는 날짜 수."""
    if not os.path.isdir(DAILY_DIR):
        return 0
    count = 0
    for folder in os.listdir(DAILY_DIR):
        folder_path = os.path.join(DAILY_DIR, folder)
        if os.path.isdir(folder_path):
            oy_files = glob.glob(os.path.join(folder_path, "oliveyoung_*.json"))
            if oy_files:
                count += 1
    return count


def step_check_and_update(today_str):
    """7. 3일치 데이터 확인 → 갱신 여부."""
    collected = count_daily_data()

    if collected >= PERIOD_DAYS:
        print(f"\n{'=' * 50}")
        print(f"  {collected}일치 데이터 수집됨 → 사이트 갱신 시작!")
        print(f"{'=' * 50}\n")

        # score_calculator.py 실행
        calc_script = os.path.join(BASE_DIR, "score_calculator.py")
        result = subprocess.run(
            [sys.executable, calc_script],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0:
            log("7. CALC", "점수 계산 완료")
            for line in result.stdout.split("\n"):
                if line.strip():
                    print(f"       {line.strip()}")
        else:
            log("7. CALC", f"실패: {result.stderr[:200]}", ok=False)
            return False

        # generate_site.py 실행
        site_script = os.path.join(BASE_DIR, "generate_site.py")
        result = subprocess.run(
            [sys.executable, site_script],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0:
            log("7. SITE", "사이트 생성 완료")
            return True
        else:
            log("7. SITE", f"실패: {result.stderr[:200]}", ok=False)
            return False
    else:
        remaining = PERIOD_DAYS - collected
        print(f"\n{'=' * 50}")
        print(f"  데이터 수집 완료. 아직 {collected}일치.")
        print(f"  사이트 갱신 안 함. ({remaining}일 더 필요)")
        print(f"{'=' * 50}")
        return True


def main():
    start = time.time()
    today = datetime.now()
    today_str = today.strftime("%Y%m%d")
    print(f"\n{'=' * 50}")
    print(f"  K-Beauty Daily Data Collection")
    print(f"  {today.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 50}\n")

    # Step 1: 캡처
    capture_ok = step_capture()

    # Step 2: 확인 대기
    if capture_ok:
        if not step_wait_confirmation():
            return False

    # Step 3: 제품 추출
    oy_file = step_extract_products(today_str)

    # Step 4 & 5: API 호출
    nv_file = step_naver()
    yt_file = step_youtube()

    # Step 6: daily 폴더 저장
    if oy_file:
        step_save_daily(today_str, oy_file, nv_file, yt_file)

    # Step 7: 갱신 여부
    step_check_and_update(today_str)

    elapsed = time.time() - start
    print(f"\n  Total time: {elapsed:.1f}s")
    return True


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
