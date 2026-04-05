"""
K-Beauty Trend Tracker - Orchestrator + Verification Agent

사용법:
  python run_daily_collect.py              # 전체 파이프라인 (Step 1~5)
  python run_daily_collect.py step1        # Step 1만: 캡처 + 추출 안내
  python run_daily_collect.py step2        # Step 2만: 올리브영 검증
  python run_daily_collect.py step3        # Step 3만: API 수집
  python run_daily_collect.py step4        # Step 4만: API 검증
  python run_daily_collect.py step5        # Step 5만: daily 저장 + 갱신

=== 구조 ===

Orchestrator (이 스크립트):
  전체 흐름 통제. Step 1~5를 순서대로 실행.
  검증 단계에서 claude -p 로 별도 프로세스를 띄워 검증 Agent 호출.

Verification Agent (claude -p subprocess):
  새 프로세스 = 수집 과정 기억 없음 = unbiased 검증.
  스크린샷/JSON 파일만 보고 대조.
  JSON 스키마로 구조화된 응답 반환: {"passed": bool, "issues": [...]}
"""

import concurrent.futures
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

from config import (
    PERIOD_DAYS, TIMEOUT_ENRICH, TIMEOUT_VERIFY, TIMEOUT_KEYWORD,
    TIMEOUT_EN_VERIFY, TIMEOUT_CAPTURE, TIMEOUT_NAVER, TIMEOUT_YOUTUBE,
)

_print_lock = threading.Lock()


def safe_print(text):
    """cp949 등 터미널 인코딩에서 깨지는 문자를 ? 로 대체하여 출력. 스레드 안전."""
    with _print_lock:
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
                sys.stdout.encoding or "utf-8", errors="replace"
            ))


# ================================================================
#  경로 설정
# ================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DAILY_DIR = os.path.join(DATA_DIR, "daily")
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
PROJECT_ROOT = os.path.dirname(BASE_DIR)
SCREENSHOT_DIR = os.path.join(PROJECT_ROOT, "Oliveyoung collection")
CLAUDE_EXE = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
AGENTS_DIR = os.path.join(BASE_DIR, "agents")


def check_claude_auth():
    """claude -p 인증 상태 사전 확인. 실패 시 False 반환."""
    try:
        result = subprocess.run(
            [CLAUDE_EXE, "-p", "--no-session-persistence"],
            input="reply OK",
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0 and "OK" in result.stdout:
            return True
        safe_print(f"[AUTH] claude -p 인증 실패: returncode={result.returncode}")
        return False
    except subprocess.TimeoutExpired:
        safe_print("[AUTH] claude -p 응답 없음 (30초 타임아웃) - 인증 만료 가능")
        return False
    except Exception as e:
        safe_print(f"[AUTH] claude -p 확인 실패: {e}")
        return False


def load_agent_rules(filename):
    """agents/ 디렉토리에서 agent별 규칙 MD 파일을 읽어 반환."""
    path = os.path.join(AGENTS_DIR, filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


# ================================================================
#  Verification Agent
# ================================================================

VERIFICATION_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "passed": {"type": "boolean", "description": "사용자 확인이 필요한 이슈가 없으면 true"},
        "auto_fixed": {
            "type": "array",
            "items": {"type": "string"},
            "description": "agent가 직접 수정한 항목 목록 (수정 완료)"
        },
        "issues": {
            "type": "array",
            "items": {"type": "string"},
            "description": "사용자 확인이 필요한 항목만 (agent가 판단 불가)"
        },
        "new_launches": {
            "type": "array",
            "items": {"type": "string"},
            "description": "1주 이내 출시 확인된 신제품의 product_code 목록"
        }
    },
    "required": ["passed", "issues"]
}, ensure_ascii=False)

KEYWORD_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "keywords": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "product_code": {"type": "string"},
                    "naver_keyword": {"type": "string"},
                    "english_name": {"type": "string"}
                },
                "required": ["product_code", "naver_keyword", "english_name"]
            }
        }
    },
    "required": ["keywords"]
}, ensure_ascii=False)

EN_VERIFY_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "product_code": {"type": "string"},
                    "status": {"type": "string", "enum": ["ok", "mismatch", "missing", "needs_confirm"]},
                    "corrected_name": {"type": "string", "description": "status가 mismatch일 때만: 수정된 영문명"},
                    "reason": {"type": "string", "description": "status가 ok가 아닐 때: 사유"}
                },
                "required": ["product_code", "status"]
            }
        }
    },
    "required": ["results"]
}, ensure_ascii=False)


def compute_file_hash(filepath):
    """파일의 SHA256 해시 계산 — 검증 결과와 데이터 파일 연결용."""
    import hashlib
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def run_keyword_agent(oy_path, timeout=TIMEOUT_KEYWORD, today_str=None):
    """claude -p로 최적 검색 키워드 생성 (배치 분할). 실패 시 None 반환."""
    if today_str is None:
        today_str = datetime.now().strftime("%Y%m%d")
    gn_path = os.path.join(DATA_DIR, f"_global_names_{today_str}.json")
    if not os.path.exists(gn_path):
        safe_print("[KEYWORD] FAIL - 글로벌몰 영문명 파일 없음.")
        return None
    global_names_ref = os.path.abspath(gn_path)

    # 올리브영 데이터를 배치 분할
    with open(oy_path, "r", encoding="utf-8") as f:
        products = json.load(f)

    batch_size = 10
    batches = [products[i:i + batch_size] for i in range(0, len(products), batch_size)]
    rules = load_agent_rules("step3_keyword.md")
    all_keywords = [None] * len(batches)  # 순서 보존용

    # 글로벌몰 영문명 데이터를 미리 로드 (배치별 필터링용)
    with open(gn_path, "r", encoding="utf-8") as f:
        global_names_data = json.load(f)
    gn_products = global_names_data.get("products", global_names_data) if isinstance(global_names_data, dict) else global_names_data

    def _run_keyword_batch(batch_idx, batch):
        """단일 키워드 배치 처리 (병렬 실행용)."""
        codes = [p["product_code"] for p in batch]
        codes_set = set(codes)
        rank_range = f"{batch[0].get('rank', '?')}~{batch[-1].get('rank', '?')}"

        batch_oy_path = os.path.join(DATA_DIR, f"_kw_batch_oy_{batch_idx}.json")
        with open(batch_oy_path, "w", encoding="utf-8") as f:
            json.dump(batch, f, ensure_ascii=False, indent=2)

        batch_gn_path = os.path.join(DATA_DIR, f"_kw_batch_gn_{batch_idx}.json")
        if isinstance(gn_products, dict):
            filtered_gn = {k: v for k, v in gn_products.items() if k in codes_set}
        elif isinstance(gn_products, list):
            filtered_gn = [p for p in gn_products if p.get("product_code") in codes_set]
        else:
            filtered_gn = gn_products
        with open(batch_gn_path, "w", encoding="utf-8") as f:
            json.dump(filtered_gn, f, ensure_ascii=False, indent=2)

        prompt = f"""{rules}

---

## 작업 (배치 {batch_idx + 1}/{len(batches)}: rank {rank_range})
올리브영 제품 데이터를 읽고, 각 제품의 키워드를 생성해.

제품 데이터 ({len(batch)}개): {os.path.abspath(batch_oy_path)}

## 글로벌몰 영문명 참조 파일
{os.path.abspath(batch_gn_path)}
- product_code로 검색, global_name 필드가 공식 영문명
- 매칭된 건은 용량/기획 텍스트만 제거하고 그대로 사용
- 매칭 안 된 건은 한국어 name을 자연스러운 영어로 번역 (WebFetch 하지 않음)

화장품인 제품만 product_code, naver_keyword, english_name을 생성해.
비화장품은 keywords 배열에서 완전히 제외해."""

        cmd = [
            CLAUDE_EXE, "-p",
            "--model", "sonnet",
            "--output-format", "json",
            "--json-schema", KEYWORD_SCHEMA,
            "--allowed-tools", "Read",
            "--no-session-persistence",
        ]

        safe_print(f"[KEYWORD] 배치 {batch_idx + 1}/{len(batches)}: rank {rank_range} ({len(codes)}개)...")

        try:
            result = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace", cwd=PROJECT_ROOT,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            safe_print(f"[KEYWORD] 배치 {batch_idx + 1} 실패: {e}")
            return None
        finally:
            for p in (batch_oy_path, batch_gn_path):
                if os.path.exists(p):
                    os.remove(p)

        if result.returncode != 0:
            safe_print(f"[KEYWORD] 배치 {batch_idx + 1} 실행 실패")
            return None

        raw = result.stdout.strip()
        try:
            outer = json.loads(raw)
            if "structured_output" in outer and isinstance(outer["structured_output"], dict):
                inner = outer["structured_output"]
            elif "result" in outer and isinstance(outer["result"], str):
                inner = json.loads(outer["result"])
            elif "keywords" in outer:
                inner = outer
            else:
                safe_print(f"[KEYWORD] 배치 {batch_idx + 1} 응답 파싱 실패")
                return None

            batch_kws = inner.get("keywords", [])
            safe_print(f"[KEYWORD] 배치 {batch_idx + 1} OK - {len(batch_kws)}개 키워드")
            return batch_kws
        except (json.JSONDecodeError, TypeError):
            safe_print(f"[KEYWORD] 배치 {batch_idx + 1} JSON 파싱 실패")
            return None

    # 병렬 실행 (max_workers=3: API rate limit 고려)
    safe_print(f"[KEYWORD] {len(batches)}개 배치 병렬 실행...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_run_keyword_batch, idx, batch): idx
            for idx, batch in enumerate(batches)
        }
        for future in concurrent.futures.as_completed(futures):
            batch_idx = futures[future]
            batch_result = future.result()
            if batch_result is None:
                return None
            all_keywords[batch_idx] = batch_result

    # 순서대로 합치기
    merged = []
    for kws in all_keywords:
        if kws:
            merged.extend(kws)
    return {"keywords": merged[:50]}


