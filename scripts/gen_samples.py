"""Generate sample data for Naver and YouTube with OY rank mismatch."""
import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Naver: search_volume intentionally NOT correlated with OY rank
# Hidden Gem targets: A9(OY#8), A20(OY#14) -> very low search
# Buzz Trap targets: A35(OY#44), A42(OY#41), A22(OY#50) -> very high search
nv = {
    "A000000000007": ("아누아 토너패드", 12000, 10500),
    "A000000000051": ("롬앤 쥬시 틴트", 10000, 9200),
    "A000000000001": ("토리든 세럼", 18000, 15500),
    "A000000000004": ("구달 비타C 세럼", 16000, 11000),
    "A000000000013": ("메디힐 마스크팩", 5500, 5800),
    "A000000000018": ("티르티르 쿠션", 28000, 12000),
    "A000000000002": ("라운드랩 독도 토너", 11000, 10200),
    "A000000000009": ("바이오던스 마스크", 1100, 1200),
    "A000000000048": ("코스알엑스 핌프 패치", 25000, 10000),
    "A000000000010": ("넘버즈인 비타민C", 6200, 5800),
    "A000000000012": ("달바 스프레이 세럼", 4200, 4500),
    "A000000000008": ("이니스프리 노세범 선크림", 1500, 1800),
    "A000000000017": ("라운드랩 선크림", 9000, 8400),
    "A000000000020": ("에뛰드 손정 크림", 1300, 1500),
    "A000000000014": ("VDL 파운데이션", 6800, 6500),
    "A000000000006": ("클리오 킬커버 쿠션", 22000, 19000),
    "A000000000033": ("라네즈 립 슬리핑 마스크", 14000, 11800),
    "A000000000021": ("조선미녀 글로우 세럼", 6500, 6000),
    "A000000000016": ("믹순 빈 에센스", 2000, 2200),
    "A000000000034": ("이니스프리 노세범 파우더", 8500, 8000),
    "A000000000024": ("모레모 트리트먼트", 7500, 7000),
    "A000000000031": ("스킨1004 센텔라 토너", 5800, 5400),
    "A000000000003": ("코스알엑스 스네일 에센스", 2800, 3200),
    "A000000000025": ("바닐라코 클렌징밤", 3000, 3200),
    "A000000000023": ("조선미녀 선크림", 4500, 4800),
    "A000000000039": ("에뛰드 아이 팔레트", 9500, 8200),
    "A000000000036": ("설화수 퍼스트 케어", 3600, 3800),
    "A000000000037": ("헤이미쉬 클렌징밤", 3500, 3200),
    "A000000000038": ("클레어스 도트 세럼", 35000, 14000),
    "A000000000032": ("썸바이미 미라클 토너", 7000, 6500),
    "A000000000041": ("일리윤 세라마이드 크림", 2200, 2400),
    "A000000000026": ("미장센 헤어오일", 3200, 3000),
    "A000000000027": ("해피바스 바디워시", 1500, 1400),
    "A000000000028": ("더마토리 마스크팩", 2500, 2300),
    "A000000000040": ("이니스프리 그린티 세럼", 4800, 5000),
    "A000000000015": ("라로슈포제 시카밤", 5000, 5200),
    "A000000000005": ("에스네이처 수분크림", 1200, 1400),
    "A000000000019": ("바이오던스 판테놀 마스크", 8000, 7200),
    "A000000000029": ("모레모 워터 트리트먼트", 7200, 6800),
    "A000000000030": ("일리윤 바디로션", 1800, 2000),
    "A000000000042": ("토니모리 레티놀", 38000, 9500),
    "A000000000043": ("에뛰드 더블래스팅", 5200, 4900),
    "A000000000044": ("코스알엑스 AC 크림", 3800, 3500),
    "A000000000035": ("스킨푸드 글루타치온", 45000, 8500),
    "A000000000045": ("OST 비타민C 세럼", 2400, 2200),
    "A000000000046": ("클레어스 토너", 6000, 5500),
    "A000000000047": ("닥터지 선크림", 4000, 3700),
    "A000000000049": ("믹순 머쉬룸 크림", 1000, 900),
    "A000000000050": ("라보에이치 헤어팩", 900, 850),
    "A000000000022": ("롬앤 블러셔", 32000, 15000),
}

