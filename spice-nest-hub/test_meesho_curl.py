import subprocess
import json
import re

url = "https://www.meesho.com/spice-nest-ginger-garlic-paste-750g-pure-adrak-lehsun-paste-no-preservatives-fresh-ginger-garlic-for-curries-biryani-indian-cooking-ready-to-use-jar/p/axi3yp?ms=2&source=Meri+Shop"

# Clean up URL: remove query parameters if needed or keep them
res = subprocess.run(["curl.exe", "-s", "-L", url], capture_output=True, text=True, encoding="utf-8", errors="ignore")
html = res.stdout

print(f"HTML Length: {len(html)}")

m_title = re.search(r'<title[^>]*>(.*?)</title>', html, re.I)
if m_title:
    print(f"Title: {m_title.group(1)}")

m_next = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
if m_next:
    try:
        data = json.loads(m_next.group(1))
        init = data.get("props", {}).get("pageProps", {}).get("initialState", {})
        details = init.get("product", {}).get("details", {})
        print("Details from __NEXT_DATA__:")
        print(f"  Name: {details.get('name')}")
        print(f"  Price: ₹{details.get('price')}")
        print(f"  MRP: ₹{details.get('mrp')}")
        print(f"  In Stock: {details.get('in_stock')}")
        print(f"  Supplier: {details.get('supplier_name')}")
        print(f"  Rating: {details.get('rating')}")
        print(f"  Review count: {details.get('review_count')}")
    except Exception as e:
        print("Error parsing __NEXT_DATA__:", e)