def verify_english_names(oy_path, keywords_path, timeout=TIMEOUT_EN_VERIFY):
    """영문명과 한글 풀네임을 product-by-product로 대조 검증.

    키워드 생성 후, 결정된 english_name이 한글 제품명과 일치하는지 확인.
    오매칭 발견 시 수정된 이름을 반환하여 keywords 파일을 업데이트.
    """
    if not os.path.exists(keywords_path):
        safe_print("[EN_VERIFY] 키워드 파일 없음 - 검증 건너뜀")
        return

    with open(oy_path, "r", encoding="utf-8") as f:
        oy_data = json.load(f)
    with open(keywords_path, "r", encoding="utf-8") as f:
        kw_data = json.load(f)

    # 올리브영 제품 맵 (product_code → full name)
    oy_map = {}
    for p in oy_data:
        oy_map[p["product_code"]] = {
            "name": p["name"],
            "brand": p.get("brand", ""),
            "brand_en": p.get("brand_en", ""),
        }

    # 비교 목록 생성
    compare_lines = []
    for kw in kw_data:
        code = kw["product_code"]
        en_name = kw.get("english_name", "")
        oy_info = oy_map.get(code, {})
        ko_name = oy_info.get("name", "")
        brand = oy_info.get("brand", "")
        brand_en = oy_info.get("brand_en", "")
        compare_lines.append(f"{code} | {brand} ({brand_en}) | KO: {ko_name} | EN: {en_name}")

    if not compare_lines:
        safe_print("[EN_VERIFY] 비교 대상 없음")
        return

    compare_text = "\n".join(compare_lines)

    rules = load_agent_rules("step3_en_verify.md")

    prompt = f"""{rules}

---

## 작업
아래 목록에서 각 제품의 한글 풀네임(KO)과 영문명(EN)이 같은 제품을 가리키는지 확인해.

## 제품 목록
{compare_text}

각 제품에 대해 status(ok/mismatch/missing/needs_confirm)를 판단해.
- mismatch면 corrected_name과 reason을 제시
- needs_confirm이면 반드시 웹검색(global.oliveyoung.com, 공식몰)으로 확인한 결과를 reason에 포함"""

    cmd = [
        CLAUDE_EXE, "-p",
        "--model", "sonnet",
        "--output-format", "json",
        "--json-schema", EN_VERIFY_SCHEMA,
        "--allowed-tools", "Read,WebFetch,WebSearch",
        "--no-session-persistence",
    ]

    safe_print("[EN_VERIFY] 영문명 검증 Agent 호출 중...")

    try:
        result = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", cwd=PROJECT_ROOT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        safe_print(f"[EN_VERIFY] Agent 실패: {e}")
        return

    if result.returncode != 0:
        safe_print(f"[EN_VERIFY] Agent 실행 실패: {(result.stderr or '')[:200]}")
        return

    raw = result.stdout.strip()
    try:
        outer = json.loads(raw)
        if "structured_output" in outer and isinstance(outer["structured_output"], dict):
            inner = outer["structured_output"]
        elif "results" in outer:
            inner = outer
        else:
            safe_print("[EN_VERIFY] 응답 파싱 실패")
            return
    except (json.JSONDecodeError, TypeError):
        safe_print("[EN_VERIFY] JSON 파싱 실패")
        return

    verify_results = inner.get("results", [])
    mismatches = [r for r in verify_results if r.get("status") == "mismatch"]
    missing = [r for r in verify_results if r.get("status") == "missing"]
    needs_confirm = [r for r in verify_results if r.get("status") == "needs_confirm"]

    if not mismatches and not missing and not needs_confirm:
        safe_print(f"[EN_VERIFY] 전체 {len(verify_results)}개 제품 영문명 OK")
        return

    safe_print(f"[EN_VERIFY] 오매칭 {len(mismatches)}건, 확인필요 {len(needs_confirm)}건, 누락 {len(missing)}건")

    # needs_confirm 목록을 파일로 저장 (orchestrator가 세션에서 사용자에게 확인 요청)
    if needs_confirm:
        confirm_path = os.path.join(DATA_DIR, "_en_needs_confirm.json")
        confirm_items = []
        for nc in needs_confirm:
            code = nc["product_code"]
            oy_info = oy_map.get(code, {})
            kw_entry = {kw["product_code"]: kw for kw in kw_data}.get(code, {})
            confirm_items.append({
                "product_code": code,
                "korean_name": oy_info.get("name", ""),
                "english_name": kw_entry.get("english_name", ""),
                "reason": nc.get("reason", ""),
            })
            safe_print(f"  확인필요: {oy_info.get('name', code)} → EN: {kw_entry.get('english_name', '?')} ({nc.get('reason', '')})")
        with open(confirm_path, "w", encoding="utf-8") as f:
            json.dump(confirm_items, f, ensure_ascii=False, indent=2)
        safe_print(f"[EN_VERIFY] 확인 필요 {len(confirm_items)}건 → _en_needs_confirm.json (세션에서 사용자 확인 요청 필요)")

    # 키워드 파일의 english_name 수정 (mismatch만 자동 수정)
    kw_by_code = {kw["product_code"]: kw for kw in kw_data}
    fixed_count = 0
    for m in mismatches:
        code = m["product_code"]
        corrected = m.get("corrected_name", "")
        reason = m.get("reason", "")
        if corrected and code in kw_by_code:
            old_name = kw_by_code[code].get("english_name", "")
            kw_by_code[code]["english_name"] = corrected
            fixed_count += 1
            safe_print(f"  수정: {old_name} → {corrected} ({reason})")

    if fixed_count > 0:
        with open(keywords_path, "w", encoding="utf-8") as f:
            json.dump(kw_data, f, ensure_ascii=False, indent=2)
        safe_print(f"[EN_VERIFY] {fixed_count}건 영문명 수정 완료 → {os.path.basename(keywords_path)}")


def run_verification_agent(prompt, timeout=TIMEOUT_VERIFY, allowed_tools="Read,Write,Glob"):
    """
    Claude Code CLI를 별도 프로세스(Opus)로 띄워 검증 실행.

    - 새 프로세스 = 이전 수집/추출 대화 기억 없음 = unbiased 검증
    - --model sonnet: 규칙 기반 검증
    - --no-session-persistence: 세션 기록 남기지 않음
    - Write 권한: 명확한 이슈는 agent가 직접 JSON 수정

    Returns:
        dict: {"passed": bool, "auto_fixed": [...], "issues": [...], "new_launches": [...]}
              파싱 실패 시 {"passed": False, "issues": ["파싱 실패: ..."]}
    """
    cmd = [
        CLAUDE_EXE,
        "-p",
        "--model", "sonnet",
        "--output-format", "json",
        "--json-schema", VERIFICATION_SCHEMA,
        "--allowed-tools", allowed_tools,
        "--no-session-persistence",
    ]

    safe_print(f"\n[VERIFY] 검증 Agent 호출 중...")

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            cwd=PROJECT_ROOT,
        )
    except subprocess.TimeoutExpired:
        return {"passed": False, "issues": [f"검증 Agent 타임아웃 ({timeout}초)"]}
    except FileNotFoundError:
        return {"passed": False, "issues": [
            "claude CLI를 찾을 수 없음. Claude Code가 설치되어 있는지 확인하세요."
        ]}

    if result.returncode != 0:
        stderr_short = (result.stderr or "")[:500]
        return {"passed": False, "issues": [f"검증 Agent 실행 실패: {stderr_short}"]}

    # JSON 응답 파싱
    # --output-format json 사용 시 응답 구조:
    # {"type":"result", "structured_output": {"passed": bool, "issues": [...]}, ...}
    raw = result.stdout.strip()
    try:
        outer = json.loads(raw)

        # structured_output 필드에 JSON 스키마 응답이 들어옴
        if "structured_output" in outer and isinstance(outer["structured_output"], dict):
            inner = outer["structured_output"]
        elif "result" in outer and isinstance(outer["result"], str) and outer["result"]:
            inner = json.loads(outer["result"])
        elif "passed" in outer:
            inner = outer
        else:
            return {"passed": False, "issues": [f"응답에 structured_output 없음: {raw[:300]}"]}

        passed = inner.get("passed", False)
        issues = inner.get("issues", [])
        if not isinstance(issues, list):
            issues = [str(issues)]
        return {"passed": passed, "issues": issues}
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        return {"passed": False, "issues": [
            f"검증 Agent 응답 파싱 실패: {str(e)}",
            f"원문 (앞 500자): {raw[:500]}"
        ]}


def handle_verification_result(result, step_name):
    """검증 결과 처리. 통과/실패에 따라 진행 여부 결정."""
    auto_fixed = result.get("auto_fixed", [])
    if auto_fixed:
        safe_print(f"[VERIFY] {step_name} 자동 수정 {len(auto_fixed)}건:")
        for fix in auto_fixed:
            safe_print(f"    ✓ {fix}")

    if result["passed"]:
        safe_print(f"[VERIFY] {step_name} 검증 통과")
        if result["issues"]:
            safe_print(f"  (참고 사항 {len(result['issues'])}건)")
            for issue in result["issues"]:
                safe_print(f"    - {issue}")
        return True

    safe_print(f"[VERIFY] {step_name} 검증 실패 - 사용자 확인 필요 {len(result['issues'])}건:")
    for i, issue in enumerate(result["issues"], 1):
        safe_print(f"  {i}. {issue}")

    try:
        user_input = input("\n무시하고 진행하려면 Enter, 중단하려면 q: ")
        if user_input.strip().lower() == "q":
            safe_print("중단됨.")
            return False
        safe_print("경고 무시하고 진행합니다.")
        return True
    except (KeyboardInterrupt, EOFError):
        safe_print("\n중단됨.")
        return False


# ================================================================
#  Step 1: 올리브영 캡처 + 추출 안내
# ================================================================

