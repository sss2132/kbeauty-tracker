import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
YOUTUBE_API_KEY_2 = os.environ.get("YOUTUBE_API_KEY_2")
YOUTUBE_API_KEY_3 = os.environ.get("YOUTUBE_API_KEY_3")
YOUTUBE_API_KEYS = [k for k in [YOUTUBE_API_KEY_3, YOUTUBE_API_KEY, YOUTUBE_API_KEY_2] if k]

# YouTube OAuth (테스트 모드 앱: refresh_token 7일 만료)
YOUTUBE_OAUTH_TOKEN = Path(__file__).parent / "token.json"
YOUTUBE_CLIENT_SECRET = Path(__file__).parent / "client_secret.json"

PERIOD_DAYS = 3

# 프로모션 패널티는 score_calculator.get_promotion_penalty()에서 관리
# (오특/1+1=0.5, 2입 할인율 기반 0.5~0.9)

# === claude -p 타임아웃 (초) ===
TIMEOUT_ENRICH = 600      # Step 1 보강 (배치당, 12개 제품)
TIMEOUT_VERIFY = 600      # Step 2/4 검증 (Opus)
TIMEOUT_KEYWORD = 600     # Step 3 키워드 생성 (배치당, 10개 제품)
TIMEOUT_EN_VERIFY = 600   # Step 3 영문명 검증
TIMEOUT_CAPTURE = 300     # 캡처 스크립트
TIMEOUT_NAVER = 180       # 네이버 API
TIMEOUT_YOUTUBE = 300     # 유튜브 API

# 제휴 파라미터 (승인 후 실제 값으로 교체)
SHOPEE_TH_AFFILIATE_ID = "kbeautyth"
YESSTYLE_AFFILIATE_ID = "kbeautyth"
# OLIVEYOUNG_AFFILIATE_ID = "kbeautyth"  # 올리브영 글로벌 제휴 비활성화


def make_affiliate_url(search_keyword, product_code=None, platform="shopee"):
    import urllib.parse
    encoded = urllib.parse.quote(search_keyword)
    if platform == "shopee":
        return f"https://shopee.co.th/search?keyword={encoded}&af_id={SHOPEE_TH_AFFILIATE_ID}"
    elif platform == "yesstyle":
        return f"https://www.yesstyle.com/en/search.html?keyword={encoded}&ref={YESSTYLE_AFFILIATE_ID}"
    elif platform == "lazada":
        return f"https://www.lazada.co.th/catalog/?q={encoded}"
    elif platform == "amazon":
        return f"https://www.amazon.com/s?k={encoded}"
    # elif platform == "oliveyoung":
    #     return f"https://global.oliveyoung.com/product/{product_code}?ref={OLIVEYOUNG_AFFILIATE_ID}"
