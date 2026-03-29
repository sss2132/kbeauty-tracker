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

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime


def safe_print(text):
    """cp949 등 터미널 인코딩에서 깨지는 문자를 ? 로 대체하여 출력."""
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
PERIOD_DAYS = 3
CLAUDE_EXE = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
AGENTS_DIR = os.path.join(BASE_DIR, "agents")


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
        "passed": {"type": "boolean"},
        "issues": {
            "type": "array",
            "items": {"type": "string"}
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
                    "youtube_keyword": {"type": "string"},
                    "english_name": {"type": "string"}
                },
                "required": ["product_code", "naver_keyword", "youtube_keyword", "english_name"]
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


def run_keyword_agent(oy_path, timeout=600):
    """claude -p로 최적 검색 키워드 생성. 실패 시 None 반환."""
    today_str = datetime.now().strftime("%Y%m%d")
    gn_path = os.path.join(DATA_DIR, f"_global_names_{today_str}.json")
    if not os.path.exists(gn_path):
        safe_print("[KEYWORD] FAIL - 글로벌몰 영문명 파일 없음. Step 3 Phase 0(fetch_global_names) 먼저 실행 필요.")
        return None
    global_names_ref = os.path.abspath(gn_path)

    rules = load_agent_rules("step3_keyword.md")

    prompt = f"""{rules}

---

## 작업
올리브영 제품 데이터를 읽고, 각 제품의 최적 검색 키워드를 생성해.

파일: {os.path.abspath(oy_path)}

## 글로벌몰 영문명 참조 파일
{global_names_ref}
- products 객체에서 product_code로 검색, global_name 필드가 공식 영문명
- 공식 영문명에서 용량/기획/세트 정보를 제거하고 핵심 제품명만 사용
- 파일에 없는 제품은 한국어 제품명을 영어로 번역

화장품인 제품만(최대 50개) product_code, naver_keyword, youtube_keyword, english_name을 생성해.
비화장품은 keywords 배열에서 완전히 제외해."""

    cmd = [
        CLAUDE_EXE, "-p",
        "--output-format", "json",
        "--json-schema", KEYWORD_SCHEMA,
        "--allowed-tools", "Read,WebFetch",
        "--no-session-persistence",
        prompt,
    ]

    safe_print("[KEYWORD] 키워드 생성 Agent 호출 중 (글로벌 몰 영문명 대조 포함)...")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", cwd=PROJECT_ROOT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        safe_print(f"[KEYWORD] Agent 실패: {e}")
        return None

    if result.returncode != 0:
        safe_print("[KEYWORD] Agent 실행 실패")
        return None

    raw = result.stdout.strip()
    try:
        outer = json.loads(raw)
        if "structured_output" in outer and isinstance(outer["structured_output"], dict):
            return outer["structured_output"]
        elif "result" in outer and isinstance(outer["result"], str):
            return json.loads(outer["result"])
        elif "keywords" in outer:
            return outer
    except (json.JSONDecodeError, TypeError):
        pass

    safe_print("[KEYWORD] Agent 응답 파싱 실패 - 기본 키워드 사용")
    return None


def verify_english_names(oy_path, keywords_path, timeout=600):
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
        "--output-format", "json",
        "--json-schema", EN_VERIFY_SCHEMA,
        "--allowed-tools", "Read,WebFetch,WebSearch",
        "--no-session-persistence",
        prompt,
    ]

    safe_print("[EN_VERIFY] 영문명 검증 Agent 호출 중...")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
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

    # needs_confirm 목록을 파일로 저장 (orchestrator가 텔레그램으로 사용자에게 확인 요청)
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
        safe_print(f"[EN_VERIFY] 확인 필요 {len(confirm_items)}건 → _en_needs_confirm.json (텔레그램으로 사용자 확인 요청 필요)")

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