def run_step1(today_str=None):
    """올리브영 랭킹 페이지 캡처 + DOM 추출 + 데이터 보강 Agent."""
    if today_str is None:
        today_str = datetime.now().strftime("%Y%m%d")

    # 멱등성: 당일 결과 파일이 이미 있으면 건너뜀
    oy_check = os.path.join(DATA_DIR, f"oliveyoung_{today_str}.json")
    if os.path.exists(oy_check) and os.path.getsize(oy_check) > 100:
        safe_print(f"[STEP1] SKIP - {os.path.basename(oy_check)} 이미 존재")
        return True

    # claude -p 인증 사전 확인
    if not check_claude_auth():
        safe_print("[STEP1] ABORT - claude -p 인증 실패. 로그인 필요.")
        return False
    safe_print(f"\n{'=' * 50}")
    safe_print(f"  Step 1: 올리브영 캡처 + 추출")
    safe_print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    safe_print(f"{'=' * 50}\n")

    # Phase 1: 캡처 실행 (스크린샷이 이미 있으면 건너뜀)
    existing_ss = sorted(
        glob.glob(os.path.join(SCREENSHOT_DIR, f"oliveyoung_{today_str}_*.png"))
    )
    if existing_ss:
        safe_print(f"[CAPTURE] SKIP - 스크린샷 {len(existing_ss)}장 이미 존재")
    else:
        capture_script = os.path.join(SCRIPTS_DIR, "capture_oliveyoung.py")
        if not os.path.exists(capture_script):
            safe_print("[CAPTURE] SKIP - capture_oliveyoung.py 없음")
        else:
            try:
                result = subprocess.run(
                    [sys.executable, capture_script],
                    capture_output=True, text=True, timeout=TIMEOUT_CAPTURE,
                    encoding="utf-8", errors="replace"
                )
                if result.returncode == 0:
                    safe_print("[CAPTURE] OK")
                    for line in result.stdout.split("\n"):
                        if line.strip():
                            safe_print(f"  {line.strip()}")
                else:
                    safe_print(f"[CAPTURE] FAIL - {result.stderr[:300]}")
                    return False
            except subprocess.TimeoutExpired:
                safe_print("[CAPTURE] FAIL - 타임아웃 (300초)")
                return False

    # Phase 2: DOM 추출 — capture_oliveyoung.py가 통합 수행 (별도 실행 불필요)
    raw_path_check = os.path.join(DATA_DIR, f"_dom_extract_{today_str}.json")
    if not os.path.exists(raw_path_check):
        safe_print("[EXTRACT] WARN - DOM 파일 없음. 캡처 스크립트가 통합 추출했어야 함.")
        return False

    # Phase 3: 데이터 보강 Agent (스크린샷 1장씩 배치 처리)
    raw_path = os.path.join(DATA_DIR, f"_dom_extract_{today_str}.json")
    oy_path = os.path.join(DATA_DIR, f"oliveyoung_{today_str}.json")
    screenshots = sorted(
        glob.glob(os.path.join(SCREENSHOT_DIR, f"oliveyoung_{today_str}_*.png"))
    )
    ss_count = len(screenshots)
    safe_print(f"\n스크린샷 {ss_count}장, raw 데이터: {os.path.basename(raw_path)}")

    if not os.path.exists(raw_path):
        safe_print(f"[ERROR] {raw_path} 없음. DOM 추출 실패.")
        return False

    # raw JSON을 미리 로드하여 배치별 슬라이싱 (agent가 60개 전체를 읽지 않도록)
    with open(raw_path, "r", encoding="utf-8") as f:
        raw_products = json.load(f)

    rules = load_agent_rules("step1_extract.md")
    all_products = []

    def _run_enrich_batch(batch_idx, ss_path):
        """단일 배치 보강 처리 (병렬 실행용)."""
        rank_start = batch_idx * 12
        rank_end = min(rank_start + 12, 50)
        if rank_start >= 50:
            return []

        # 배치별 슬라이싱: 해당 rank 범위의 raw 데이터만 임시 파일로 저장
        batch_raw = raw_products[rank_start:rank_end]
        batch_raw_path = os.path.join(DATA_DIR, f"_dom_batch_{batch_idx}.json")
        with open(batch_raw_path, "w", encoding="utf-8") as f:
            json.dump(batch_raw, f, ensure_ascii=False, indent=2)

        batch_out = os.path.join(DATA_DIR, f"_enrich_batch_{batch_idx}.json")
        prompt = f"""{rules}

---

## 작업 대상 (배치 {batch_idx + 1}/{min(ss_count, 5)})
- raw DOM 추출 결과 (이 배치 분량만): {os.path.abspath(batch_raw_path)}
  - {len(batch_raw)}개 제품 (rank {rank_start + 1}~{rank_end})
- 스크린샷 (1장): {os.path.abspath(ss_path)}

## 출력
- 보강된 JSON을 다음 경로에 저장: {os.path.abspath(batch_out)}
- rank {rank_start + 1}~{rank_end} 제품 배열, 위 규칙의 필드 전부 포함
- raw 데이터와 스크린샷을 대조하여 정확성 확보
- is_duplicate는 false로 설정 (orchestrator가 전체 merge 후 판정)
- 문제가 있으면 파일은 생성하되, 콘솔에 issues를 출력"""

        safe_print(f"\n[ENRICH] 배치 {batch_idx + 1}/{min(ss_count, 5)}: rank {rank_start + 1}~{rank_end} 처리 중...")

        cmd = [
            CLAUDE_EXE, "-p",
            "--model", "opus",
            "--allowed-tools", "Read,Write,Glob",
            "--no-session-persistence",
        ]

        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True, text=True, timeout=TIMEOUT_ENRICH,
                encoding="utf-8", errors="replace",
                cwd=PROJECT_ROOT,
            )
        except subprocess.TimeoutExpired:
            safe_print(f"[ENRICH] 배치 {batch_idx + 1} 타임아웃 (900초)")
            return None

        if result.returncode != 0:
            safe_print(f"[ENRICH] 배치 {batch_idx + 1} 실패 - {(result.stderr or '')[:300]}")
            return None

        # 배치 raw 임시 파일 정리
        if os.path.exists(batch_raw_path):
            os.remove(batch_raw_path)

        if not os.path.exists(batch_out):
            safe_print(f"[ENRICH] 배치 {batch_idx + 1} 결과 파일 미생성")
            return None

        with open(batch_out, "r", encoding="utf-8") as f:
            batch_products = json.load(f)
        safe_print(f"[ENRICH] 배치 {batch_idx + 1} OK - {len(batch_products)}개 제품")
        os.remove(batch_out)
        return batch_products

    # 5배치 병렬 실행 (각 배치는 독립적: 서로 다른 스크린샷 + rank 범위)
    batches_to_run = [
        (idx, ss) for idx, ss in enumerate(screenshots) if idx * 12 < 50
    ]
    safe_print(f"\n[ENRICH] {len(batches_to_run)}개 배치 병렬 실행 시작...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(_run_enrich_batch, idx, ss): idx
            for idx, ss in batches_to_run
        }
        for future in concurrent.futures.as_completed(futures):
            batch_idx = futures[future]
            batch_result = future.result()
            if batch_result is None:
                return False
            all_products.extend(batch_result)

    # promotion_type 후처리: 명확한 패턴은 파이썬에서 보정 (agent 판단 부담 경감)
    for p in all_products:
        nf = p.get("name_full", "")
        pt = p.get("promotion_type", "none")
        # 오특 제품은 oteuk으로 확정
        if p.get("is_oteuk") and pt != "oteuk":
            p["promotion_type"] = "oteuk"
        # 1+1 패턴
        elif re.search(r"1\+1|1\s*\+\s*1", nf) and pt != "bogo":
            p["promotion_type"] = "bogo"
        # 더블/듀오 기획
        elif re.search(r"더블\s*기획|듀오\s*기획", nf) and pt not in ("double", "bogo"):
            p["promotion_type"] = "double"
        # 동일 용량 묶음 (50ml+50ml 등)
        elif re.search(r"(\d+)\s*ml\s*\+\s*\1\s*ml", nf) and pt != "double":
            p["promotion_type"] = "double"
        # 리필 기획
        elif re.search(r"리필\s*기획", nf) and pt != "refill":
            p["promotion_type"] = "refill"
        # 2입/2개 기획 (multi_pack)
        elif re.search(r"[23]\s*입\s*기획|[23]\s*개\s*기획", nf) and pt != "multi_pack":
            p["promotion_type"] = "multi_pack"
        # 애매한 패턴(본품+미니, 추가증정 등)은 agent 판단 유지 — 여기서 건드리지 않음

    # is_duplicate 후처리: name 기준 중복 판정
    name_count = {}
    for p in all_products:
        nm = p.get("name", "")
        name_count[nm] = name_count.get(nm, 0) + 1
    for p in all_products:
        nm = p.get("name", "")
        p["is_duplicate"] = name_count.get(nm, 0) > 1

    # rank 순 정렬 + 50개 제한
    all_products.sort(key=lambda x: x.get("rank", 999))
    all_products = all_products[:50]

    with open(oy_path, "w", encoding="utf-8") as f:
        json.dump(all_products, f, ensure_ascii=False, indent=2)

    safe_print(f"[ENRICH] OK - {os.path.basename(oy_path)} 생성 ({len(all_products)}개 제품)")
    return True


# ================================================================
#  Step 2: 올리브영 검증 (Verification Agent)
# ================================================================

def build_oy_verification_prompt_multi(today_str, ss_pairs):
    """올리브영 데이터 검증 프롬프트 생성 (스크린샷 2장 배치).

    Args:
        ss_pairs: list of (ss_index, ss_path) tuples
    """
    oy_path = os.path.join(DATA_DIR, f"oliveyoung_{today_str}.json")
    if not os.path.exists(oy_path):
        return None

    rank_start = ss_pairs[0][0] * 12 + 1
    rank_end = min((ss_pairs[-1][0] + 1) * 12, 50)

    ss_section = "\n".join(
        f"  - 스크린샷 {idx + 1} (rank {idx * 12 + 1}~{min((idx + 1) * 12, 50)}): {os.path.abspath(path)}"
        for idx, path in ss_pairs
    )

    rules = load_agent_rules("step2_oy_verify.md")

    return f"""{rules}

---

## 역할
너는 K-Beauty Trend Tracker의 데이터 검증자야.
다른 agent가 올리브영 베스트 랭킹 페이지에서 추출한 데이터를 처음 보는 상태에서 검증해.

## 검증 대상 (배치: rank {rank_start}~{rank_end})
스크린샷 파일 ({len(ss_pairs)}장):
{ss_section}

JSON 파일:
{os.path.abspath(oy_path)}
→ rank {rank_start}~{rank_end} 범위 제품만 검증하라.

## 검증 항목 (우선순위 순)
0. **총 제품 수 확인 (최우선)**: JSON에 정확히 50개 제품이 있는지 먼저 확인. 50개 미만이면 즉시 issues에 보고.
1. **스크린샷 rank 배지 1:1 대조**: 스크린샷의 각 제품 위치에 표시된 순위 번호 배지(01, 02, ...)를 읽고, 해당 위치의 제품이 JSON의 같은 rank에 있는지 전수 대조. rank가 1이라도 밀려있으면 보고.
2. 제품명 변조 여부 (가장 중요): JSON name이 스크린샷 실제 제품명과 일치하는지 엄격 대조
3. 오특 제품이 is_oteuk: true로 올바르게 태그되었는지
4. 스크린샷에 있는데 JSON에 빠진 제품이 없는지
5. search_keyword 품질: 위 규칙의 기준에 따라 제품별 대조
6. 번들/골라담기: 위 규칙의 확정 테이블과 대조, 새 번들은 보고
7. 비화장품: 위 규칙 기준으로 감지하여 보고
8. 기획상품 유형: 1+1, 더블, 리필, 2입 등 기획 유형 식별하여 보고

## 수정 및 보고 규칙
**명확한 오류는 직접 JSON 파일을 수정하고 auto_fixed에 기록해라:**
- 가격 불일치 (스크린샷 vs JSON) → JSON 수정
- brand_en 불일치 → 통일
- promotion_type 오류 (1+1인데 double 등) → 수정
- is_oteuk 누락/오류 → 수정
- is_duplicate 오류 → 수정

**사용자 확인이 필요한 것만 issues에 넣어라:**
- 비화장품 감지 (제거 여부는 사용자 판단)
- 새 번들 키워드 (확정 테이블에 없는 것)
- 애매한 기획상품 패널티 (본품+미니 등)
- 스크린샷이 불명확해서 판단 불가한 경우

## 출력 형식
{{"passed": true/false, "auto_fixed": ["Rank N: 수정 내용", ...], "issues": ["사용자 확인 필요 항목", ...]}}

passed는 사용자 확인이 필요한 issues가 없을 때만 true.
auto_fixed가 있어도 issues가 없으면 passed=true.
사소한 표기 차이(띄어쓰기, 약어)는 무시하고, 실질적 오류만 수정/보고해."""


def run_step2(today_str=None):
    """올리브영 데이터 검증 - 스크린샷 1장씩 배치 검증."""
    if today_str is None:
        today_str = datetime.now().strftime("%Y%m%d")

    safe_print(f"\n{'=' * 50}")
    safe_print(f"  Step 2: 올리브영 데이터 검증")
    safe_print(f"{'=' * 50}")

    oy_path = os.path.join(DATA_DIR, f"oliveyoung_{today_str}.json")
    if not os.path.exists(oy_path):
        safe_print(f"[ERROR] {oy_path} 없음. Step 1 + 추출 먼저 실행 필요.")
        return False

    with open(oy_path, "r", encoding="utf-8") as f:
        products = json.load(f)
    total = len(products)
    promo = sum(1 for p in products if p.get("is_oteuk"))
    safe_print(f"  제품 {total}개, 오특 {promo}개")

    screenshots = sorted(
        glob.glob(os.path.join(SCREENSHOT_DIR, f"oliveyoung_{today_str}_*.png"))
    )

    all_issues = []
    all_passed = True

    # 스크린샷 2장씩 묶어서 배치 구성 (5→3 프로세스, 토큰 절약)
    valid_ss = [(idx, ss) for idx, ss in enumerate(screenshots) if idx * 12 < 50]
    multi_batches = []
    for i in range(0, len(valid_ss), 2):
        multi_batches.append(valid_ss[i:i + 2])

    def _run_verify_multi(batch_idx, ss_pairs):
        rank_start = ss_pairs[0][0] * 12 + 1
        rank_end = min((ss_pairs[-1][0] + 1) * 12, 50)
        safe_print(f"\n[VERIFY] 배치 {batch_idx + 1}/{len(multi_batches)}: rank {rank_start}~{rank_end} ({len(ss_pairs)}장) 검증 중...")
        prompt = build_oy_verification_prompt_multi(today_str, ss_pairs)
        if not prompt:
            safe_print("[ERROR] 검증 프롬프트 생성 실패")
            return None
        result = run_verification_agent(prompt, timeout=600)
        safe_print(f"[VERIFY] 배치 {batch_idx + 1}: {'PASS' if result['passed'] else 'FAIL'} ({len(result.get('issues', []))}건)")
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_run_verify_multi, bi, pairs): bi
            for bi, pairs in enumerate(multi_batches)
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result is None:
                return False
            if not result["passed"]:
                all_passed = False
            all_issues.extend(result.get("issues", []))

    merged = {"passed": all_passed, "issues": all_issues}
    return handle_verification_result(merged, "올리브영")