naver_data = []
for code, (kw, vol, vol_lw) in nv.items():
    cr = round((vol - vol_lw) / vol_lw * 100, 1) if vol_lw > 0 else 0.0
    naver_data.append({
        "product_code": code, "keyword": kw,
        "search_volume": vol, "search_volume_last_week": vol_lw, "change_rate": cr,
    })

# OUTSIDE entries
naver_data.extend([
    {"product_code": "OUTSIDE_NV_001", "keyword": "조선미녀 맑은쌀 선크림", "search_keyword_en": "Beauty of Joseon Rice Sunscreen", "search_volume": 38000, "search_volume_last_week": 15000, "change_rate": 153.3},
    {"product_code": "OUTSIDE_NV_002", "keyword": "스킨1004 센텔라 앰플", "search_keyword_en": "SKIN1004 Centella Ampoule", "search_volume": 22000, "search_volume_last_week": 9500, "change_rate": 131.6},
    {"product_code": "OUTSIDE_NV_003", "keyword": "아이소이 레티놀 크림", "search_keyword_en": "isoi Retinol Cream", "search_volume": 18000, "search_volume_last_week": 8000, "change_rate": 125.0},
    {"product_code": "OUTSIDE_NV_004", "keyword": "마녀공장 갈락토미 에센스", "search_keyword_en": "Manyo Galactomy Essence", "search_volume": 14500, "search_volume_last_week": 7200, "change_rate": 101.4},
    {"product_code": "OUTSIDE_NV_005", "keyword": "닥터자르트 시카페어 크림", "search_keyword_en": "Dr.Jart Cicapair Cream", "search_volume": 11000, "search_volume_last_week": 6000, "change_rate": 83.3},
])

with open(os.path.join(DATA_DIR, "naver_sample.json"), "w", encoding="utf-8") as f:
    json.dump(naver_data, f, ensure_ascii=False, indent=2)
print(f"Naver sample: {len(naver_data)} entries")

