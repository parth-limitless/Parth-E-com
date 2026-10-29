
import requests, json, re
API_KEY = 'NVDOI4LW1BWV9NPRJ9KF3L6X2R1Y2BA20914JVC908RT8A1S5Z4HHI4R6R4DZUIQA8O9EZJVLQWZAT3A'
store_url = 'https://www.meesho.com/SpiceNestImpexPrivatelimited'
params = {'api_key': API_KEY, 'url': store_url, 'render_js': 'true', 'wait': '4000', 'country_code': 'in', 'premium_proxy': 'true'}
r = requests.get('https://app.scrapingbee.com/api/v1/', params=params, timeout=60)
m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
if m:
    data = json.loads(m.group(1))
    init = data.get('props', {}).get('pageProps', {}).get('initialState', {})
    shop_info = init.get('shop', {}).get('shopInfo', {})
    print('Shop Info:', json.dumps(shop_info, indent=2)[:500])
    shop_listing = init.get('shopListing', {}).get('listing', {})
    print('Shop Listing keys:', list(shop_listing.keys()))
    catalogs = shop_listing.get('catalogs', []) or shop_listing.get('products', [])
    print('Total catalogs/products in shopListing:', len(catalogs))
    if catalogs:
        print('First item sample:', json.dumps(catalogs[0], indent=2)[:500])