# ================================================================
#  Step 3: 네이버 + 유튜브 API 수집
# ================================================================

def run_step3(today_str=None):
    """네이버/유튜브 API 수집 — Claude가 키워드 결정."""
    if today_str is None:
        today_str = datetime.now().strftime("%Y%m%d")

    safe_print(f"\n{'=' * 50}")
    safe_print(f"  Step 3: API 수집 (키워드 생성 + 네이버 + 유튜브)")
    safe_print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    safe_print(f"{'=' * 50}\n")

    # claude -p 인증 사전 확인
    if not check_claude_auth():
        safe_print("[STEP3] ABORT - claude -p 인증 실패. 로그인 필요.")
        return False

    # YouTube OAuth 토큰 사전 확인
    try:
        from scripts.youtube_oauth import is_oauth_configured, is_token_expired, refresh_credentials
        if is_oauth_configured():
            expired = is_token_expired()
            if expired:
                safe_print("[OAuth] YouTube 토큰 만료됨 → 갱신 시도")
                _, status = refresh_credentials()
                if status == "reauth_needed":
                    safe_print("[OAuth] 브라우저 재인증 필요! 터미널에서: python scripts/youtube_oauth.py")
                elif status == "refreshed":
                    safe_print("[OAuth] 토큰 갱신 완료")
            else:
                safe_print("[OAuth] YouTube 토큰 유효")
    except ImportError:
        pass  # OAuth 미설정 시 무시

    # 올리브영 JSON 확인
    oy_path = os.path.join(DATA_DIR, f"oliveyoung_{today_str}.json")
    if not os.path.exists(oy_path):
        oy_files = sorted(glob.glob(os.path.join(DATA_DIR, "oliveyoung_*.json")))
        oy_files = [f for f in oy_files if "sample" not in os.path.basename(f) and "keywords" not in os.path.basename(f)]
        if oy_files:
            oy_path = oy_files[-1]
        else:
            safe_print("[ERROR] 올리브영 데이터 없음. Step 1 먼저 실행.")
            return False
    safe_print(f"[OY] {os.path.basename(oy_path)}")

    # Phase 0: 올리브영 글로벌 몰에서 공식 영문명 수집 (이미 있으면 재사용)
    global_script = os.path.join(SCRIPTS_DIR, "fetch_global_names.py")
    global_names_path = os.path.join(DATA_DIR, f"_global_names_{today_str}.json")
    global_ok = False
    if os.path.exists(global_names_path) and os.path.getsize(global_names_path) > 100:
        safe_print(f"[GLOBAL] SKIP - {os.path.basename(global_names_path)} 이미 존재")
        global_ok = True
    max_global_retries = 3
    for attempt in range(1, max_global_retries + 1) if not global_ok else []:
        if not os.path.exists(global_script):
            safe_print("[GLOBAL ERROR] fetch_global_names.py 스크립트 없음 - Step 3 중단")
            return False
        try:
            safe_print(f"[GLOBAL] 영문명 수집 시도 {attempt}/{max_global_retries}")
            r = subprocess.run(
                [sys.executable, global_script],
                capture_output=True, text=True, timeout=TIMEOUT_CAPTURE,
                encoding="utf-8", errors="replace"
            )
            if r.returncode == 0 and os.path.exists(global_names_path):
                safe_print("[GLOBAL] 영문명 수집 완료")
                global_ok = True
                break
            else:
                stderr_msg = (r.stderr or "")[:200]
                safe_print(f"[GLOBAL] 시도 {attempt} 실패: {stderr_msg}")
        except Exception as e:
            safe_print(f"[GLOBAL] 시도 {attempt} 에러: {e}")
        if attempt < max_global_retries:
            time.sleep(5)

    if not global_ok:
        safe_print("[GLOBAL ERROR] 글로벌몰 영문명 수집 실패 (3회 재시도 후). Step 3 중단. 세션에서 알림 필요.")
        return False

    results = {}
    retry_script = os.path.join(SCRIPTS_DIR, "keyword_retry.py")

    # 유튜브는 키워드/영문명 불필요 (풀네임 검색) → 키워드 생성 전에 바로 시작
    def _run_youtube_pipeline():
        """유튜브 수집 + retry."""
        yt_script = os.path.join(SCRIPTS_DIR, "youtube_trend.py")
        if not os.path.exists(yt_script):
            safe_print("[YOUTUBE] SKIP - youtube_trend.py 없음")
            return None
        try:
            r = subprocess.run(
                [sys.executable, yt_script],
                capture_output=True, text=True, timeout=TIMEOUT_YOUTUBE,
                encoding="utf-8", errors="replace"
            )
            if r.returncode != 0:
                safe_print(f"[YOUTUBE] FAIL - {r.stderr[:200]}")
                return None
            safe_print("[YOUTUBE] OK")
            api_err_path = os.path.join(DATA_DIR, "_youtube_api_errors.txt")
            if os.path.exists(api_err_path):
                with open(api_err_path, "r", encoding="utf-8") as ef:
                    err_keywords = ef.read().strip().split("\n")
                safe_print(f"[YOUTUBE] API 에러 {len(err_keywords)}건!")
                os.remove(api_err_path)
        except Exception as e:
            safe_print(f"[YOUTUBE] FAIL - {e}")
            return None

        # 유튜브 retry
        if os.path.exists(retry_script):
            try:
                r = subprocess.run(
                    [sys.executable, retry_script, "youtube"],
                    capture_output=True, text=True, timeout=TIMEOUT_NAVER,
                    encoding="utf-8", errors="replace"
                )
                if r.returncode == 0:
                    for line in r.stdout.split("\n"):
                        if line.strip() and ("성공" in line or "개선" in line):
                            safe_print(f"  [YT RETRY] {line.strip()}")
            except Exception:
                pass

        yt_files = sorted(glob.glob(os.path.join(DATA_DIR, "youtube_*.json")))
        yt_files = [f for f in yt_files
                    if "sample" not in os.path.basename(f)]
        return yt_files[-1] if yt_files else None

    yt_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    yt_future = yt_executor.submit(_run_youtube_pipeline)
    safe_print("[YOUTUBE] 선행 시작 (키워드 생성과 병렬)")

    # Phase 1: Claude가 최적 키워드 생성 (당일 파일 있으면 건너뜀)
    keywords_path = os.path.join(DATA_DIR, f"_keywords_{today_str}.json")
    if os.path.exists(keywords_path) and os.path.getsize(keywords_path) > 100:
        safe_print(f"[KEYWORD] SKIP - {os.path.basename(keywords_path)} 이미 존재")
        kw_result = None  # skip
    else:
        kw_result = run_keyword_agent(oy_path, today_str=today_str)
    if kw_result and "keywords" in kw_result:
        # 50개 하드컷 (에이전트가 초과 반환해도 상위 50개만 저장)
        kw_list = kw_result["keywords"][:50]
        with open(keywords_path, "w", encoding="utf-8") as f:
            json.dump(kw_list, f, ensure_ascii=False, indent=2)
        safe_print(f"[KEYWORD] {len(kw_list)}개 키워드 생성 완료")
    else:
        safe_print("[KEYWORD] 키워드 생성 실패 - Step 3 중단")
        yt_executor.shutdown(wait=False)
        return False

    # Phase 1.5+2+3: 영문명 검증 + 네이버 + 유튜브 병렬 수집
    def _run_naver_pipeline():
        """네이버 수집 + retry."""
        nv_script = os.path.join(SCRIPTS_DIR, "naver_trend.py")
        if not os.path.exists(nv_script):
            safe_print("[NAVER] SKIP - naver_trend.py 없음")
            return None
        try:
            r = subprocess.run(
                [sys.executable, nv_script],
                capture_output=True, text=True, timeout=TIMEOUT_NAVER,
                encoding="utf-8", errors="replace"
            )
            if r.returncode != 0:
                safe_print(f"[NAVER] FAIL - {r.stderr[:200]}")
                return None
            safe_print("[NAVER] OK")
        except Exception as e:
            safe_print(f"[NAVER] FAIL - {e}")
            return None

        # 네이버 retry
        if os.path.exists(retry_script):
            try:
                r = subprocess.run(
                    [sys.executable, retry_script, "naver"],
                    capture_output=True, text=True, timeout=TIMEOUT_NAVER,
                    encoding="utf-8", errors="replace"
                )
                if r.returncode == 0:
                    for line in r.stdout.split("\n"):
                        if line.strip() and ("성공" in line or "개선" in line):
                            safe_print(f"  [NAVER RETRY] {line.strip()}")
            except Exception:
                pass

        nv_files = sorted(glob.glob(os.path.join(DATA_DIR, "naver_*.json")))
        nv_files = [f for f in nv_files
                    if "sample" not in os.path.basename(f)
                    and "rank" not in os.path.basename(f)]
        return nv_files[-1] if nv_files else None

    def _run_en_verify():
        """영문명 검증 (한글 풀네임과 대조)."""
        if os.path.exists(keywords_path):
            verify_english_names(oy_path, keywords_path)

    safe_print("\n[API] 영문명 검증 + 네이버 병렬 시작 (유튜브는 이미 실행 중)...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        en_future = executor.submit(_run_en_verify)
        nv_future = executor.submit(_run_naver_pipeline)
        en_future.result()
        results["naver"] = nv_future.result()
    results["youtube"] = yt_future.result()
    yt_executor.shutdown(wait=False)

    # 결과 보고
    zero_report = []
    nv_path = results.get("naver")
    if nv_path and os.path.exists(nv_path):
        with open(nv_path, "r", encoding="utf-8") as f:
            nv_data = json.load(f)
        nv_total = len(nv_data)
        nv_zero = sum(1 for n in nv_data if n.get("search_volume", n.get("search_volume_this_week", 0)) == 0)
        nv_pct = nv_zero * 100 // nv_total if nv_total else 0
        zero_report.append(f"네이버: {nv_zero}/{nv_total}건 검색량 0 ({nv_pct}%)")
        safe_print(f"[결과] 네이버 검색량 0: {nv_zero}/{nv_total} ({nv_pct}%)")

    yt_path_result = results.get("youtube")
    if yt_path_result and os.path.exists(yt_path_result):
        with open(yt_path_result, "r", encoding="utf-8") as f:
            yt_data = json.load(f)
        yt_total = len(yt_data)
        yt_zero = sum(1 for y in yt_data if y.get("video_count", 0) == 0)
        yt_err = sum(1 for y in yt_data if y.get("api_error", False))
        yt_pct = yt_zero * 100 // yt_total if yt_total else 0
        zero_report.append(f"유튜브: {yt_zero}/{yt_total}건 영상 0 ({yt_pct}%), API에러 {yt_err}건")
        safe_print(f"[결과] 유튜브 영상 0: {yt_zero}/{yt_total} ({yt_pct}%), API에러: {yt_err}")

    # 결과 경로를 임시 파일에 저장 (Step 4에서 사용)
    state = {
        "oy_path": oy_path,
        "naver_path": results.get("naver"),
        "youtube_path": results.get("youtube"),
        "today_str": today_str,
        "zero_report": zero_report,
    }
    state_path = os.path.join(DATA_DIR, "_pipeline_state.json")
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)

    return True