# YouTube: total_views intentionally NOT correlated with OY rank
# code: (keyword, video_count, total_views, vc_last_week, tv_last_week)
yt = {
    "A000000000007": ("ANUA Heartleaf Toner Pad", 42, 680000, 35, 550000),
    "A000000000051": ("romand Juicy Lasting Tint", 28, 600000, 22, 480000),
    "A000000000001": ("Torriden DIVE-IN Serum", 45, 850000, 38, 720000),
    "A000000000004": ("Goodal Vitamin C Serum", 32, 750000, 25, 520000),
    "A000000000013": ("Mediheal NMF Mask", 15, 130000, 12, 140000),
    "A000000000018": ("TIRTIR Red Cushion", 95, 1400000, 70, 800000),
    "A000000000002": ("Round Lab Dokdo Toner", 38, 380000, 30, 340000),
    "A000000000009": ("Biodance Collagen Mask", 8, 20000, 6, 18000),  # HIDDEN GEM
    "A000000000048": ("COSRX Pimple Patch", 85, 1200000, 60, 550000),
    "A000000000010": ("numbuzin Vitamin C", 22, 420000, 18, 380000),
    "A000000000012": ("dAlba White Truffle Serum", 18, 95000, 15, 100000),
    "A000000000008": ("Innisfree Sunscreen", 10, 25000, 8, 28000),
    "A000000000017": ("Round Lab Sunscreen", 20, 320000, 16, 290000),
    "A000000000020": ("Etude SoonJung Cream", 7, 22000, 5, 25000),  # HIDDEN GEM
    "A000000000014": ("VDL Foundation", 15, 230000, 12, 210000),
    "A000000000006": ("CLIO Kill Cover Cushion", 65, 1100000, 50, 880000),
    "A000000000033": ("LANEIGE Lip Sleeping Mask", 60, 950000, 48, 800000),
    "A000000000021": ("Beauty of Joseon Glow Serum", 40, 550000, 32, 480000),
    "A000000000016": ("mixsoon Bean Essence", 12, 35000, 10, 38000),
    "A000000000034": ("Innisfree No Sebum Powder", 40, 400000, 35, 370000),
    "A000000000024": ("Moremo Hair Treatment", 22, 280000, 18, 250000),
    "A000000000031": ("SKIN1004 Centella Toner", 15, 200000, 12, 185000),
    "A000000000003": ("COSRX Snail Mucin", 120, 800000, 95, 850000),
    "A000000000025": ("Banila Co Clean It Zero", 30, 180000, 25, 190000),
    "A000000000023": ("Beauty of Joseon Sunscreen", 50, 500000, 42, 520000),
    "A000000000039": ("Etude Eye Palette", 25, 350000, 20, 310000),
    "A000000000036": ("Sulwhasoo First Care", 20, 60000, 18, 65000),
    "A000000000037": ("heimish All Clean Balm", 18, 150000, 15, 140000),
    "A000000000038": ("Klairs Serum", 55, 900000, 40, 480000),
    "A000000000032": ("SOME BY MI Miracle Toner", 35, 450000, 28, 400000),
    "A000000000041": ("Illiyoon Ceramide Cream", 18, 40000, 15, 42000),
    "A000000000026": ("mise en scene Hair Oil", 10, 65000, 8, 60000),
    "A000000000027": ("Happy Bath Body Wash", 5, 30000, 4, 25000),
    "A000000000028": ("Dermatory Mask", 8, 45000, 6, 42000),
    "A000000000040": ("Innisfree Green Tea Serum", 22, 120000, 18, 125000),
    "A000000000015": ("La Roche Posay Cicaplast", 25, 250000, 20, 230000),
    "A000000000005": ("esNature Squalane Cream", 6, 20000, 5, 22000),
    "A000000000019": ("Biodance Panthenol Mask", 30, 110000, 25, 95000),
    "A000000000029": ("Moremo Water Treatment", 25, 170000, 20, 155000),
    "A000000000030": ("Illiyoon Body Lotion", 12, 25000, 10, 28000),
    "A000000000042": ("TONYMOLY Retinol", 42, 1900000, 15, 350000),  # BUZZ TRAP
    "A000000000043": ("Etude Double Lasting", 15, 100000, 12, 95000),
    "A000000000044": ("COSRX AC Collection", 12, 85000, 10, 80000),
    "A000000000035": ("SKINFOOD Glutathione", 48, 1500000, 18, 280000),  # BUZZ TRAP
    "A000000000045": ("OST Vitamin C Serum", 10, 50000, 8, 48000),
    "A000000000046": ("Klairs Supple Toner", 20, 190000, 16, 175000),
    "A000000000047": ("Dr.G Sunscreen", 14, 75000, 11, 70000),
    "A000000000049": ("mixsoon Mushroom Cream", 35, 18000, 28, 15000),
    "A000000000050": ("Lador Hair Pack", 8, 22000, 6, 20000),
    "A000000000022": ("Romand Blusher", 70, 1700000, 50, 850000),  # BUZZ TRAP
}

youtube_data = []
for code, (kw, vc, tv, vc_lw, tv_lw) in yt.items():
    cr = round((tv - tv_lw) / tv_lw * 100, 1) if tv_lw > 0 else 0.0
    youtube_data.append({
        "product_code": code, "keyword": kw,
        "video_count": vc, "total_views": tv,
        "video_count_last_week": vc_lw, "total_views_last_week": tv_lw,
        "change_rate": cr,
    })

youtube_data.extend([
    {"product_code": "OUTSIDE_YT_001", "keyword": "Peripera Ink Tint", "search_keyword_en": "Peripera Ink Tint", "video_count": 65, "total_views": 4500000, "video_count_last_week": 40, "total_views_last_week": 1500000, "change_rate": 200.0},
    {"product_code": "OUTSIDE_YT_002", "keyword": "Medicube Age-R Booster", "search_keyword_en": "Medicube Age-R Booster", "video_count": 48, "total_views": 3200000, "video_count_last_week": 30, "total_views_last_week": 1200000, "change_rate": 166.7},
    {"product_code": "OUTSIDE_YT_003", "keyword": "Abib Heartleaf Calming Pad", "search_keyword_en": "Abib Heartleaf Pad", "video_count": 38, "total_views": 2100000, "video_count_last_week": 25, "total_views_last_week": 800000, "change_rate": 162.5},
    {"product_code": "OUTSIDE_YT_004", "keyword": "VT Cica Cream review", "search_keyword_en": "VT Cica Cream", "video_count": 30, "total_views": 1800000, "video_count_last_week": 22, "total_views_last_week": 750000, "change_rate": 140.0},
    {"product_code": "OUTSIDE_YT_005", "keyword": "Hanyul Artemisia Essence", "search_keyword_en": "Hanyul Artemisia Essence", "video_count": 22, "total_views": 900000, "video_count_last_week": 15, "total_views_last_week": 400000, "change_rate": 125.0},
])

