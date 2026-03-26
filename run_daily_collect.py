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
    if os.path.exists(gn_path):
        global_names_ref = os.path.abspath(gn_path)
    else:
        global_names_ref = "(파일 없음 — 한국어 제품명을 영어로 번역해서 사용)"

    prompt = f"""너는 K-Beauty 제품 검색 키워드 전문가야.
올리브영 제품 데이터를 읽고, 각 제품의 최적 검색 키워드를 생성해.

파일: {os.path.abspath(oy_path)}

## 핵심 원칙: 제품명 변조 금지
- 원본 name 필드에 있는 제품 핵심 이름을 절대 바꾸지 마
- 키워드 생성은 "앞뒤 프로모션/용량/패키징 텍스트를 제거"하는 것이지, "제품명을 요약하거나 재작성"하는 게 아님
- 제거 대상: 앞쪽 [대괄호 프로모션], 용량(ml, g, 매), 수량(+1, 더블, 2입), 기획/한정/리필, 증정 정보
- 유지 대상: 브랜드명 + 제품 라인명 + 제품 고유명 (이것들은 원본 그대로 유지)
- 잘못된 예: "메디힐 마데카소사이드 흔적 리페어 세럼" → "메디힐 마데카소사이드 세럼" (X, "흔적 리페어" 삭제됨)
- 잘못된 예: "메디힐 더마 패드" → "메디힐 토닝패드" (X, 제품명 자체를 바꿈)

## 네이버 키워드 규칙 (naver_keyword)
- 한국 소비자가 네이버에서 실제로 검색할 법한 키워드
- 브랜드명(한국어) + 제품 라인명 (2~3단어). 너무 구체적이면 네이버 API에서 검색량 0이 됨
- 같은 라인의 다른 패키징(용량, 세트, 기획)은 같은 키워드 공유 OK
- 예: "메디힐 에센셜 마스크팩 10+1/10매 기획 7종 골라담기" → "메디힐 마스크팩"
- 예: "토리든 다이브인 저분자 히알루론산 세럼 50ml 한정 리필 기획" → "토리든 다이브인 세럼"
- 예: "아누아 피디알엔 히알루론산 캡슐 100 세럼 30ml 더블 기획" → "아누아 세럼"
- 예: "바이오힐보 프로바이오덤 콜라겐 에센스 선크림 50ml+50ml" → "바이오힐보 선크림"
- 예: "클리오 킬커버 파운웨어 쿠션 기획" → "클리오 킬커버 쿠션"

## 유튜브 키워드 규칙 (youtube_keyword)
- 한국어 키워드로 검색 (한국 트렌드 기준이므로 한국어 영상을 정확히 잡아야 함)
- 네이버 키워드보다 조금 더 구체적으로: 브랜드명 + 제품 라인명 + 제품 타입
- 예: "달바 워터풀 톤업 선크림 핑크", "메디힐 마데카소사이드 세럼", "토리든 다이브인 세럼"
- 번들/골라담기 제품은 CLAUDE.md의 "확정된 번들 제품 키워드" 참조 (한글 키워드도 동일 원칙: 공통 상위 키워드 사용)

## 영문명 규칙 (english_name)
- 올리브영 글로벌 몰 공식 영문명 파일 반드시 참조: {global_names_ref}
  - 파일의 products 객체에서 product_code로 검색, global_name 필드가 공식 영문명
  - 공식 영문명에서 용량/기획/세트 정보를 제거하고 핵심 제품명만 사용
  - 파일에 없는 제품은 한국어 제품명을 영어로 번역
- 이 영문명은 YouTube 검색이 아닌 웹사이트 게시용으로 사용됨
- 예: "메디힐 마데카소사이드 세럼" → english_name: "MEDIHEAL Madecassoside Blemish Repair Serum"
- 예: "클리오 킬커버 파운웨어 쿠션" → english_name: "CLIO Kill Cover Founwear Cushion"

## 비화장품 제외 규칙
- 건강기능식품(비타민, 단백질쉐이크, 콜라겐 영양제 등), 과자/스낵(베이글칩 등), 의료기기는 제외
- 콜라겐 "패치"나 콜라겐 "세럼"은 화장품이므로 포함
- 판단 기준: 피부에 바르거나 붙이는 제품 = 화장품, 먹는 제품 = 비화장품

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

    prompt = f"""너는 K-Beauty 제품의 영문명 검증 전문가야.
