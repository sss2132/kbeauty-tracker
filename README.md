# K-Beauty Trend Tracker

태국 소비자/셀러/인플루언서를 위한 K-Beauty 트렌드 분석 사이트.
Olive Young Korea, Naver Shopping, YouTube 데이터를 통합하여 주간 트렌드 점수를 산출합니다.

## 설치

```bash
pip install -r requirements.txt
```

## 주간 데이터 업데이트

### 1. 올리브영 랭킹 데이터 준비

올리브영 베스트 셀러 TOP 50 데이터를 수집하여 `data/oliveyoung_YYYYMMDD.json` 형식으로 저장합니다.

```json
[
  {
    "rank": 1,
    "name": "다이브인 저분자 히알루론산 세럼 50ml",
    "brand": "토리든",
    "brand_en": "Torriden",
    "name_en": "DIVE-IN Low Molecular Hyaluronic Acid Serum",
    "search_keyword": "Torriden DIVE-IN Serum",
    "category": "skincare",
    "url": "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000000001",
    "product_code": "A000000000001",
    "review_count": 28543,
    "rating": 4.8
  }
]
```

**필수 필드:** `rank`, `name`, `brand`, `category`, `product_code`
**권장 필드:** `brand_en`, `name_en`, `search_keyword` (제휴 URL 생성에 사용)

### 2. 파이프라인 실행

```bash
python run_weekly.py
```

실행 흐름:
1. 올리브영 데이터 확인 (없으면 sample 사용 + 경고)
2. 네이버 쇼핑 트렌드 조회
3. 유튜브 트렌드 조회
4. 종합 점수 계산 (50개 분석 → TOP 30 선정)
5. 정적 사이트 생성 (`docs/index.html`)

## API 키 설정

환경변수로 API 키를 설정합니다.

```bash
# 네이버 데이터랩 API
export NAVER_CLIENT_ID="your_client_id"
export NAVER_CLIENT_SECRET="your_client_secret"

# YouTube Data API v3
export YOUTUBE_API_KEY="your_api_key"
```

API 키를 설정하지 않으면 **샘플 데이터로 동작**하며, 사이트에 경고 배너가 표시됩니다.

## GitHub Pages 배포

1. `docs/` 폴더를 GitHub Pages 소스로 설정 (Settings → Pages → Source: `docs/`)
2. `python run_weekly.py` 실행 후 커밋 & 푸시하면 자동 배포

## 데이터 구조

### oliveyoung_*.json
올리브영 베스트 셀러 TOP 50 제품 정보.

### weekly_ranking_*.json
주간 분석 결과. 주요 필드:

| 필드 | 설명 |
|------|------|
| `data_status` | 각 소스별 데이터 가용 상태 |
| `active_weights` | 실제 적용된 가중치 (소스 실패 시 자동 재분배) |
| `products` | TOP 30 제품 (종합 점수 기준) |
| `products_extended` | 31~50위 제품 |
| `dropped_products` | 이전 주 TOP 30에서 이탈한 제품 |
| `buzz_traps` | 소셜 버즈 대비 실판매 낮은 제품 |
| `hidden_gems` | 판매 좋지만 소셜 노출 낮은 제품 |
| `outside_oliveyoung` | OY 밖에서 뜨는 키워드 |

### data_status 필드

```json
{
  "data_status": {
    "oliveyoung": {"available": true, "product_count": 50, "source": "api"},
    "naver": {"available": true, "product_count": 50, "source": "sample"},
    "youtube": {"available": false, "product_count": 0, "reason": "API 키 없음"}
  },
  "active_weights": {"oliveyoung": 0.56, "naver": 0.44}
}
```

소스 실패 시 가중치 자동 재분배:
- 3소스 정상: OY 45% + NV 35% + YT 20%
- 유튜브 실패: OY 56% + NV 44%
- 네이버 실패: OY 69% + YT 31%
- 네이버+유튜브 실패: OY 100%

## 점수 계산 방식

| 소스 | 기본 가중치 | 점수 산정 |
|------|------------|----------|
| Olive Young | 45% | 순위 기반 (1위=100점) + 리뷰 보너스 |
| Naver Shopping | 35% | 검색량 전주 대비 변화율 |
| YouTube | 20% | 리뷰 영상 조회수 변화율 |

## 시그널/플래그

| 시그널 | 조건 | 의미 |
|--------|------|------|
| HOT | 종합 점수 ≥ 85 | 현재 가장 인기 |
| RISING | OY 순위 30위 밖 → 종합 TOP 30 진입 | 곧 뜰 제품 |
| BUZZ TRAP | 소셜 점수 > 70 AND OY < 40 | 과대 포장 위험 |
| HIDDEN GEM | OY > 70 AND NV < 30 AND YT < 30 | 숨은 기회 |
