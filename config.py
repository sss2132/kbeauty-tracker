import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")

# 제휴 파라미터 (승인 후 실제 값으로 교체)
SHOPEE_TH_AFFILIATE_ID = "kbeautyth"
YESSTYLE_AFFILIATE_ID = "kbeautyth"
OLIVEYOUNG_AFFILIATE_ID = "kbeautyth"


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
    elif platform == "oliveyoung":
        return f"https://global.oliveyoung.com/product/{product_code}?ref={OLIVEYOUNG_AFFILIATE_ID}"