# ================================================================
#  Step 4: API 데이터 검증 (Verification Agent)
# ================================================================

def _precheck_api_anomalies(oy_path, nv_path, yt_path):
    """API 데이터의 수치 이상치를 파이썬으로 선검사. agent에게 넘길 요약 반환."""
    anomalies = []
    nv_ok = nv_path and os.path.exists(nv_path)
    yt_ok = yt_path and os.path.exists(yt_path)

    if not nv_ok and not yt_ok:
        anomalies.append("네이버/유튜브 데이터 모두 없음 — passed: false 처리 필요")
        return anomalies, []

    # --- 네이버 이상치 ---
    if nv_ok:
        with open(nv_path, "r", encoding="utf-8") as f:
            nv_data = json.load(f)
        total = len(nv_data)
        zero_count = sum(1 for p in nv_data if p.get("search_volume", 0) == 0)
        if total > 0 and zero_count / total >= 0.9:
            anomalies.append(f"네이버 API 이상: {zero_count}/{total} ({zero_count*100//total}%) 제품 검색량 0")

        # 직전 데이터 대비 10배 변동 체크
        prev_nv = _find_previous_daily_path("naver")
        if prev_nv:
            with open(prev_nv, "r", encoding="utf-8") as f:
                prev_data = json.load(f)
            prev_map = {p.get("product_code", p.get("keyword", "")): p.get("search_volume", 0) for p in prev_data}
            spikes = []
            for p in nv_data:
                code = p.get("product_code", p.get("keyword", ""))
                cur = p.get("search_volume", 0)
                prev = prev_map.get(code, 0)
                if prev > 0 and cur > 0 and (cur / prev >= 10 or prev / cur >= 10):
                    spikes.append(f"{code}: {prev}→{cur}")
            if spikes:
                anomalies.append(f"네이버 10배 변동 {len(spikes)}건: {', '.join(spikes[:5])}")

    # --- 유튜브 이상치 ---
    yt_flagged = []
    if yt_ok:
        with open(yt_path, "r", encoding="utf-8") as f:
            yt_data = json.load(f)
        for p in yt_data:
            code = p.get("product_code", "")
            issues = []
            if p.get("api_error", False):
                issues.append("api_error")
            vc3m = p.get("video_count_3month", 0)
            vc2w = p.get("video_count", 0)
            if vc3m != -1 and vc3m < vc2w:
                issues.append(f"3개월({vc3m}) < 2주({vc2w})")
            if vc3m >= 1000:
                issues.append(f"3개월 영상 {vc3m}개 — 키워드 과범위 의심")
            if issues:
                yt_flagged.append(f"{code}: {', '.join(issues)}")
        if yt_flagged:
            anomalies.append(f"유튜브 이상 {len(yt_flagged)}건: {'; '.join(yt_flagged[:5])}")

    # --- 신제품 후보 추출 (agent가 웹검색으로 최종 판단) ---
    new_candidates = []
    with open(oy_path, "r", encoding="utf-8") as f:
        oy_data = json.load(f)
    for p in oy_data:
        name_full = p.get("name_full", "")
        if any(tag in name_full for tag in ["[NEW", "선런칭", "런칭"]):
            new_candidates.append(p.get("product_code", ""))
    if yt_ok:
        for p in yt_data:
            if p.get("is_new_product_candidate") and p.get("product_code") not in new_candidates:
                new_candidates.append(p["product_code"])

    return anomalies, new_candidates


def build_api_verification_prompt(oy_path, nv_path, yt_path):
    """API 데이터 검증 프롬프트 생성 — 수치 이상치는 선처리 결과를 전달."""
    rules = load_agent_rules("step4_api_verify.md")

    # 파이썬 선처리: 수치 이상치 + 신제품 후보
    anomalies, new_candidates = _precheck_api_anomalies(oy_path, nv_path, yt_path)

    parts = [f"""{rules}

---

## 역할
너는 K-Beauty Trend Tracker의 데이터 검증자야.
수집 과정을 전혀 모르는 상태에서, 결과 파일만 보고 검증해.

## 파이썬 선처리 결과 (수치 이상치)"""]

    if anomalies:
        for a in anomalies:
            parts.append(f"- ⚠ {a}")
        parts.append("위 이상치가 실제 문제인지 확인하고 issues에 포함 여부를 판단해.")
    else:
        parts.append("- 수치 이상치 없음 (네이버 0값 비율, 10배 변동, 유튜브 3개월<2주 등 모두 정상)")

    # 신제품 후보는 agent가 웹검색으로 최종 확인 — 브랜드+제품명도 함께 전달
    if new_candidates:
        parts.append(f"\n## 신제품 후보 (웹검색으로 출시일 확인 필요)")
        with open(oy_path, "r", encoding="utf-8") as f:
            oy_for_new = json.load(f)
        oy_map = {p["product_code"]: p for p in oy_for_new}
        for code in new_candidates:
            p = oy_map.get(code, {})
            parts.append(f"- {code}: {p.get('brand', '')} {p.get('name', '')}")
        parts.append("각 후보의 출시일을 웹검색('[브랜드] [제품명] 출시일')으로 확인하여 1주 이내면 new_launches에 추가.")
    else:
        parts.append("\n## 신제품 후보: 없음")

    # 키워드 잔여물 검사는 여전히 agent가 전수 확인 (유튜브 JSON 직접 읽기 필요)
    parts.append(f"\n## 검증 대상 파일 (키워드 잔여물 전수 검사용)")
    parts.append(f"올리브영: {os.path.abspath(oy_path)}")

    if nv_path and os.path.exists(nv_path):
        parts.append(f"네이버: {os.path.abspath(nv_path)}")
    else:
        parts.append("네이버: (수집 실패 또는 없음)")

    if yt_path and os.path.exists(yt_path):
        parts.append(f"유튜브: {os.path.abspath(yt_path)}")
    else:
        parts.append("유튜브: (수집 실패 또는 없음)")

    parts.append(f"""
## 남은 검증 항목
1. 유튜브 keyword 필드 전수 검사 (용량/기획/잔여물 체크 — 규칙 참조)
2. 비화장품 필터 확인
3. 위 선처리 결과의 이상치 판단
4. 신제품 후보 웹검색 확인

## 출력 형식
반드시 아래 JSON 형식으로만 응답해:
- 모두 정상이면: {{"passed": true, "issues": [], "new_launches": ["코드1", ...]}}
- 문제 있으면: {{"passed": false, "issues": ["문제1", "문제2", ...], "new_launches": []}}

new_launches는 검증 통과 여부와 무관하게 항상 포함.
수집 실패(파일 없음)는 issues에 기록하되, 네이버/유튜브 중 하나만 실패해도 passed: true 가능.
둘 다 실패했으면 passed: false.""")

    return "\n".join(parts)


def run_step4(today_str=None):
    """API 데이터 검증 - 독립 Verification Agent 호출 + 결과 저장.

    검증 Agent는 별도 프로세스(claude -p)로 실행되며:
    - Read, Glob 도구만 사용 가능 (Bash, Write 불가 → 데이터 수정 불가)
    - --no-session-persistence → 수집 과정 기억 없음
    - 결과는 _verification_result.json에 파일 해시와 함께 저장
    - Step 5가 이 파일을 하드체크 → 검증 없이 진행 불가
    """
    if today_str is None:
        today_str = datetime.now().strftime("%Y%m%d")

    safe_print(f"\n{'=' * 50}")
    safe_print(f"  Step 4: API 데이터 검증 (독립 검증 Agent)")
    safe_print(f"{'=' * 50}")

    # 파이프라인 상태 로드
    state_path = os.path.join(DATA_DIR, "_pipeline_state.json")
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = {
            "oy_path": os.path.join(DATA_DIR, f"oliveyoung_{today_str}.json"),
            "naver_path": None,
            "youtube_path": None,
            "today_str": today_str,
        }

    oy_path = state["oy_path"]
    nv_path = state.get("naver_path")
    yt_path = state.get("youtube_path")

    if not os.path.exists(oy_path):
        safe_print(f"[ERROR] {oy_path} 없음")
        return False

    prompt = build_api_verification_prompt(oy_path, nv_path, yt_path)
    result = run_verification_agent(prompt, allowed_tools="Read,Write,Glob,WebFetch,WebSearch")

    # === 검증 결과를 파일로 저장 (Step 5에서 강제 확인) ===
    file_hashes = {}
    for label, path in [("oliveyoung", oy_path), ("naver", nv_path), ("youtube", yt_path)]:
        if path and os.path.exists(path):
            file_hashes[label] = compute_file_hash(path)

    verification_data = {
        "passed": result["passed"],
        "issues": result["issues"],
        "new_launches": result.get("new_launches", []),
        "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "verified_date": today_str,
        "file_hashes": file_hashes,
        "verified_by": "claude -p verification agent (independent process)",
    }

    vr_path = os.path.join(DATA_DIR, "_verification_result.json")
    with open(vr_path, "w", encoding="utf-8") as f:
        json.dump(verification_data, f, ensure_ascii=False, indent=2)
    safe_print(f"[VERIFY] 검증 결과 저장: _verification_result.json")

    return handle_verification_result(result, "API")


# ================================================================
#  태국어 이름 자동 생성
# ================================================================

def _verify_thai_batch(batch, batch_idx):
    """번역된 태국어 이름으로 Shopee 검색해서 동일 제품인지 검증. 병렬 실행용."""
    product_list = json.dumps(batch, ensure_ascii=False, indent=2)

    prompt = f"""아래 화장품의 태국어 번역명이 정확한지 Shopee Thailand에서 검증해줘.

## 작업 순서
각 제품마다:
1. name_th(번역된 태국어 이름)로 Shopee Thailand 검색
   - WebFetch로 https://shopee.co.th/search?keyword={{name_th에서 핵심 2-3단어}} 검색
2. 검색 결과에서 동일 제품이 나오는지 확인
3. 결과:
   - 동일 제품 확인됨 → verified: true, Shopee에서 쓰는 태국어 이름이 다르면 corrected_name_th에 수정
   - 동일 제품 못 찾음 → verified: false, 번역명 그대로 유지
   - Shopee에서 더 자연스러운 이름을 쓰고 있으면 corrected_name_th에 그 이름 기록 (용량/수량 제거)

## 규칙
- 용량(ml, g), 수량, 프로모션 정보는 절대 포함하지 않음
- Shopee 검색 결과에서 브랜드+제품 핵심명만 추출

제품 목록:
{product_list}"""

    schema = json.dumps({
        "type": "object",
        "properties": {
            "verifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_code": {"type": "string"},
                        "verified": {"type": "boolean"},
                        "corrected_name_th": {"type": "string"}
                    },
                    "required": ["product_code", "verified"]
                }
            }
        },
        "required": ["verifications"]
    })

    try:
        result = subprocess.run(
            [CLAUDE_EXE, "-p", "--model", "sonnet",
             "--output-format", "json",
             "--max-turns", "8", "--allowed-tools", "WebFetch",
             "--json-schema", schema],
            input=prompt, capture_output=True, text=True, timeout=600,
            encoding="utf-8", errors="replace",
            cwd=BASE_DIR
        )
        if result.returncode != 0:
            safe_print(f"[TH] 검증 배치 {batch_idx} 실패 (returncode={result.returncode})")
            return []

        response = json.loads(result.stdout)
        parsed = response.get("structured_output", {})
        if not parsed:
            text = response.get("result", "")
            parsed = json.loads(text)
        return parsed.get("verifications", [])

    except subprocess.TimeoutExpired:
        safe_print(f"[TH] 검증 배치 {batch_idx} 타임아웃 (240s)")
        return []
    except (json.JSONDecodeError, KeyError) as e:
        safe_print(f"[TH] 검증 배치 {batch_idx} 파싱 실패: {e}")
        return []