def run_verification_agent(prompt, timeout=1800, allowed_tools="Read,Glob"):
    """
    Claude Code CLI를 별도 프로세스로 띄워 검증 실행.

    새 프로세스 = 이전 수집/추출 대화 기억 없음 = unbiased 검증.
    --json-schema로 구조화 응답, --allowed-tools로 허용 도구 제한.

    Returns:
        dict: {"passed": bool, "issues": [...], "new_launches": [...]}
              파싱 실패 시 {"passed": False, "issues": ["파싱 실패: ..."]}
    """
    cmd = [
        CLAUDE_EXE,
        "-p",
        "--output-format", "json",
        "--json-schema", VERIFICATION_SCHEMA,
        "--allowed-tools", allowed_tools,
        "--no-session-persistence",
        prompt,
    ]

    safe_print(f"\n[VERIFY] 검증 Agent 호출 중...")

    try:
        result = subprocess.run(
            cmd,
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
    if result["passed"]:
        safe_print(f"[VERIFY] {step_name} 검증 통과")
        if result["issues"]:
            safe_print(f"  (참고 사항 {len(result['issues'])}건)")
            for issue in result["issues"]:
                safe_print(f"    - {issue}")
        return True

    safe_print(f"[VERIFY] {step_name} 검증 실패 - {len(result['issues'])}건 발견:")
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

def run_step1():
    """올리브영 랭킹 페이지 캡처 + DOM 추출 + 데이터 보강 Agent."""
    today_str = datetime.now().strftime("%Y%m%d")
    safe_print(f"\n{'=' * 50}")
    safe_print(f"  Step 1: 올리브영 캡처 + 추출")
    safe_print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    safe_print(f"{'=' * 50}\n")

    # Phase 1: 캡처 실행
    capture_script = os.path.join(SCRIPTS_DIR, "capture_oliveyoung.py")
    if not os.path.exists(capture_script):
        safe_print("[CAPTURE] SKIP - capture_oliveyoung.py 없음")
    else:
        try:
            result = subprocess.run(
                [sys.executable, capture_script],
                capture_output=True, text=True, timeout=300,
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

    # Phase 2: DOM 추출 실행
    extract_script = os.path.join(SCRIPTS_DIR, "extract_dom.py")
    if not os.path.exists(extract_script):
        safe_print("[EXTRACT] SKIP - extract_dom.py 없음")
    else:
        try:
            result = subprocess.run(
                [sys.executable, extract_script],
                capture_output=True, text=True, timeout=120,
                encoding="utf-8", errors="replace"
            )
            if result.returncode == 0:
                safe_print("[EXTRACT] OK")
            else:
                safe_print(f"[EXTRACT] FAIL - {result.stderr[:300]}")
                return False
        except subprocess.TimeoutExpired:
            safe_print("[EXTRACT] FAIL - 타임아웃 (120초)")
            return False

    # Phase 3: 데이터 보강 Agent
    raw_path = os.path.join(DATA_DIR, f"_dom_extract_{today_str}.json")
    oy_path = os.path.join(DATA_DIR, f"oliveyoung_{today_str}.json")
    screenshots = sorted(
        glob.glob(os.path.join(SCREENSHOT_DIR, f"oliveyoung_{today_str}_*.png"))
    )
    ss_paths = "\n".join(screenshots) if screenshots else "(스크린샷 없음)"
    ss_count = len(screenshots)
    safe_print(f"\n스크린샷 {ss_count}장, raw 데이터: {os.path.basename(raw_path)}")

    if not os.path.exists(raw_path):
        safe_print(f"[ERROR] {raw_path} 없음. DOM 추출 실패.")
        return False

    rules = load_agent_rules("step1_extract.md")
    prompt = f"""{rules}

---

## 작업 대상
- raw DOM 추출 결과: {os.path.abspath(raw_path)}
- 스크린샷 ({ss_count}장):
{ss_paths}

## 출력
- 보강된 JSON을 다음 경로에 저장: {os.path.abspath(oy_path)}
- 50개 제품 배열 (rank 1~50), 위 규칙의 필드 전부 포함
- raw 데이터와 스크린샷을 대조하여 정확성 확보
- 문제가 있으면 파일은 생성하되, 콘솔에 issues를 출력"""

    safe_print(f"\n[ENRICH] 데이터 보강 Agent 호출 중...")

    cmd = [
        CLAUDE_EXE, "-p",
        "--allowed-tools", "Read,Write,Glob",
        "--no-session-persistence",
        prompt,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=600,
            encoding="utf-8", errors="replace",
            cwd=PROJECT_ROOT,
        )
    except subprocess.TimeoutExpired:
        safe_print("[ENRICH] FAIL - 타임아웃 (600초)")
        return False

    if result.returncode != 0:
        safe_print(f"[ENRICH] FAIL - {(result.stderr or '')[:500]}")
        return False

    if os.path.exists(oy_path):
        safe_print(f"[ENRICH] OK - {os.path.basename(oy_path)} 생성됨")
        # raw 파일은 중간 산출물이므로 유지 (Step 5에서 cleanup)
        return True
    else:
        safe_print(f"[ENRICH] FAIL - {os.path.basename(oy_path)} 미생성")
        if result.stdout:
            safe_print(f"  Agent 출력: {result.stdout[:500]}")
        return False


# ================================================================
#  Step 2: 올리브영 검증 (Verification Agent)
# ================================================================

def build_oy_verification_prompt(today_str):
    """올리브영 데이터 검증 프롬프트 생성."""
    oy_path = os.path.join(DATA_DIR, f"oliveyoung_{today_str}.json")
    if not os.path.exists(oy_path):
        return None

    screenshots = sorted(
        glob.glob(os.path.join(SCREENSHOT_DIR, f"oliveyoung_{today_str}_*.png"))
    )
    ss_count = len(screenshots)

    # 스크린샷 경로를 절대경로로
    ss_paths = "\n".join(screenshots) if screenshots else "(스크린샷 없음)"

    rules = load_agent_rules("step2_oy_verify.md")

    return f"""{rules}

---

## 역할
너는 K-Beauty Trend Tracker의 데이터 검증자야.
다른 agent가 올리브영 베스트 랭킹 페이지에서 추출한 데이터를 처음 보는 상태에서 검증해.

## 검증 대상
스크린샷 파일 ({ss_count}장):
{ss_paths}

JSON 파일:
{os.path.abspath(oy_path)}

## 검증 항목
1. 스크린샷의 각 제품 순위 번호가 JSON rank와 일치하는지 (1장당 3-4개 샘플링)
2. 제품명 변조 여부 (가장 중요): JSON name이 스크린샷 실제 제품명과 일치하는지 엄격 대조
3. 오특 제품이 is_oteuk: true로 올바르게 태그되었는지
4. 스크린샷에 있는데 JSON에 빠진 제품이 없는지
5. search_keyword 품질: 위 규칙의 기준에 따라 제품별 대조
6. 번들/골라담기: 위 규칙의 확정 테이블과 대조, 새 번들은 보고
7. 중복 제품: search_keyword 동일한 쌍 모두 보고
8. 비화장품: 위 규칙 기준으로 감지하여 보고
9. 기획상품 유형: 1+1, 더블, 리필, 2입 등 기획 유형 식별하여 보고

## 출력 형식
반드시 아래 JSON 형식으로만 응답해:
- 모두 정상이면: {{"passed": true, "issues": []}}
- 문제 있으면: {{"passed": false, "issues": ["문제1 설명", "문제2 설명", ...]}}

issues에는 구체적으로 어떤 rank의 어떤 제품에 무슨 문제가 있는지 적어.
사소한 표기 차이(띄어쓰기, 약어)는 무시하고, 실질적 오류만 보고해."""


def run_step2(today_str=None):
    """올리브영 데이터 검증 - Verification Agent 호출."""
    if today_str is None:
        today_str = datetime.now().strftime("%Y%m%d")

    safe_print(f"\n{'=' * 50}")
    safe_print(f"  Step 2: 올리브영 데이터 검증")
    safe_print(f"{'=' * 50}")

    oy_path = os.path.join(DATA_DIR, f"oliveyoung_{today_str}.json")
    if not os.path.exists(oy_path):
        safe_print(f"[ERROR] {oy_path} 없음. Step 1 + 추출 먼저 실행 필요.")
        return False

    # 기본 통계
    with open(oy_path, "r", encoding="utf-8") as f:
        products = json.load(f)
    total = len(products)
    promo = sum(1 for p in products if p.get("is_oteuk"))
    safe_print(f"  제품 {total}개, 오특 {promo}개")

    prompt = build_oy_verification_prompt(today_str)
    if not prompt:
        safe_print("[ERROR] 검증 프롬프트 생성 실패")
        return False

    result = run_verification_agent(prompt)
    return handle_verification_result(result, "올리브영")


# ================================================================
#  Step 3: 네이버 + 유튜브 API 수집
# ================================================================

def run_step3():
    """네이버/유튜브 API 수집 — Claude가 키워드 결정."""
    today_str = datetime.now().strftime("%Y%m%d")

    safe_print(f"\n{'=' * 50}")
    safe_print(f"  Step 3: API 수집 (키워드 생성 + 네이버 + 유튜브)")
    safe_print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    safe_print(f"{'=' * 50}\n")

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

    # Phase 0: 올리브영 글로벌 몰에서 공식 영문명 수집 (필수 - 건너뛰기 금지)
    global_script = os.path.join(SCRIPTS_DIR, "fetch_global_names.py")
    global_names_path = os.path.join(DATA_DIR, f"_global_names_{today_str}.json")
    global_ok = False
    max_global_retries = 3
    for attempt in range(1, max_global_retries + 1):
        if not os.path.exists(global_script):
            safe_print("[GLOBAL ERROR] fetch_global_names.py 스크립트 없음 - Step 3 중단")
            return False
        try:
            safe_print(f"[GLOBAL] 영문명 수집 시도 {attempt}/{max_global_retries}")
            r = subprocess.run(
                [sys.executable, global_script],
                capture_output=True, text=True, timeout=300,
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
        safe_print("[GLOBAL ERROR] 글로벌몰 영문명 수집 실패 (3회 재시도 후). Step 3 중단. 텔레그램으로 알림 필요.")
        return False

    # Phase 1: Claude가 최적 키워드 생성
    keywords_path = os.path.join(DATA_DIR, f"_keywords_{today_str}.json")
    kw_result = run_keyword_agent(oy_path)
    if kw_result and "keywords" in kw_result:
        # 50개 하드컷 (에이전트가 초과 반환해도 상위 50개만 저장)
        kw_list = kw_result["keywords"][:50]
        with open(keywords_path, "w", encoding="utf-8") as f:
            json.dump(kw_list, f, ensure_ascii=False, indent=2)
        safe_print(f"[KEYWORD] {len(kw_list)}개 키워드 생성 완료")
    else:
        safe_print("[KEYWORD] 키워드 생성 실패 - 기본 키워드로 진행")

    # Phase 1.5: 영문명 검증 (한글 풀네임과 대조)
    if os.path.exists(keywords_path):
        verify_english_names(oy_path, keywords_path)

    results = {}

    # Phase 2: 네이버 API
    nv_script = os.path.join(SCRIPTS_DIR, "naver_trend.py")
    if os.path.exists(nv_script):
        try:
            r = subprocess.run(
                [sys.executable, nv_script],
                capture_output=True, text=True, timeout=180,
                encoding="utf-8", errors="replace"
            )
            if r.returncode == 0:
                safe_print("[NAVER] OK")
                nv_files = sorted(glob.glob(os.path.join(DATA_DIR, "naver_*.json")))
                nv_files = [f for f in nv_files
                            if "sample" not in os.path.basename(f)
                            and "rank" not in os.path.basename(f)]
                results["naver"] = nv_files[-1] if nv_files else None
            else:
                safe_print(f"[NAVER] FAIL - {r.stderr[:200]}")
        except Exception as e:
            safe_print(f"[NAVER] FAIL - {e}")
    else:
        safe_print("[NAVER] SKIP - naver_trend.py 없음")

    # Phase 3: 유튜브 API
    yt_script = os.path.join(SCRIPTS_DIR, "youtube_trend.py")
    if os.path.exists(yt_script):
        try:
            r = subprocess.run(
                [sys.executable, yt_script],
                capture_output=True, text=True, timeout=300,
                encoding="utf-8", errors="replace"
            )
            if r.returncode == 0:
                safe_print("[YOUTUBE] OK")
                # API 에러 파일 확인
                api_err_path = os.path.join(DATA_DIR, "_youtube_api_errors.txt")
                if os.path.exists(api_err_path):
                    with open(api_err_path, "r", encoding="utf-8") as ef:
                        err_keywords = ef.read().strip().split("\n")
                    safe_print(f"[YOUTUBE] API 에러 {len(err_keywords)}건 발생!")
                    safe_print(f"  에러 키워드: {', '.join(err_keywords[:10])}")
                    os.remove(api_err_path)
                yt_files = sorted(glob.glob(os.path.join(DATA_DIR, "youtube_*.json")))
                yt_files = [f for f in yt_files
                            if "sample" not in os.path.basename(f)]
                results["youtube"] = yt_files[-1] if yt_files else None
            else:
                safe_print(f"[YOUTUBE] FAIL - {r.stderr[:200]}")
        except Exception as e:
            safe_print(f"[YOUTUBE] FAIL - {e}")
    else:
        safe_print("[YOUTUBE] SKIP - youtube_trend.py 없음")

    # 네이버/유튜브 0 비율 보고
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

    # Phase 4: 검색량 0 키워드 재시도
    retry_script = os.path.join(SCRIPTS_DIR, "keyword_retry.py")
    if os.path.exists(retry_script):
        try:
            r = subprocess.run(
                [sys.executable, retry_script],
                capture_output=True, text=True, timeout=300,
                encoding="utf-8", errors="replace"
            )
            if r.returncode == 0:
                safe_print("[RETRY] 키워드 재시도 완료")
                for line in r.stdout.split("\n"):
                    if line.strip() and ("성공" in line or "개선" in line or "변경" in line):
                        safe_print(f"  {line.strip()}")
            else:
                safe_print(f"[RETRY] 실패 (무시하고 진행): {r.stderr[:200]}")
        except Exception as e:
            safe_print(f"[RETRY] 에러 (무시하고 진행): {e}")

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

def build_api_verification_prompt(oy_path, nv_path, yt_path):
    """API 데이터 검증 프롬프트 생성."""
    rules = load_agent_rules("step4_api_verify.md")

    parts = [f"""{rules}

---

## 역할
너는 K-Beauty Trend Tracker의 데이터 검증자야.
수집 과정을 전혀 모르는 상태에서, 결과 파일만 보고 검증해.

## 검증 대상 파일
올리브영: {os.path.abspath(oy_path)}"""]

    if nv_path and os.path.exists(nv_path):
        parts.append(f"네이버: {os.path.abspath(nv_path)}")
    else:
        parts.append("네이버: (수집 실패 또는 없음)")

    if yt_path and os.path.exists(yt_path):
        parts.append(f"유튜브: {os.path.abspath(yt_path)}")
    else:
        parts.append("유튜브: (수집 실패 또는 없음)")

    # 직전 날짜 데이터 경로 (변동 비교용)
    prev_nv = _find_previous_daily_path("naver")
    if prev_nv:
        parts.append(f"\n직전 네이버 데이터 (변동 비교용): {prev_nv}")

    parts.append(f"""
## 검증 항목
위 규칙 파일의 기준에 따라 네이버/유튜브 데이터를 검증하고, 신제품을 감지해.

## 출력 형식
반드시 아래 JSON 형식으로만 응답해:
- 모두 정상이면: {{"passed": true, "issues": [], "new_launches": ["코드1", ...]}}
- 문제 있으면: {{"passed": false, "issues": ["문제1", "문제2", ...], "new_launches": []}}

new_launches는 검증 통과 여부와 무관하게 항상 포함.
수집 실패(파일 없음)는 issues에 기록하되, 네이버/유튜브 중 하나만 실패해도 passed: true 가능.
둘 다 실패했으면 passed: false.""")

    return "\n".join(parts)


def run_step4():
    """API 데이터 검증 - 독립 Verification Agent 호출 + 결과 저장.

    검증 Agent는 별도 프로세스(claude -p)로 실행되며:
    - Read, Glob 도구만 사용 가능 (Bash, Write 불가 → 데이터 수정 불가)
    - --no-session-persistence → 수집 과정 기억 없음
    - 결과는 _verification_result.json에 파일 해시와 함께 저장
    - Step 5가 이 파일을 하드체크 → 검증 없이 진행 불가
    """
    safe_print(f"\n{'=' * 50}")
    safe_print(f"  Step 4: API 데이터 검증 (독립 검증 Agent)")
    safe_print(f"{'=' * 50}")

    # 파이프라인 상태 로드
    state_path = os.path.join(DATA_DIR, "_pipeline_state.json")
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    else:
        today_str = datetime.now().strftime("%Y%m%d")
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
    result = run_verification_agent(prompt, allowed_tools="Read,Glob,WebFetch,WebSearch")

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
        "verified_date": datetime.now().strftime("%Y%m%d"),
        "file_hashes": file_hashes,
        "verified_by": "claude -p verification agent (independent process)",
    }

    vr_path = os.path.join(DATA_DIR, "_verification_result.json")
    with open(vr_path, "w", encoding="utf-8") as f:
        json.dump(verification_data, f, ensure_ascii=False, indent=2)
    safe_print(f"[VERIFY] 검증 결과 저장: _verification_result.json")

    return handle_verification_result(result, "API")


# ================================================================
#  Step 5: daily 저장 + 3일치 확인 + 갱신
# ================================================================

def run_step5():
    """daily 폴더 저장 + 3일치 확인 + score 계산 + 사이트 갱신."""
    today = datetime.now()
    today_str = today.strftime("%Y%m%d")
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
                "번들/골라담기 제품 키워드가 CLAUDE.md 확정 테이블과 일치하는지",
                "글로벌몰 영문명(english_name) 정상 수집되었는지",
                "전일 대비 급격한 순위 변동 (데이터 오류 가능성 체크)",
            ],
        }
        with open(final_check_path, "w", encoding="utf-8") as f:
            json.dump(final_check, f, ensure_ascii=False, indent=2)
        safe_print(f"\n[FINAL CHECK] daily 저장 전 최종 확인 필요")
        safe_print("  orchestrator가 스크린샷 대조 후 텔레그램으로 승인 요청합니다.")
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

    # 영문명 영구 저장 (키워드 파일 삭제 전에 추출)
    kw_tmp_path = os.path.join(DATA_DIR, f"_keywords_{today_str}.json")
    if os.path.exists(kw_tmp_path):
        try:
            with open(kw_tmp_path, "r", encoding="utf-8") as f:
                kw_data = json.load(f)
            if isinstance(kw_data, dict) and "keywords" in kw_data:
                kw_data = kw_data["keywords"]
            # daily 폴더에 영문명 저장
            en_names_daily = {}
            for kw in kw_data:
                code = kw.get("product_code", "")
                en = kw.get("english_name", "")
                if code and en:
                    en_names_daily[code] = en
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
    safe_print("=" * 50)
    safe_print("  K-Beauty Trend Tracker - Daily Pipeline")
    safe_print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    safe_print("=" * 50)

    # 이전 날짜 좀비 파일 정리
    today_str = datetime.now().strftime("%Y%m%d")
    cleanup_stale_state_files(today_str)
    cleanup_incomplete_daily(today_str)

    # Step 1: 캡처
    if not run_step1():
        return False

    # Step 1이 캡처 + 추출 + 보강까지 완료함
    today_str = datetime.now().strftime("%Y%m%d")

    # Step 2: 올리브영 검증
    if not run_step2(today_str):
        return False

    # Step 3: API 수집
    if not run_step3():
        return False

    # Step 4: API 검증
    if not run_step4():
        return False

    # Step 5: 저장 + 갱신
    step5_result = run_step5()
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

    if mode == "step1":
        ok = run_step1()
    elif mode == "step2":
        today_str = sys.argv[2] if len(sys.argv) > 2 else None
        ok = run_step2(today_str)
    elif mode == "step3":
        ok = run_step3()
    elif mode == "step4":
        ok = run_step4()
    elif mode == "step5":
        ok = run_step5()
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
