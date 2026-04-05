"""
올리브영 랭킹 페이지 자동 캡처 + DOM 추출 통합 스크립트
Playwright chromium 사용.

사용법: python scripts/capture_oliveyoung.py

출력:
  스크린샷: Oliveyoung collection/oliveyoung_YYYYMMDD_1.png ~ 5.png
  DOM JSON: kbeauty-tracker/data/_dom_extract_YYYYMMDD.json

동일 페이지 세션에서 스크린샷과 DOM을 동시에 추출하여 시점 불일치 방지.
"""

from playwright.sync_api import sync_playwright
from datetime import datetime
import json
import os
import sys

URL = 'https://www.oliveyoung.co.kr/store/main/getBestList.do'

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'Oliveyoung collection')
ARCHIVE_DIR = os.path.join(OUTPUT_DIR, 'Archive')
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')

CAPTURE_COUNT = 5
ROWS_PER_CAPTURE = 3


def main():
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')

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

        # === DOM 추출 (스크린샷과 동일 시점) ===
        products = page.evaluate("""() => {
            var items = document.querySelectorAll('.cate_prd_list li');
            var results = [];
            items.forEach(function(item, idx) {
                if (idx >= 60) return;

                var link = item.querySelector('a');
                var href = link ? link.getAttribute('href') : '';
                var goodsNoMatch = href ? href.match(/goodsNo=([^&]+)/) : null;
                var goodsNo = goodsNoMatch ? goodsNoMatch[1] : '';

                var brandEl = item.querySelector('.tx_brand');
                var brand = brandEl ? brandEl.textContent.trim() : '';

                var nameEl = item.querySelector('.tx_name');
                var name = nameEl ? nameEl.textContent.trim() : '';

                var priceEl = item.querySelector('.tx_cur .tx_num');
                var price = priceEl ? priceEl.textContent.trim().replace(/,/g, '') : '';

                var orgPriceEl = item.querySelector('.tx_org .tx_num');
                var orgPrice = orgPriceEl ? orgPriceEl.textContent.trim().replace(/,/g, '') : '';

                var rankEl = item.querySelector('.num');
                var rankText = rankEl ? rankEl.textContent.trim() : '';

                var oteukEl = item.querySelector('.icon_flag.oteuk') ||
                              item.querySelector('.badge_oteuk') ||
                              item.querySelector('[class*="oteuk"]') ||
                              item.querySelector('[class*="todayDeal"]');
                var isOteuk = !!oteukEl;
                if (!isOteuk && rankEl) {
                    var rankClass = rankEl.className || '';
                    if (rankClass.includes('oteuk') || rankClass.includes('deal')) {
                        isOteuk = true;
                    }
                }
                var rankNum = parseInt(rankText);
                if (isNaN(rankNum) && rankText !== '') {
                    isOteuk = true;
                }

                results.push({
                    index: idx,
                    brand: brand,
                    name: name,
                    price: price,
                    original_price: orgPrice,
                    product_code: goodsNo,
                    rank_text: rankText,
                    is_oteuk: isOteuk,
                    url: href ? 'https://www.oliveyoung.co.kr' + href : ''
                });
            });
            return results;
        }""")

        dom_path = os.path.join(DATA_DIR, f'_dom_extract_{today}.json')
        with open(dom_path, 'w', encoding='utf-8') as f:
            json.dump(products, f, ensure_ascii=False, indent=2)
        print(f'[DOM] {len(products)}개 제품 추출 → {os.path.basename(dom_path)}')

        # === 스크린샷 캡처 (DOM 추출과 동일 페이지) ===
        # 스크롤로 전체 로딩 확보
        page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        page.wait_for_timeout(2000)
        page.evaluate('window.scrollTo(0, 0)')
        page.wait_for_timeout(1000)

        grid_info = page.evaluate("""() => {
            var items = document.querySelectorAll('.cate_prd_list li');
            if (items.length === 0) return null;
            var listEl = items[0].closest('ul');
            var listRect = listEl.getBoundingClientRect();

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

            start_row = i * ROWS_PER_CAPTURE
            if start_row >= len(rows):
                break

            y_start = rows[start_row]
            capture_height = row_height * ROWS_PER_CAPTURE + 20

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

    print(f'\n캡처+DOM 추출 완료: 스크린샷 {len(saved_files)}장, DOM {len(products)}개 제품')
    return saved_files


if __name__ == '__main__':
    main()