def generate_thai_names():
    """score_calculator 출력(weekly_ranking)에서 최종 30위 제품 중
    thai_names.json에 없는 제품의 태국어 이름을 생성.
    Phase 1: claude -p로 한국어→태국어 번역 (도구 없음, 빠름)
    Phase 2: 번역명으로 Shopee 검색해서 검증 (병렬 배치)"""
    thai_path = os.path.join(DATA_DIR, "thai_names.json")
    thai_names = {}
    if os.path.exists(thai_path):
        with open(thai_path, "r", encoding="utf-8") as f:
            thai_names = json.load(f)

    # 최신 weekly_ranking 파일에서 최종 30위 제품 읽기
    ranking_files = sorted(glob.glob(os.path.join(DATA_DIR, "weekly_ranking_*.json")))
    if not ranking_files:
        safe_print("[TH] weekly_ranking 파일 없음 — 스킵")
        return

    try:
        with open(ranking_files[-1], "r", encoding="utf-8") as f:
            ranking = json.load(f)
        products = ranking.get("products", [])
    except (json.JSONDecodeError, KeyError):
        safe_print("[TH] weekly_ranking 파싱 실패 — 스킵")
        return

    # thai_names.json에 없는 제품만 필터
    missing = []
    for p in products:
        code = p.get("product_code", "")
        name = p.get("name_ko", "")
        if code and name and (code not in thai_names or not thai_names[code]):
            missing.append({"product_code": code, "name": name})

    if not missing:
        safe_print(f"[TH] 최종 {len(products)}개 제품 모두 태국어 이름 있음")
        return

    safe_print(f"[TH] 태국어 이름 누락 {len(missing)}개")

    # ── Phase 1: 번역 (도구 없음, 전체 한번에) ──
    safe_print("[TH] Phase 1: 한국어 → 태국어 번역")
    product_list = json.dumps(missing, ensure_ascii=False, indent=2)

    translate_prompt = f"""아래 한국어 화장품 제품명을 태국어로 번역해줘.

규칙:
- 브랜드명은 영어 그대로 유지 (예: Torriden, CLIO, rom&nd)
- 제품 고유명/라인명도 영어면 영어 유지 (예: DIVE-IN, Kill Cover)
- 한국어 일반명사(세럼, 크림, 쿠션, 마스크팩 등)만 태국어로 번역
- 용량, 수량, 기획 정보는 절대 포함하지 않음

제품 목록:
{product_list}"""

    translate_schema = json.dumps({
        "type": "object",
        "properties": {
            "translations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_code": {"type": "string"},
                        "name_th": {"type": "string"}
                    },
                    "required": ["product_code", "name_th"]
                }
            }
        },
        "required": ["translations"]
    })

    try:
        result = subprocess.run(
            [CLAUDE_EXE, "-p", "--model", "sonnet",
             "--output-format", "json",
             "--max-turns", "2", "--allowed-tools", "",
             "--json-schema", translate_schema],
            input=translate_prompt, capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
            cwd=BASE_DIR
        )
        if result.returncode != 0:
            safe_print("[TH] Phase 1 번역 실패")
            return

        response = json.loads(result.stdout)
        parsed = response.get("structured_output", {})
        if not parsed:
            parsed = json.loads(response.get("result", "{}"))
        translations = parsed.get("translations", [])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as e:
        safe_print(f"[TH] Phase 1 실패: {e}")
        return

    if not translations:
        safe_print("[TH] Phase 1 번역 결과 없음")
        return

    # 번역 결과를 code -> name_th 매핑
    translated = {}
    missing_codes = {item["product_code"] for item in missing}
    for item in translations:
        code = item.get("product_code", "")
        name_th = item.get("name_th", "")
        if code and name_th and code in missing_codes:
            translated[code] = name_th

    safe_print(f"[TH] Phase 1 완료: {len(translated)}개 번역")
    for code, name_th in translated.items():
        ko = next((m["name"] for m in missing if m["product_code"] == code), "")
        safe_print(f"  {ko} -> {name_th}")

    # ── Phase 2: Shopee 검증 (병렬 배치) ──
    safe_print("[TH] Phase 2: Shopee 검색으로 검증")

    # 검증할 제품 목록 구성
    verify_items = []
    for code, name_th in translated.items():
        ko = next((m["name"] for m in missing if m["product_code"] == code), "")
        verify_items.append({
            "product_code": code, "name_ko": ko, "name_th": name_th
        })

    BATCH_SIZE = 3
    batches = [verify_items[i:i + BATCH_SIZE]
               for i in range(0, len(verify_items), BATCH_SIZE)]
    all_verifications = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(batches), 3)) as executor:
        futures = {
            executor.submit(_verify_thai_batch, batch, idx): idx
            for idx, batch in enumerate(batches)
        }
        for future in concurrent.futures.as_completed(futures):
            batch_idx = futures[future]
            try:
                result = future.result()
                all_verifications.extend(result)
                safe_print(f"  검증 배치 {batch_idx} 완료: {len(result)}개")
            except Exception as e:
                safe_print(f"  검증 배치 {batch_idx} 에러: {e}")

    # ── 결과 병합: 검증된 이름 우선, 아니면 번역명 사용 ──
    verification_map = {v["product_code"]: v for v in all_verifications}
    added = 0
    verified_count = 0
    corrected_count = 0

    for code, name_th in translated.items():
        v = verification_map.get(code)
        final_name = name_th
        tag = "[번역]"

        if v:
            corrected = v.get("corrected_name_th", "").strip()
            if v.get("verified"):
                if corrected:
                    final_name = corrected
                    tag = "[Shopee 수정]"
                    corrected_count += 1
                else:
                    tag = "[Shopee 확인]"
                verified_count += 1

        thai_names[code] = final_name
        added += 1
        ko = next((m["name"] for m in missing if m["product_code"] == code), code)
        safe_print(f"  + {tag} {ko} -> {final_name}")

    if added > 0:
        with open(thai_path, "w", encoding="utf-8") as f:
            json.dump(thai_names, f, ensure_ascii=False, indent=2)
        safe_print(f"[TH] {added}개 추가 (Shopee 확인: {verified_count}, "
                   f"수정: {corrected_count}, 미검증: {added - verified_count}) "
                   f"— 총 {len(thai_names)}개")

    else:
        safe_print("[TH] 결과 없음")

    # weekly_ranking의 name_th를 thai_names.json 기준으로 동기화
    # (누락 제품이 없더라도, 기존 name_th가 오래된 값이면 갱신)
    try:
        with open(ranking_files[-1], "r", encoding="utf-8") as f:
            ranking = json.load(f)
        synced = 0
        for p in ranking.get("products", []):
            code = p.get("product_code", "")
            if code in thai_names:
                correct = thai_names[code]
                if p.get("name_th") != correct:
                    p["name_th"] = correct
                    synced += 1
        if synced > 0:
            with open(ranking_files[-1], "w", encoding="utf-8") as f:
                json.dump(ranking, f, ensure_ascii=False, indent=2)
            safe_print(f"[TH] weekly_ranking 동기화: {synced}개 name_th 갱신")
        else:
            safe_print("[TH] weekly_ranking 동기화 완료 (변경 없음)")
    except (json.JSONDecodeError, KeyError):
        safe_print("[TH] weekly_ranking 동기화 실패")


# ================================================================
#  Step 5: daily 저장 + 3일치 확인 + 갱신
# ================================================================