with open(os.path.join(DATA_DIR, "youtube_sample.json"), "w", encoding="utf-8") as f:
    json.dump(youtube_data, f, ensure_ascii=False, indent=2)
print(f"YouTube sample: {len(youtube_data)} entries")

# Naver Shopping Rank (인기도순): intentionally NOT correlated with OY rank
# Low rank number = more popular. None = not found in search results.
# Buzz Trap targets: high social but BAD naver rank (low popularity on shopping)
# Hidden Gem targets: good naver rank (high shopping popularity) but low social
nr = {
    "A000000000007": ("아누아 토너패드", 5, "아누아 어성초 77 수딩 토너 패드", 16900),
    "A000000000051": ("롬앤 쥬시 틴트", 8, "롬앤 쥬시 래스팅 틴트 25호", 8900),
    "A000000000001": ("토리든 세럼", 2, "토리든 다이브인 저분자 히알루론산 세럼", 15800),
    "A000000000004": ("구달 비타C 세럼", 12, "구달 청귤 비타C 잡티 세럼", 14200),
    "A000000000013": ("메디힐 마스크팩", 3, "메디힐 N.M.F 아쿠아링 앰플 마스크", 8500),
    "A000000000018": ("티르티르 쿠션", 1, "티르티르 마스크 핏 레드 쿠션", 18900),
    "A000000000002": ("라운드랩 독도 토너", 7, "라운드랩 1025 독도 토너", 12800),
    "A000000000009": ("바이오던스 마스크", 4, "바이오던스 바이오 콜라겐 리얼 딥 마스크", 22000),  # HIDDEN GEM: good rank
    "A000000000048": ("코스알엑스 핌프 패치", 15, "코스알엑스 아크네 핌플 마스터 패치", 4500),
    "A000000000010": ("넘버즈인 비타민C", 9, "넘버즈인 3번 비타민C 브라이트닝 세럼", 16500),
    "A000000000012": ("달바 스프레이 세럼", 22, "달바 화이트 트러플 퍼스트 스프레이 세럼", 28000),
    "A000000000008": ("이니스프리 선크림", 6, "이니스프리 데일리 UV 디펜스 선스크린", 12000),  # HIDDEN GEM: good rank
    "A000000000017": ("라운드랩 선크림", 11, "라운드랩 자작나무 수분 선크림", 14500),
    "A000000000020": ("에뛰드 손정 크림", 10, "에뛰드 순정 2x 배리어 인텐시브 크림", 15800),  # HIDDEN GEM: good rank
    "A000000000014": ("VDL 파운데이션", 28, "VDL 커버스테이션 파운데이션", 25000),
    "A000000000006": ("클리오 킬커버 쿠션", 13, "클리오 킬커버 더 뉴 펀웨어 쿠션", 23000),
    "A000000000033": ("라네즈 립 마스크", 16, "라네즈 립 슬리핑 마스크", 15000),
    "A000000000021": ("조선미녀 글로우 세럼", 20, "조선미녀 광채 세럼", 16000),
    "A000000000016": ("믹순 빈 에센스", 35, "믹순 빈 에센스", 22000),
    "A000000000034": ("이니스프리 노세범 파우더", 14, "이니스프리 노세범 미네랄 파우더", 7500),
    "A000000000024": ("모레모 트리트먼트", 18, "모레모 헤어 트리트먼트 미라클 2x", 12500),
    "A000000000031": ("스킨1004 센텔라 토너", 25, "스킨1004 마다가스카 센텔라 토닝 토너", 16800),
    "A000000000003": ("코스알엑스 스네일 에센스", 17, "코스알엑스 어드밴스드 스네일 96 에센스", 12500),
    "A000000000025": ("바닐라코 클렌징밤", 19, "바닐라코 클린 잇 제로 클렌징 밤", 14800),
    "A000000000023": ("조선미녀 선크림", 21, "조선미녀 맑은쌀 선크림", 14500),
    "A000000000039": ("에뛰드 아이 팔레트", 30, "에뛰드 플레이 컬러 아이즈 팔레트", 19800),
    "A000000000036": ("설화수 퍼스트 케어", 42, "설화수 퍼스트 케어 액티베이팅 세럼", 52000),
    "A000000000037": ("헤이미쉬 클렌징밤", 24, "헤이미쉬 올클린 밤 클렌저", 14000),
    "A000000000038": ("클레어스 도트 세럼", 26, "클레어스 프레쉬리 쥬스드 비타민 드롭", 18500),
    "A000000000032": ("썸바이미 미라클 토너", 23, "썸바이미 AHA BHA PHA 30 데이즈 미라클 토너", 12000),
    "A000000000041": ("일리윤 세라마이드 크림", 27, "일리윤 세라마이드 아토 집중 크림", 19800),
    "A000000000026": ("미장센 헤어오일", 33, "미장센 퍼펙트 세럼 오리지널", 8900),
    "A000000000027": ("해피바스 바디워시", 38, "해피바스 오리지널 컬렉션 바디워시", 7500),
    "A000000000028": ("더마토리 마스크팩", 40, "더마토리 프로 시카 진정 마스크", 11000),
    "A000000000040": ("이니스프리 그린티 세럼", 31, "이니스프리 그린티 씨드 세럼", 22000),
    "A000000000015": ("라로슈포제 시카밤", 29, "라로슈포제 시카플라스트 밤 B5+", 18500),
    "A000000000005": ("에스네이처 수분크림", 36, "에스네이처 아쿠아 스쿠알란 수분 크림", 21000),
    "A000000000019": ("바이오던스 판테놀 마스크", 32, "바이오던스 판테놀 시카 마스크", 19800),
    "A000000000029": ("모레모 워터 트리트먼트", 34, "모레모 워터 트리트먼트 미라클 10", 12000),
    "A000000000030": ("일리윤 바디로션", 37, "일리윤 세라마이드 아토 로션", 15800),
    "A000000000042": ("토니모리 레티놀", 85, "토니모리 백 레티놀 앰플", 19800),  # BUZZ TRAP: bad rank
    "A000000000043": ("에뛰드 더블래스팅", 45, "에뛰드 더블 래스팅 파운데이션", 18000),
    "A000000000044": ("코스알엑스 AC 크림", 48, "코스알엑스 AC 컬렉션 크림", 16500),
    "A000000000035": ("스킨푸드 글루타치온", 92, "스킨푸드 로열허니 프로폴리스 인리치드 크림", 22000),  # BUZZ TRAP: bad rank
    "A000000000045": ("OST 비타민C 세럼", 55, "OST 퓨어 비타민 C21.5 어드밴스드 세럼", 15000),
    "A000000000046": ("클레어스 토너", 39, "클레어스 서플 프레퍼레이션 페이셜 토너", 16500),
    "A000000000047": ("닥터지 선크림", 43, "닥터지 그린 마일드 업 선 플러스", 16000),
    "A000000000049": ("믹순 머쉬룸 크림", 60, "믹순 머쉬룸 바이탈라이징 크림", 25000),
    "A000000000050": ("라보에이치 헤어팩", 65, "라보에이치 판테놀 헤어팩", 14800),
    "A000000000022": ("롬앤 블러셔", 78, "롬앤 쥬시 래스팅 블러셔", 9800),  # BUZZ TRAP: bad rank
}

naver_rank_data = []
for code, (kw, rank, matched, price) in nr.items():
    naver_rank_data.append({
        "product_code": code,
        "keyword": kw,
        "naver_shopping_rank": rank,
        "matched_title": matched,
        "matched_price": price,
        "total_results": 100,
    })

with open(os.path.join(DATA_DIR, "naver_rank_sample.json"), "w", encoding="utf-8") as f:
    json.dump(naver_rank_data, f, ensure_ascii=False, indent=2)
print(f"Naver Rank sample: {len(naver_rank_data)} entries")
