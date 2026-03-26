# 파이프라인 이슈 트래커

## 해결 완료

### ✅ 1. claude -p 서브프로세스 실패
- CLAUDE_EXE 전체 경로로 변경 완료

### ✅ 2. 검증 직접 수행 문제 (unbiased 검증 우회)
- CLAUDE.md에 "직접 검증 금지, Agent tool 사용" 추가

### ✅ 3. 키워드 파일명 충돌
- 키워드 파일명을 `_keywords_YYYYMMDD.json`으로 강제

### ✅ 9. Hidden Gem vs Steady Seller 구분
- video_count_3month + consecutive_periods 기반 구분 구현

### ✅ 11. 영문명 오매칭 (2026-03-27)
- `verify_english_names()` 검증 step 추가 (Step 3 내)
- mismatch 자동 수정, needs_confirm은 웹검색 근거 포함하여 텔레그램으로 사용자 확인
- `english_names_override.json` + `korean_names_override.json`으로 영속 관리

### ✅ 12. 한글 제품명 키워드 누락 (2026-03-27)
- `clean_product_name()` 함수로 올리브영 원본에서 용량/기획만 제거, 핵심 키워드 유지
- 올리브영 축약 표기는 `korean_names_override.json`으로 공식 이름 복원

### ✅ 13. 유튜브 축약 키워드 우선 검색 (2026-03-27)
- 풀네임(ko_override > clean_product_name)으로 1차 검색
- 결과 < 3건이면 youtube_keyword(축약)로 재검색 + 0.7배 패널티

### ✅ 14. 동일 제품 병합 누락 (2026-03-27)
- `english_names_override`에서 같은 영문명 = 같은 제품으로 병합
- 병합 시 가장 긴 name_ko(정식 이름) 사용

### ✅ 15. 구매링크 한글 검색 → 영문 검색 (2026-03-27)
- `make_affiliate_url()`에 `name_en` 전달

### ✅ 16. data/ 구조 정리 (2026-03-27)
- sample 파일 → `data/samples/`로 이동
- Step 5 cleanup에 루트 날짜별 파일 정리 로직 추가 (daily/에 보존 후 루트 삭제)

## 미해결 / 모니터링

### ⚠️ 5. DOM 추출 65개 (60개 초과)
- DOM 스크래핑에서 정확히 60개만 추출하도록 필터링 필요

### ⚠️ 6. API 검증에서 키워드 품질(라인명 구분) 미검증
- 같은 브랜드 라인 내 다른 제품 구분 여부 검증 항목 추가 필요

### ⚠️ 7. 유튜브 API 에러 시 무음 실패
- API 에러 발생 시 `api_error: true` 반환하도록 수정됨
- 다만 API 할당량 소진 시 403 → 키 로테이션 후에도 실패하면 -1 반환

### ⚠️ 8. 유튜브 youtube_available 기준 (video_count >= 3)
- 현재 유지 중. 1~2개 영상은 노이즈가 클 수 있어 3개 기준 유지
