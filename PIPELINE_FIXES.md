# 파이프라인 수정 필요 사항 (2026-03-22 테스트에서 발견)

## 1. claude -p 서브프로세스 실패
- 증상: 스케줄러 세션에서 검증 Agent(claude -p) 실행 실패
- 원인 추정: PATH에 claude 없음 또는 동시 실행 충돌
- 임시 조치: CLAUDE_EXE 전체 경로로 변경 완료
- 확인 필요: 전체 경로로도 실패하면 동시 실행 충돌이 원인

## 2. 검증 직접 수행 문제 (unbiased 검증 우회)
- 증상: claude -p 실패 시 orchestrator Claude가 직접 검증 → 10초 만에 끝남 (대충 넘김)
- 원인: 수집한 세션이 직접 검증하면 bias 발생
- 조치: CLAUDE.md에 "직접 검증 금지, Agent tool 사용" 추가함
- 추가 필요: 파이프라인 코드에서 claude -p 실패 시 fallback 동작을 명확히 (재시도 또는 중단)

## 3. 키워드 파일명 충돌 [수정 완료]
- 증상: 키워드 Agent가 oliveyoung_20260322_keywords.json으로 저장 → 네이버/유튜브 스크립트가 올리브영 데이터로 잘못 인식
- 원인: 키워드 파일이 data/ 폴더에 oliveyoung_ 접두사로 저장됨
- 수정: 키워드 파일명을 _keywords_YYYYMMDD.json으로 강제 (기존 코드 452줄에 이미 있으나, 키워드 Agent가 다른 이름으로 저장)
- 또는: 네이버/유튜브 스크립트에서 oliveyoung_*_keywords.json 패턴 제외

## 4. 인라인 Python 이스케이핑 실패
- 증상: Bash에서 인라인 Python 스크립트 실행 시 따옴표 이스케이핑 에러
- 원인: 새 Claude 세션이 복잡한 인라인 스크립트를 구성할 때 발생
- 영향: 낮음 (Claude가 파일로 작성해서 자동 복구)

## 5. DOM 추출 65개 (60개 초과)
- 증상: DOM 스크래핑에서 60개가 아닌 65개 제품 추출
- 원인: 페이지에 숨겨진 요소 또는 중복 노드
- 수정 필요: DOM 추출 로직에서 정확히 60개만 추출하도록 필터링

## 6. API 검증에서 키워드 품질(라인명 구분) 미검증 [키워드 규칙 수정 완료, 검증 항목은 미수정]
- 증상: "CLIO Kill Cover Cushion"으로 키워드 생성됨. 실제로는 Kill Cover 라인에 파운웨어/더뉴/메쉬글로우 등 여러 쿠션이 있어서 "CLIO Kill Cover Founwear Cushion"이어야 구분 가능
- 원인: 키워드 agent 규칙에 "핵심 제품 타입만"이라 라인 내 세부 제품명이 잘림
- 검증 agent도 "같은 브랜드 동일 keyword" 검사만 있고, 라인 내 다른 제품 구분 여부는 미검증
- 수정 필요:
  1. 키워드 agent 규칙에 "같은 브랜드 라인 내 다른 제품이 있으면 고유 제품명(파운웨어 등) 포함" 추가
  2. API 검증 프롬프트에 "같은 브랜드 라인의 다른 제품과 구분되는 키워드인지" 검증 항목 추가

## 7. 유튜브 API 에러 시 무음 실패
- 증상: API 에러(할당량 소진 포함)가 나면 0, 0, 0, 0, 0.0 반환 → 정상 결과(영상 없음)와 구분 불가
- 위치: youtube_trend.py 118~120줄
- 수정 필요: API 에러 발생 시 텔레그램 알림 또는 에러 플래그 추가

## 8. 유튜브 youtube_available 기준이 엄격 (video_count >= 3)
- 증상: 최근 1주 영상 1~2개인 제품도 youtube_available: false 처리
- 위치: youtube_trend.py 160줄
- 검토 필요: 기준을 >= 1로 낮출지 여부

## 9. Hidden Gem vs Steady Seller 구분 추가 ✅
- 구현 완료:
  - youtube_trend.py: 전체 제품에 대해 6개월 영상 수(`video_count_6month`) 조회 추가
  - score_calculator.py detect_flags():
    - 기본 조건: OY > 70 + NS < 30 + YT < 30
    - steady_seller 조건 (OR): 유튜브 6개월 리뷰 >= 30 OR consecutive_periods >= 10 (30일)
    - 하나라도 충족 → steady_seller, 둘 다 미충족 → hidden_gem
  - seller_grade: steady_seller → "proven"
  - output JSON에 steady_sellers 배열 + stats 추가

## 10. Step 4 API 검증이 실제로 unbiased하게 실행되지 않았을 가능성
- 증상: Step 2와 같은 claude -p 서브프로세스 문제로 검증을 직접 수행했을 수 있음
- 확인 필요: 다음 테스트에서 step4도 claude -p가 정상 실행되는지 확인