def run_step5(today_str=None):
    """daily 폴더 저장 + 3일치 확인 + score 계산 + 사이트 갱신."""
    if today_str is None:
        today_str = datetime.now().strftime("%Y%m%d")
    today = datetime.strptime(today_str, "%Y%m%d")
    start = time.time()

    safe_print(f"\n{'=' * 50}")
    safe_print(f"  Step 5: 저장 + 갱신 확인")
    safe_print(f"{'=' * 50}\n")

    # 이전 날짜 불완전 daily 폴더 + 좀비 상태/임시 파일 + 루트 데이터 파일 정리
    cleanup_incomplete_daily(today_str)
    cleanup_stale_state_files(today_str)

    # ================================================================
    # 검증 결과 강제 확인 (하드코딩 — 우회 불가)
    # _verification_result.json이 없거나 passed=false면 여기서 중단.
    # 파일 해시까지 대조해서 검증 이후 데이터 변조도 감지.
    # ================================================================
    vr_path = os.path.join(DATA_DIR, "_verification_result.json")
    if not os.path.exists(vr_path):
        safe_print("[BLOCK] _verification_result.json 없음")
        safe_print("  Step 4 (독립 검증)를 먼저 실행해야 합니다.")
        safe_print("  검증 없이는 절대 진행 불가.")
        return False

    with open(vr_path, "r", encoding="utf-8") as f:
        vr = json.load(f)

    if not vr.get("passed"):
        safe_print("[BLOCK] 검증 실패 상태 — Step 5 진행 불가")
        for issue in vr.get("issues", []):
            safe_print(f"  - {issue}")
        safe_print("  데이터를 수정하고 Step 4를 다시 실행하세요.")
        return False

    if vr.get("verified_date") != today_str:
        safe_print(f"[BLOCK] 검증 결과가 오늘({today_str})이 아님: {vr.get('verified_date')}")
        safe_print("  Step 4를 다시 실행하세요.")
        return False

    safe_print("[CHECK] 검증 결과 확인: passed=true")

    # 파이프라인 상태 로드
    state_path = os.path.join(DATA_DIR, "_pipeline_state.json")
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = {"oy_path": os.path.join(DATA_DIR, f"oliveyoung_{today_str}.json"),
                 "naver_path": None, "youtube_path": None, "today_str": today_str}

    oy_path = state["oy_path"]
    nv_path = state.get("naver_path")
    yt_path = state.get("youtube_path")

    # 파일 해시 대조 (검증 이후 데이터 변조 방지)
    saved_hashes = vr.get("file_hashes", {})
    for label, path in [("oliveyoung", oy_path), ("naver", nv_path), ("youtube", yt_path)]:
        if path and os.path.exists(path) and label in saved_hashes:
            current_hash = compute_file_hash(path)
            if current_hash != saved_hashes[label]:
                safe_print(f"[BLOCK] {label} 파일이 검증 이후 변경됨!")
                safe_print("  검증된 데이터와 현재 데이터가 다릅니다.")
                safe_print("  Step 4를 다시 실행하세요.")
                return False

    safe_print("[CHECK] 파일 해시 일치 — 검증 후 변조 없음")

    # ── 최종 체크: orchestrator 승인 게이트 (매일 daily 저장 전) ──
    # _final_check_approved.json이 없으면 최종 확인 요청 후 중단.
    # orchestrator가 확인 완료 후 이 파일을 생성하고 step5를 재실행.
    new_launches = vr.get("new_launches", [])
    approval_path = os.path.join(DATA_DIR, "_final_check_approved.json")
    if not os.path.exists(approval_path):
        daily_path_preview = os.path.join(DAILY_DIR, today.strftime("%Y-%m-%d"))
        final_check_path = os.path.join(DATA_DIR, "_final_check_needed.json")
        final_check = {
            "status": "waiting_approval",
            "today_str": today_str,
            "daily_path": daily_path_preview,
            "new_launches": new_launches,
            "oy_path": oy_path,
            "nv_path": nv_path,
            "yt_path": yt_path,
            "check_items": [
                "스크린샷 vs 최종 데이터 대조 (제품명, 가격, 순위, 총 제품 수)",
                "오특(오늘의 특가) 제품 정확히 표기되었는지",
                "유튜브/네이버 0건 제품 확인 (신제품 vs 기존제품 분류)",
                "유튜브 fallback 적용 제품 목록 및 0.7 할인 확인",
                "신제품(LAUNCH) 표기 정확한지",
                "비화장품 정상 제외되었는지",
                "동일 제품 중복(병합 대상) 키워드 일치 확인",
                "번들/골라담기 제품 키워드가 agent 규칙 확정 테이블과 일치하는지",
                "글로벌몰 영문명(english_name) 정상 수집되었는지",
                "전일 대비 급격한 순위 변동 (데이터 오류 가능성 체크)",
            ],
        }
        with open(final_check_path, "w", encoding="utf-8") as f:
            json.dump(final_check, f, ensure_ascii=False, indent=2)
        safe_print(f"\n[FINAL CHECK] daily 저장 전 최종 확인 필요")
        safe_print("  orchestrator가 스크린샷 대조 후 세션에서 승인 요청합니다.")
        safe_print("  승인 후 step5를 다시 실행하면 저장이 진행됩니다.")
        return "WAITING_APPROVAL"

    # 승인 완료 — 임시 파일 정리
    safe_print("[APPROVED] 최종 확인 승인 완료 — daily 저장 진행")
    for tmp in [approval_path, os.path.join(DATA_DIR, "_final_check_needed.json")]:
        if os.path.exists(tmp):
            os.remove(tmp)

    # daily 폴더에 저장
    date_folder = today.strftime("%Y-%m-%d")
    daily_path = os.path.join(DAILY_DIR, date_folder)
    os.makedirs(daily_path, exist_ok=True)

    saved = 0
    saved_sources = {}
    for src, prefix in [(oy_path, "oliveyoung"), (nv_path, "naver"), (yt_path, "youtube")]:
        if src and os.path.exists(src):
            dest = os.path.join(daily_path, f"{prefix}_{today_str}.json")
            shutil.copy2(src, dest)
            saved += 1
            saved_sources[prefix] = os.path.basename(src)
            safe_print(f"  -> daily/{date_folder}/{prefix}_{today_str}.json")

    # 수집 메타데이터 기록 (이 날짜가 실제 파이프라인 수집인지 증명)
    new_launches = vr.get("new_launches", [])
    meta = {
        "collected_at": today.strftime("%Y-%m-%d %H:%M:%S"),
        "collected_by": "run_daily_collect.py pipeline",
        "sources": saved_sources,
        "verified": True,
        "verified_at": vr.get("verified_at"),
        "verified_by": vr.get("verified_by"),
        "file_hashes": saved_hashes,
        "new_launches": new_launches,
    }
    meta_path = os.path.join(daily_path, "_collection_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    safe_print(f"[SAVE] {saved}개 파일 저장 + 메타데이터 기록")
    if new_launches:
        safe_print(f"[LAUNCH] 신제품 {len(new_launches)}개: {', '.join(new_launches)}")

    # 3일치 완전 수집 확인 (올리브영+네이버+유튜브 모두 있어야 함)
    complete_count, incomplete_days = count_complete_daily_data()
    oy_only_count = count_daily_data()

    safe_print(f"\n  완전 수집(OY+NV+YT): {complete_count}/{PERIOD_DAYS}일")
    safe_print(f"  올리브영만 수집: {oy_only_count}일")

    if incomplete_days:
        for day, missing in incomplete_days:
            safe_print(f"  {day}: {', '.join(missing)} 누락")

    # 영문명 영구 저장 (score_calculator 전에 override에 반영해야 함)
    kw_tmp_path = os.path.join(DATA_DIR, f"_keywords_{today_str}.json")
    if os.path.exists(kw_tmp_path):
        try:
            with open(kw_tmp_path, "r", encoding="utf-8") as f:
                kw_data = json.load(f)
            if isinstance(kw_data, dict) and "keywords" in kw_data:
                kw_data = kw_data["keywords"]
            en_names_daily = {}
            for kw in kw_data:
                code = kw.get("product_code", "")
                en = kw.get("english_name", "")
                if code and en:
                    en_names_daily[code] = en
            # daily 폴더에 영문명 저장
            if en_names_daily:
                en_daily_path = os.path.join(daily_path, f"english_names_{today_str}.json")
                with open(en_daily_path, "w", encoding="utf-8") as f:
                    json.dump(en_names_daily, f, ensure_ascii=False, indent=2)
                safe_print(f"  -> daily/{date_folder}/english_names_{today_str}.json ({len(en_names_daily)}개)")
            # english_names_override.json에 누적 (한글 포함 건 제외)
            override_path = os.path.join(DATA_DIR, "english_names_override.json")
            en_override = {}
            if os.path.exists(override_path):
                with open(override_path, "r", encoding="utf-8") as f:
                    en_override = json.load(f)
            added = 0
            for code, en in en_names_daily.items():
                if code not in en_override and not any(ord(c) >= 0xAC00 for c in en):
                    en_override[code] = en
                    added += 1
            if added > 0:
                with open(override_path, "w", encoding="utf-8") as f:
                    json.dump(en_override, f, ensure_ascii=False, indent=2)
                safe_print(f"[EN] 영문명 {added}개 신규 누적 (총 {len(en_override)}개)")
        except (json.JSONDecodeError, KeyError) as e:
            safe_print(f"[EN] 영문명 저장 실패: {e}")

    if complete_count >= PERIOD_DAYS:
        # 마지막 사이트 갱신 이후 새 데이터가 3일 이상 쌓였는지 확인
        site_update_path = os.path.join(DATA_DIR, "_last_site_update.json")
        should_update_site = True  # 기본값: 갱신 진행

        if os.path.exists(site_update_path):
            try:
                with open(site_update_path, "r", encoding="utf-8") as f:
                    site_update_info = json.load(f)
                last_update_date = site_update_info.get("last_update_date", "")

                # 마지막 갱신 이후 새로 쌓인 daily 날짜 수 계산
                new_days = _count_daily_since(last_update_date)
                if new_days < PERIOD_DAYS:
                    safe_print(f"\n[SKIP] 사이트 갱신 스킵 ({new_days}일/{PERIOD_DAYS}일 수집됨)")
                    safe_print(f"  마지막 갱신: {last_update_date}")
                    safe_print(f"  {PERIOD_DAYS - new_days}일 더 수집되면 갱신합니다.")
                    should_update_site = False
                else:
                    safe_print(f"\n마지막 갱신({last_update_date}) 이후 {new_days}일 새 데이터 -> 사이트 갱신 시작")
            except (json.JSONDecodeError, KeyError):
                safe_print("\n[WARN] _last_site_update.json 손상 — 갱신 진행")
        else:
            safe_print(f"\n{complete_count}일치 완전 데이터 (첫 갱신) -> 사이트 갱신 시작")

        if should_update_site:
            # score_calculator
            calc_script = os.path.join(BASE_DIR, "score_calculator.py")
            calc = subprocess.run(
                [sys.executable, calc_script],
                capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="replace"
            )
            if calc.returncode == 0:
                safe_print("[CALC] OK")
                for line in calc.stdout.split("\n"):
                    if line.strip():
                        safe_print(f"  {line.strip()}")
            else:
                safe_print(f"[CALC] FAIL - {calc.stderr[:200]}")
                return False

            # 태국어 이름 생성 (최종 30위 제품 중 누락분)
            generate_thai_names()

            # 태국어 이름 검증 (사이트 생성 전 게이트)
            th_check = os.path.join(SCRIPTS_DIR, "check_thai_names.py")
            if os.path.exists(th_check):
                th_result = subprocess.run(
                    [sys.executable, th_check],
                    capture_output=True, text=True, timeout=10,
                    encoding="utf-8", errors="replace"
                )
                for line in th_result.stdout.strip().split("\n"):
                    if line.strip():
                        safe_print(f"  {line.strip()}")
                if th_result.returncode != 0:
                    safe_print("[TH_CHECK] 태국어 이름 문제 발견 — 사이트 생성 중단")
                    return False

            # generate_site
            site_script = os.path.join(BASE_DIR, "generate_site.py")
            if os.path.exists(site_script):
                site = subprocess.run(
                    [sys.executable, site_script],
                    capture_output=True, text=True, timeout=30,
                    encoding="utf-8", errors="replace"
                )
                if site.returncode == 0:
                    safe_print("[SITE] OK")
                else:
                    safe_print(f"[SITE] FAIL - {site.stderr[:200]}")
                    return False

            # 갱신 완료 후 _last_site_update.json 기록
            complete_folders = _get_complete_daily_folders()
            if complete_folders:
                period_start = complete_folders[0]
                period_end = complete_folders[-1]
                period_str = f"{period_start} ~ {period_end}"
            else:
                period_str = today.strftime("%Y-%m-%d")

            # last_update_date는 갱신에 포함된 마지막 daily 날짜로 기록
            # (오늘 날짜가 아님 — 다음 주기 카운트 기준점)
            if complete_folders:
                last_daily = complete_folders[-1].replace("-", "")
            else:
                last_daily = today_str
            site_update_record = {
                "last_update_date": last_daily,
                "period": period_str,
                "updated_at": today.strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(site_update_path, "w", encoding="utf-8") as f:
                json.dump(site_update_record, f, ensure_ascii=False, indent=2)
            safe_print(f"[RECORD] 사이트 갱신 기록: {today_str} (구간: {period_str})")

            safe_print("\n[GIT] 커밋 + 푸시는 수동 또는 Claude Code에서 실행하세요.")
    else:
        remaining = PERIOD_DAYS - complete_count
        safe_print(f"\n사이트 갱신 불가: 네이버/유튜브 데이터 누락 "
                    f"({complete_count}/{PERIOD_DAYS}일 완전 수집, {remaining}일 더 필요)")

    # 임시 파일 정리
    for tmp in [state_path, vr_path, kw_tmp_path,
                os.path.join(DATA_DIR, f"_global_names_{today_str}.json")]:
        if os.path.exists(tmp):
            os.remove(tmp)

    # 스크린샷 archive 이동
    archive_dir = os.path.join(SCREENSHOT_DIR, "Archive", today_str[:4] + "-" + today_str[4:6])
    ss_files = glob.glob(os.path.join(SCREENSHOT_DIR, f"oliveyoung_{today_str}_*.png"))
    if ss_files:
        os.makedirs(archive_dir, exist_ok=True)
        for ss in ss_files:
            dest = os.path.join(archive_dir, os.path.basename(ss))
            shutil.move(ss, dest)
        safe_print(f"[ARCHIVE] 스크린샷 {len(ss_files)}장 → archive/{today_str[:4]}-{today_str[4:6]}/")

    elapsed = time.time() - start
    safe_print(f"\nStep 5 완료: {elapsed:.1f}s")
    return True


# ================================================================
#  유틸리티
# ================================================================

def _count_daily_since(last_update_date_str):
    """마지막 갱신일(YYYYMMDD) 이후 새로 완전 수집된 daily 날짜 수."""
    if not os.path.isdir(DAILY_DIR):
        return 0
    # last_update_date_str -> YYYY-MM-DD 폴더명 비교용
    if len(last_update_date_str) == 8:
        cutoff = f"{last_update_date_str[:4]}-{last_update_date_str[4:6]}-{last_update_date_str[6:8]}"
    else:
        cutoff = last_update_date_str
    count = 0
    for folder in sorted(os.listdir(DAILY_DIR)):
        folder_path = os.path.join(DAILY_DIR, folder)
        if not os.path.isdir(folder_path) or folder <= cutoff:
            continue
        meta = os.path.exists(os.path.join(folder_path, "_collection_meta.json"))
        oy = [f for f in glob.glob(os.path.join(folder_path, "oliveyoung_*.json"))
              if "sample" not in os.path.basename(f)]
        nv = [f for f in glob.glob(os.path.join(folder_path, "naver_*.json"))
              if "sample" not in os.path.basename(f)]
        yt = [f for f in glob.glob(os.path.join(folder_path, "youtube_*.json"))
              if "sample" not in os.path.basename(f)]
        if oy and nv and yt and meta:
            count += 1
    return count


def _get_complete_daily_folders():
    """완전 수집된 daily 폴더명(YYYY-MM-DD) 목록을 정렬하여 반환."""
    if not os.path.isdir(DAILY_DIR):
        return []
    folders = []
    for folder in sorted(os.listdir(DAILY_DIR)):
        folder_path = os.path.join(DAILY_DIR, folder)
        if not os.path.isdir(folder_path):
            continue
        meta = os.path.exists(os.path.join(folder_path, "_collection_meta.json"))
        oy = [f for f in glob.glob(os.path.join(folder_path, "oliveyoung_*.json"))
              if "sample" not in os.path.basename(f)]
        nv = [f for f in glob.glob(os.path.join(folder_path, "naver_*.json"))
              if "sample" not in os.path.basename(f)]
        yt = [f for f in glob.glob(os.path.join(folder_path, "youtube_*.json"))
              if "sample" not in os.path.basename(f)]
        if oy and nv and yt and meta:
            folders.append(folder)
    return folders


def count_daily_data():
    """data/daily/에서 oliveyoung 데이터가 있는 날짜 수."""
    if not os.path.isdir(DAILY_DIR):
        return 0
    count = 0
    for folder in sorted(os.listdir(DAILY_DIR)):
        folder_path = os.path.join(DAILY_DIR, folder)
        if os.path.isdir(folder_path):
            if glob.glob(os.path.join(folder_path, "oliveyoung_*.json")):
                count += 1
    return count


def count_complete_daily_data():
    """data/daily/에서 파이프라인으로 실제 수집되고 3종 모두 있는 날짜 수.

    실제 수집 판별 기준:
    - _collection_meta.json 파일이 존재 (파이프라인이 기록)
    - 또는 올리브영+네이버+유튜브 3종 모두 존재 (레거시 호환)
    샘플 데이터(파일명에 sample 포함)는 제외.
    """
    if not os.path.isdir(DAILY_DIR):
        return 0, []
    complete_days = []
    incomplete_days = []
    for folder in sorted(os.listdir(DAILY_DIR)):
        folder_path = os.path.join(DAILY_DIR, folder)
        if not os.path.isdir(folder_path):
            continue

        # 메타데이터 확인 (파이프라인 수집 증명)
        meta_path = os.path.join(folder_path, "_collection_meta.json")
        has_meta = os.path.exists(meta_path)

        oy = [f for f in glob.glob(os.path.join(folder_path, "oliveyoung_*.json"))
              if "sample" not in os.path.basename(f)]
        nv = [f for f in glob.glob(os.path.join(folder_path, "naver_*.json"))
              if "sample" not in os.path.basename(f)]
        yt = [f for f in glob.glob(os.path.join(folder_path, "youtube_*.json"))
              if "sample" not in os.path.basename(f)]

        if oy and nv and yt and has_meta:
            complete_days.append(folder)
        elif oy:
            missing = []
            if not nv:
                missing.append("naver")
            if not yt:
                missing.append("youtube")
            if not has_meta:
                missing.append("meta(미검증)")
            incomplete_days.append((folder, missing))
    return len(complete_days), incomplete_days


def cleanup_incomplete_daily(today_str):
    """오늘 이전 날짜 중 불완전한(OY+NV+YT 3종 미달) daily 폴더 삭제."""
    if not os.path.isdir(DAILY_DIR):
        return
    today_folder = datetime.now().strftime("%Y-%m-%d")
    for folder in sorted(os.listdir(DAILY_DIR)):
        if folder >= today_folder:
            continue  # 오늘 이후는 건드리지 않음
        folder_path = os.path.join(DAILY_DIR, folder)
        if not os.path.isdir(folder_path):
            continue
        oy = glob.glob(os.path.join(folder_path, "oliveyoung_*.json"))
        nv = glob.glob(os.path.join(folder_path, "naver_*.json"))
        yt = glob.glob(os.path.join(folder_path, "youtube_*.json"))
        meta = os.path.exists(os.path.join(folder_path, "_collection_meta.json"))
        if not (oy and nv and yt and meta):
            safe_print(f"  [정리] 불완전 daily/{folder} 삭제")
            shutil.rmtree(folder_path)


def cleanup_stale_state_files(today_str):
    """이전 날짜의 좀비 상태 파일 정리."""
    for name in ["_pipeline_state.json", "_verification_result.json"]:
        path = os.path.join(DATA_DIR, name)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            file_date = data.get("today_str") or data.get("verified_date") or ""
            if file_date and file_date != today_str:
                safe_print(f"  [정리] 이전 날짜({file_date}) {name} 삭제")
                os.remove(path)
        except (json.JSONDecodeError, KeyError):
            safe_print(f"  [정리] 손상된 {name} 삭제")
            os.remove(path)
    # 이전 날짜 키워드 파일도 정리
    for f in glob.glob(os.path.join(DATA_DIR, "_keywords_*.json")):
        if today_str not in os.path.basename(f):
            safe_print(f"  [정리] 이전 키워드 파일 삭제: {os.path.basename(f)}")
            os.remove(f)
    # 이전 날짜 글로벌몰 영문명 파일 정리
    for f in glob.glob(os.path.join(DATA_DIR, "_global_names_*.json")):
        if today_str not in os.path.basename(f):
            safe_print(f"  [정리] 이전 글로벌몰 파일 삭제: {os.path.basename(f)}")
            os.remove(f)
    # 이전 날짜 DOM 추출 파일 정리
    for f in glob.glob(os.path.join(DATA_DIR, "_dom_extract_*.json")):
        if today_str not in os.path.basename(f):
            safe_print(f"  [정리] 이전 DOM 추출 파일 삭제: {os.path.basename(f)}")
            os.remove(f)
    # 이전 날짜 영문명 확인 파일 정리
    en_confirm = os.path.join(DATA_DIR, "_en_needs_confirm.json")
    if os.path.exists(en_confirm):
        os.remove(en_confirm)
    # data/ 루트의 이전 날짜별 데이터 파일 정리 (daily/로 복사 완료된 것만)
    for prefix in ["oliveyoung_", "naver_", "youtube_"]:
        for f in glob.glob(os.path.join(DATA_DIR, f"{prefix}2*.json")):
            basename = os.path.basename(f)
            # 오늘자 파일은 유지 (아직 작업 중일 수 있음)
            if today_str in basename:
                continue
            # sample 파일 제외
            if "sample" in basename:
                continue
            # daily/에 복사본이 있는 경우만 삭제
            # 파일명에서 날짜 추출: prefix_YYYYMMDD.json
            import re as _re
            m = _re.search(r'(\d{8})', basename)
            if m:
                file_date = m.group(1)
                daily_date = f"{file_date[:4]}-{file_date[4:6]}-{file_date[6:8]}"
                daily_copy = os.path.join(DATA_DIR, "daily", daily_date, basename)
                if os.path.exists(daily_copy):
                    safe_print(f"  [정리] 루트 데이터 파일 삭제 (daily/에 보존): {basename}")
                    os.remove(f)


def _find_previous_daily_path(source_prefix):
    """data/daily/에서 가장 최근 날짜의 해당 소스 파일 경로 반환."""
    if not os.path.isdir(DAILY_DIR):
        return None
    folders = sorted(
        [f for f in os.listdir(DAILY_DIR) if os.path.isdir(os.path.join(DAILY_DIR, f))],
        reverse=True
    )
    for folder in folders:
        folder_path = os.path.join(DAILY_DIR, folder)
        files = glob.glob(os.path.join(folder_path, f"{source_prefix}_*.json"))
        if files:
            return files[0]
    return None


# ================================================================
#  Orchestrator (메인)
# ================================================================

def run_full_pipeline():
    """전체 파이프라인 실행: Step 1 -> 2 -> 3 -> 4 -> 5."""
    # 파이프라인 시작 시 날짜 고정 (자정 넘김 방지)
    today_str = datetime.now().strftime("%Y%m%d")

    safe_print("=" * 50)
    safe_print("  K-Beauty Trend Tracker - Daily Pipeline")
    safe_print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')} (date locked: {today_str})")
    safe_print("=" * 50)

    # 이전 날짜 좀비 파일 정리
    cleanup_stale_state_files(today_str)
    cleanup_incomplete_daily(today_str)

    # Step 1: 캡처
    if not run_step1(today_str):
        return False

    # Step 2: 올리브영 검증
    if not run_step2(today_str):
        return False

    # Step 3: API 수집
    if not run_step3(today_str):
        return False

    # Step 4: API 검증
    if not run_step4(today_str):
        return False

    # Step 5: 저장 + 갱신
    step5_result = run_step5(today_str)
    if step5_result == "WAITING_APPROVAL":
        safe_print("\n[PAUSE] 최종 확인 대기 중 — orchestrator가 처리합니다.")
        return "WAITING_APPROVAL"
    if not step5_result:
        return False

    safe_print(f"\n{'=' * 50}")
    safe_print("  파이프라인 완료!")
    safe_print(f"{'=' * 50}")
    return True


def main():
    if len(sys.argv) < 2:
        # 인자 없으면 전체 파이프라인
        ok = run_full_pipeline()
        sys.exit(0 if ok else 1)

    mode = sys.argv[1].lower()
    # 개별 step 실행 시에도 날짜 지정 가능 (예: step2 20260402)
    today_str = sys.argv[2] if len(sys.argv) > 2 else None

    if mode == "step1":
        ok = run_step1(today_str)
    elif mode == "step2":
        ok = run_step2(today_str)
    elif mode == "step3":
        ok = run_step3(today_str)
    elif mode == "step4":
        ok = run_step4(today_str)
    elif mode == "step5":
        ok = run_step5(today_str)
    elif mode == "all":
        ok = run_full_pipeline()
    elif mode == "status":
        safe_print(f"daily 데이터: {count_daily_data()}/{PERIOD_DAYS}일")
        ok = True
    else:
        safe_print(f"알 수 없는 모드: {mode}")
        safe_print("사용법: python run_daily_collect.py [step1|step2|step3|step4|step5|all|status]")
        ok = False

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