아래 목록에서 각 제품의 한글 풀네임(KO)과 영문명(EN)이 같은 제품을 가리키는지 확인해.

## 검증 기준
1. **제품 타입 일치**: 세럼↔Serum, 크림↔Cream, 쿠션↔Cushion, 패드↔Pad, 마스크↔Mask, 틴트↔Tint 등
2. **제품 라인명 일치**: 한글 제품명의 핵심 키워드가 영문명에 반영되어야 함
   - 예: "누더 쿠션" → "Nuder Cushion" (O), "Radiant Cushion" (X - 다른 제품)
   - 예: "핑크 톤업 선크림" → "Pink Tone-Up Sun Cream" (O), "Waterfull Tone-Up Sun Cream" (X - 다른 라인)
   - 예: "시트 마스크" → "Mask Sheet" (O), "Dive In Low Molecular Hyaluronic Acid Mask Sheet" (X - 너무 구체적, 다른 제품 이름)
3. **브랜드 일치**: 영문명의 브랜드가 한글 브랜드와 같아야 함
4. **한글이 영문명에 그대로 들어가 있으면 mismatch**: 영문명 필드에 한글 문자가 포함되어 있으면 번역이 안 된 것

## 판단 원칙
- 용량(ml, g, 매)이나 프로모션(기획, 더블, 2입) 텍스트는 무시
- 같은 브랜드의 다른 제품 라인이 영문명에 들어가 있으면 mismatch
- 영문명이 한글 제품의 핵심 특성(라인명, 제품타입)을 정확히 반영하면 ok
- 영문명에 한글명에 없는 단어가 추가되어 있으면 "needs_confirm" (예: 한글 "퍼스트 스프레이 세럼"인데 영문 "White Truffle First Spray Serum"처럼 White Truffle이 추가된 경우)
- mismatch인 경우 corrected_name에 올바른 영문명을 제시 (브랜드 영문명 + 제품명 영역)
- needs_confirm인 경우 corrected_name은 비우고, reason에 아래 내용을 모두 포함:
  1. 어떤 단어가 한글명에 없고 영문명에만 있는지
  2. 글로벌몰/공식몰에서 검색한 결과 (해당 단어가 공식 이름에 포함되는지)
  3. 올리브영 국내몰이 축약 표기한 건지, 아예 다른 제품인지 판단 근거
  예: "한글명 '퍼스트 스프레이 세럼'에 없는 'White Truffle'이 영문명에 포함. 글로벌몰(global.oliveyoung.com)에서 'd'Alba First Spray Serum' 검색 결과 공식 이름이 'd'Alba White Truffle First Spray Serum'으로 확인. 올리브영 국내몰이 축약 표기한 것으로 판단."

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
    """올리브영 랭킹 페이지 캡처 + 제품 추출 안내."""
    today_str = datetime.now().strftime("%Y%m%d")
    safe_print(f"\n{'=' * 50}")
    safe_print(f"  Step 1: 올리브영 캡처 + 추출")
    safe_print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    safe_print(f"{'=' * 50}\n")

    # 캡처 실행
    script = os.path.join(SCRIPTS_DIR, "capture_oliveyoung.py")
    if not os.path.exists(script):
        safe_print("[CAPTURE] SKIP - capture_oliveyoung.py 없음")
    else:
        try:
            result = subprocess.run(
                [sys.executable, script],
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

    screenshots = sorted(
        glob.glob(os.path.join(SCREENSHOT_DIR, f"oliveyoung_{today_str}_*.png"))
    )
    ss_count = len(screenshots)
    safe_print(f"\n스크린샷 {ss_count}장 저장됨")

    # 추출 안내
    safe_print(f"\n{'=' * 50}")
    safe_print("  다음: 제품 추출")
    safe_print(f"{'=' * 50}")
    safe_print("""
Claude Code가 스크린샷 또는 DOM에서 제품 추출합니다.
추출 결과: data/oliveyoung_{today}.json

=== search_keyword 규칙 ===
- 브랜드 영문명 + 제품 라인명만 (용량/기획/한정 제외)
- 같은 브랜드 다른 제품은 반드시 구분

=== 오특(오늘의 특가) 식별 ===
- 초록색 순위 숫자 있음 = 일반 제품
- "오늘의 특가" 빨간 배너, 순위 숫자 없음 = 오특 (is_oteuk: true)
- 오특 rank는 앞뒤 순위에서 유추

=== 번들/중복 제품 감지 (필수) ===
- "N종 골라담기", "N종 택1", "N종 중 택" 등이 포함된 제품은 번들 제품으로 표시
- 같은 제품이 다른 기획(예: 10매 vs 1매, 단품 vs 세트)으로 여러 순위에 등장하면 중복으로 표시
- search_keyword가 동일한 제품이 여러 개 있으면 반드시 확인 후 표시
- CLAUDE.md의 "번들/골라담기 제품 처리 규칙" 참조하여 확정된 키워드가 있으면 사용

추출 완료 후: python run_daily_collect.py step2
""".strip())

    return True


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

    return f"""너는 K-Beauty Trend Tracker의 데이터 검증자야.
다른 agent가 올리브영 베스트 랭킹 페이지에서 추출한 데이터를 처음 보는 상태에서 검증해.

## 프로젝트 배경
- 올리브영 베스트 랭킹 TOP 60 제품을 매일 수집
- 스크린샷 5장 (4열x3행 = 12제품/장, 총 60제품)
- "오특(오늘의 특가)": 랭킹 사이에 삽입되는 프로모션 슬롯
  - 일반 제품: 초록색 원 안에 순위 숫자(01, 02, ...)가 있음
  - 오특 제품: 순위 숫자 대신 "오늘의 특가" 빨간 배너가 있음
  - 오특도 JSON에 포함, is_oteuk: true로 표기

## 검증 대상
스크린샷 파일 ({ss_count}장):
{ss_paths}

JSON 파일:
{os.path.abspath(oy_path)}

## 검증 항목
1. 스크린샷의 각 제품 순위 번호가 JSON rank와 일치하는지 (전수 검사 불필요, 1장당 3-4개 샘플링)
2. 제품명이 정확한지 (유사 제품 혼동 없는지: 선스틱 vs 선세럼, 크림 vs 로션)
3. 오특 제품이 is_oteuk: true로 올바르게 태그되었는지
   - 스크린샷에서 초록색 순위 숫자가 없는 슬롯 = 오특
   - 반대로 is_oteuk: true인데 순위 숫자가 보이면 오류
4. 스크린샷에 있는데 JSON에 빠진 제품이 없는지
5. search_keyword 품질 (제품별로 하나하나 대조):
   - 원칙: search_keyword에는 "브랜드 + 제품 고유 이름 + 제품 타입"만 남아야 함
   - 제품의 정체성이 아닌 것은 모두 제거되어야 함: 수량, 컬러 수, 구매 옵션, 패키징 정보 등
   - 각 제품의 원본 name과 search_keyword를 대조해서, name에서 무엇이 제거되었고 무엇이 남았는지 판단
   - 남아있으면 안 되는 것이 남아있으면 issues에 포함
   - 같은 브랜드의 "다른 제품"이 같은 keyword로 묶이면 안 됨
   - 단, 같은 제품의 패키징 변형(용량, 세트, 기획)은 같은 keyword가 맞음
6. 제품명 변조 여부 (가장 중요):
   - JSON의 name 필드가 스크린샷의 실제 제품명과 일치하는지 엄격히 대조
   - 스크린샷에 보이는 제품명의 핵심 부분(브랜드+라인명+제품고유명)이 JSON에 정확히 반영되었는지
   - 제품명이 요약/축소/변경되었으면 반드시 issues에 포함하고 스크린샷 원본 텍스트를 명시
7. 번들/골라담기 제품 감지:
   - 제품명에 "골라담기", "택1", "N종" 등이 포함된 제품을 모두 찾아서 보고
   - 해당 제품의 search_keyword가 하위 제품군을 포괄하는 공통 키워드인지 확인
   - CLAUDE.md의 "확정된 번들 제품 키워드" 표와 대조하여, 확정 키워드가 있으면 일치하는지 검증
   - 표에 없는 새로운 번들 제품이 발견되면 issues에 포함하여 보고
8. 중복 제품 감지:
   - 같은 제품이 다른 기획(10매 vs 1매, 단품 vs 세트 등)으로 여러 순위에 등장하는지 확인
   - search_keyword가 동일한 제품 쌍이 있으면 모두 보고 (합산 대상)
   - 이전 날짜 데이터가 있으면 비교: 어제 없던 제품이 갑자기 나타났는데, 어제 있던 유사 제품이 사라진 경우 → 같은 제품의 이름 변경 가능성 보고
9. 비화장품 제품 감지:
   - 건강기능식품(단백질 쉐이크, 비타민, 영양제, 콜라겐 음료 등), 식품/스낵(베이글칩 등), 음반/앨범, 구강용품(칫솔, 치아미백 등)이 포함되어 있는지 확인
   - 판단 기준: 피부에 바르거나 붙이는 제품 = 화장품, 먹는 제품/먹는 영양제 = 비화장품
   - 콜라겐 "패치"나 콜라겐 "세럼"은 화장품이므로 OK
   - 비화장품이 발견되면 issues에 포함하여 product_code와 제품명을 명시

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
        with open(keywords_path, "w", encoding="utf-8") as f:
            json.dump(kw_result["keywords"], f, ensure_ascii=False, indent=2)
        safe_print(f"[KEYWORD] {len(kw_result['keywords'])}개 키워드 생성 완료")
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
    parts = [f"""너는 K-Beauty Trend Tracker의 데이터 검증자야.
수집 agent가 올리브영 랭킹 기반으로 네이버/유튜브 API 데이터를 수집했어.
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

### 네이버 API 데이터 검증
- 검색량(search_volume 또는 search_volume_this_week)이 0인 제품 비율: 90% 이상이면 API 이상
- 직전 날짜 데이터 대비 평균 검색량 변동이 10배 이상이면 이상
- 파일명에 "sample"이 포함되어 있으면 샘플 데이터

### 유튜브 API 데이터 검증
- api_error: true인 제품이 있으면 issues에 명시 (API 에러로 -1 반환된 제품)
- 파일명에 "sample"이 포함되어 있으면 샘플 데이터

### video_count_3month 합리성 검증
- video_count_3month 필드가 있는 제품에 대해:
  - video_count_3month가 video_count(2주)보다 작으면 이상 (3개월이 2주보다 적을 수 없음)
  - video_count_3month가 -1이면 API 에러 (issues에 포함)
  - video_count_3month가 1000 이상이면 키워드가 너무 일반적일 가능성 (확인 필요)

### 전체 데이터 품질
- 네이버+유튜브 둘 다 결과가 0인 제품이 전체의 50% 이상이면 이상
- 네이버/유튜브 파일 모두 없으면 passed: false

### 신제품 감지 (new_launches)
다음 두 경로로 신제품 후보를 수집하고 웹검색으로 검증해:

경로 1: 올리브영 JSON의 name_full 필드에 "[NEW" 또는 "선런칭" 또는 "런칭"이 포함된 제품
경로 2: 유튜브 JSON에서 is_new_product_candidate: true인 제품

위 후보에 대해 웹검색("[브랜드명] [제품명] 출시일" 등)으로 실제 출시일을 확인해:
- 1주 이내 출시 확인 → new_launches 배열에 product_code 추가
- 1주 초과 또는 출시일 불명 → 신제품 아님 (추가하지 않음)
- 올리브영이 [NEW]를 붙여도 실제로는 리뉴얼이거나 기획 변경일 수 있으므로 반드시 웹검색 확인

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

    # 이전 날짜 불완전 daily 폴더 + 좀비 상태 파일 정리
    cleanup_incomplete_daily(today_str)

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

    # 임시 파일 정리
    for tmp in [state_path, vr_path,
                os.path.join(DATA_DIR, f"_keywords_{today_str}.json"),
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

    # Step 1은 캡처만 하고 추출은 별도 (Claude Code 또는 DOM 스크래핑)
    today_str = datetime.now().strftime("%Y%m%d")
    oy_path = os.path.join(DATA_DIR, f"oliveyoung_{today_str}.json")
    if not os.path.exists(oy_path):
        safe_print(f"\n[대기] oliveyoung_{today_str}.json 추출 후 다시 실행하세요.")
        safe_print(f"  또는: python run_daily_collect.py step2  (추출 완료 후)")
        return True

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
