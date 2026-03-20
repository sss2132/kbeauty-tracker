"""
올리브영 랭킹 페이지 자동 캡처 스크립트
Playwright chromium 사용.

사용법: python scripts/capture_oliveyoung.py

캡처 결과: Oliveyoung collection/oliveyoung_YYYYMMDD_1.png ~ 8.png
"""

from playwright.sync_api import sync_playwright
from datetime import datetime
from PIL import Image
import os
import sys

URL = 'https://www.oliveyoung.co.kr/store/main/getBestList.do'

# 프로젝트 루트 (K-Beauty)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'Oliveyoung collection')
ARCHIVE_DIR = os.path.join(OUTPUT_DIR, 'Archive')
REF_DIR = os.path.join(OUTPUT_DIR, 'Reference')

CAPTURE_COUNT = 8
PRODUCTS_PER_CAPTURE = 8  # 4열 x 2행
ROWS_PER_CAPTURE = 2

# Reference 이미지 크기 참고 (약 705x828)
TARGET_WIDTH = 705
TARGET_HEIGHT = 828


def get_reference_size():
    """Reference 폴더의 이미지 크기 평균을 가져옴."""
    try:
        sizes = []
        for f in os.listdir(REF_DIR):
            if f.endswith('.png'):
                img = Image.open(os.path.join(REF_DIR, f))
                sizes.append(img.size)
        if sizes:
            avg_w = round(sum(s[0] for s in sizes) / len(sizes))
            avg_h = round(sum(s[1] for s in sizes) / len(sizes))
            return avg_w, avg_h
    except Exception:
        pass
    return TARGET_WIDTH, TARGET_HEIGHT


def main():
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')

    target_w, target_h = get_reference_size()
    print(f'Target size: {target_w}x{target_h} (from Reference)')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1400, 'height': 900},
            device_scale_factor=1,
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

        # Get grid info
        grid_info = page.evaluate("""() => {
            var items = document.querySelectorAll('.prd_info');
            if (items.length === 0) return null;
            var listEl = items[0].closest('.prd_list_sec') || items[0].closest('ul');
            var rect = listEl.getBoundingClientRect();
            var firstItem = items[0].closest('li');
            var itemRect = firstItem.getBoundingClientRect();
            return {
                'listX': rect.left,
                'listY': rect.top + window.scrollY,
                'gridWidth': rect.width,
                'itemHeight': itemRect.height
            };
        }""")
        print(f'Grid info: {grid_info}')

        clip_x = grid_info['listX']
        grid_width = grid_info['gridWidth']
        list_y_start = grid_info['listY']
        row_height = grid_info['itemHeight']

        capture_height = row_height * ROWS_PER_CAPTURE
        scroll_per_capture = capture_height

        saved_files = []

        for i in range(CAPTURE_COUNT):
            filename = f'oliveyoung_{today}_{i + 1}.png'
            filepath = os.path.join(OUTPUT_DIR, filename)
            temp_path = os.path.join(OUTPUT_DIR, f'_temp_{i}.png')

            target_scroll = list_y_start + scroll_per_capture * i
            page.evaluate(f'window.scrollTo(0, {target_scroll})')
            page.wait_for_timeout(1000)

            page.screenshot(
                path=temp_path,
                clip={
                    'x': max(0, clip_x),
                    'y': 0,
                    'width': grid_width,
                    'height': capture_height,
                }
            )

            # Resize to reference dimensions
            img = Image.open(temp_path)
            img_resized = img.resize((target_w, target_h), Image.LANCZOS)
            img_resized.save(filepath)
            os.remove(temp_path)

            saved_files.append(filename)
            print(f'Captured: {filename} ({target_w}x{target_h})')

        browser.close()

    print(f'\n캡처 완료, Oliveyoung collection에 {len(saved_files)}장 저장됨')
    return saved_files


if __name__ == '__main__':
    main()
