"""올리브영 랭킹 페이지 DOM에서 제품 데이터 추출."""
from playwright.sync_api import sync_playwright
import json
import os
import sys

URL = 'https://www.oliveyoung.co.kr/store/main/getBestList.do'
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1400, 'height': 900},
            locale='ko-KR',
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        )
        page = context.new_page()
        page.goto(URL, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(5000)
        page.wait_for_selector('.prd_info', timeout=30000)

        # Close popups
        try:
            page.click('.btnClose', timeout=3000)
        except Exception:
            pass

        # Extract product data from DOM
        products = page.evaluate("""() => {
            var items = document.querySelectorAll('.cate_prd_list li');
            var results = [];
            items.forEach(function(item, idx) {
                if (idx >= 60) return;

                var link = item.querySelector('a');
                var href = link ? link.getAttribute('href') : '';

                // Extract goodsNo from href
                var goodsNoMatch = href ? href.match(/goodsNo=([^&]+)/) : null;
                var goodsNo = goodsNoMatch ? goodsNoMatch[1] : '';

                // Brand
                var brandEl = item.querySelector('.tx_brand');
                var brand = brandEl ? brandEl.textContent.trim() : '';

                // Product name
                var nameEl = item.querySelector('.tx_name');
                var name = nameEl ? nameEl.textContent.trim() : '';

                // Price
                var priceEl = item.querySelector('.tx_cur .tx_num');
                var price = priceEl ? priceEl.textContent.trim().replace(/,/g, '') : '';

                // Original price
                var orgPriceEl = item.querySelector('.tx_org .tx_num');
                var orgPrice = orgPriceEl ? orgPriceEl.textContent.trim().replace(/,/g, '') : '';

                // Rank number - check if it has a rank badge
                var rankEl = item.querySelector('.num');
                var rankText = rankEl ? rankEl.textContent.trim() : '';

                // Check for 오특 (today's special deal)
                // 오특 products have a special badge instead of rank number
                var oteukEl = item.querySelector('.icon_flag.oteuk') ||
                              item.querySelector('.badge_oteuk') ||
                              item.querySelector('[class*="oteuk"]') ||
                              item.querySelector('[class*="todayDeal"]');
                var isOteuk = !!oteukEl;

                // Also check if the rank badge has special styling
                if (!isOteuk && rankEl) {
                    var rankClass = rankEl.className || '';
                    if (rankClass.includes('oteuk') || rankClass.includes('deal')) {
                        isOteuk = true;
                    }
                }

                // Check rank text - if empty or contains non-number, might be 오특
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

        browser.close()

    # Output as JSON
    output = json.dumps(products, ensure_ascii=False, indent=2)
    sys.stdout.reconfigure(encoding='utf-8')
    print(output)

    # Save to file
    from datetime import datetime
    today = datetime.now().strftime('%Y%m%d')
    out_path = os.path.join(DATA_DIR, f'_dom_extract_{today}.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(output)
    print(f'\nSaved to {out_path}', file=sys.stderr)

if __name__ == '__main__':
    main()
