"""
올리브영 랭킹 페이지 자동 캡처 스크립트
Playwright chromium 사용.

사용법: python scripts/capture_oliveyoung.py

캡처 결과: Oliveyoung collection/oliveyoung_YYYYMMDD_1.png ~ 5.png
5장 x 12제품(4열x3행) = 60제품
device_scale_factor=2 로 고해상도 캡처 (리사이즈 없음)
"""

from playwright.sync_api import sync_playwright
from datetime import datetime
import os
import sys

URL = 'https://www.oliveyoung.co.kr/store/main/getBestList.do'

# 프로젝트 루트 (K-Beauty)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'Oliveyoung collection')
ARCHIVE_DIR = os.path.join(OUTPUT_DIR, 'Archive')

CAPTURE_COUNT = 5
PRODUCTS_PER_CAPTURE = 12  # 4열 x 3행
ROWS_PER_CAPTURE = 3


def main():
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1400, 'height': 900},
            device_scale_factor=2,
            locale='ko-KR',
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        )
        page = context.new_page()

        print('Navigating to Oliveyoung ranking page...')
        page.goto(URL, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(5000)

        page.wait_for_selector('.prd_info', timeout=30000)
        print('Ranking list loaded.')

        # Close popups
        try:
            page.click('.btnClose', timeout=3000)
        except Exception:
            pass
        page.evaluate("""() => {
            document.querySelectorAll('[class*="popup"], [class*="modal"], [id*="popup"]').forEach(el => {
                if (el.style) el.style.display = 'none';
            });
            var header = document.querySelector('#header') || document.querySelector('header');
            if (header) header.style.position = 'absolute';
        }""")

        # 전체 페이지 높이 확보를 위해 맨 아래까지 스크롤
        page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        page.wait_for_timeout(2000)
        page.evaluate('window.scrollTo(0, 0)')
        page.wait_for_timeout(1000)

        # 그리드 정보 수집: 각 행의 첫 아이템 y 좌표로 정확한 행 높이 계산
        grid_info = page.evaluate("""() => {
            var items = document.querySelectorAll('.cate_prd_list li');
            if (items.length === 0) return null;
            var listEl = items[0].closest('ul');
            var listRect = listEl.getBoundingClientRect();

            // 4열 그리드 → 0,4,8번째 아이템이 각 행의 시작
            var rows = [];
            for (var i = 0; i < Math.min(items.length, 60); i += 4) {
                var rect = items[i].getBoundingClientRect();
                rows.push(rect.top + window.scrollY);
            }
            var rowHeight = rows.length > 1 ? rows[1] - rows[0] : 400;
            return {
                'listX': listRect.left,
                'gridWidth': listRect.width,
                'rows': rows,
                'rowHeight': rowHeight,
                'totalRows': rows.length
            };
        }""")
        print(f'Grid: {grid_info["totalRows"]} rows, rowHeight={grid_info["rowHeight"]:.0f}px')

        clip_x = grid_info['listX']
        grid_width = grid_info['gridWidth']
        rows = grid_info['rows']
        row_height = grid_info['rowHeight']

        saved_files = []

        for i in range(CAPTURE_COUNT):
            filename = f'oliveyoung_{today}_{i + 1}.png'
            filepath = os.path.join(OUTPUT_DIR, filename)

            # i번째 캡처: 행 i*3 ~ i*3+2 (3줄)
            start_row = i * ROWS_PER_CAPTURE
            if start_row >= len(rows):
                break

            y_start = rows[start_row]
            capture_height = row_height * ROWS_PER_CAPTURE + 20  # 약간 여유

            # full_page=True + clip으로 정확한 영역 캡처 (뷰포트 제약 없음)
            page.screenshot(
                path=filepath,
                full_page=True,
                clip={
                    'x': max(0, clip_x),
                    'y': y_start - 10,
                    'width': grid_width,
                    'height': capture_height,
                }
            )

            from PIL import Image
            img = Image.open(filepath)
            saved_files.append(filename)
            print(f'Captured: {filename} ({img.width}x{img.height}) rows {start_row+1}-{start_row+ROWS_PER_CAPTURE}')

        browser.close()

    print(f'\n캡처 완료, Oliveyoung collection에 {len(saved_files)}장 저장됨')
    return saved_files


if __name__ == '__main__':
    main()
