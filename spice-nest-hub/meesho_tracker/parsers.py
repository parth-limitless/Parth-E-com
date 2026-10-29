"""
Meesho Store Page & Product Page Parsers (Selectolax + BeautifulSoup Fallback)
=============================================================================
Extracts product cards, validates via Pydantic v2, and saves raw Gzip dumps.
"""

import gzip
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser

from meesho_tracker.config import load_selectors
from meesho_tracker.models import ProductRecord, RejectedRecord

logger = logging.getLogger("meesho_tracker.parsers")


class RawDumpManager:
    """Saves raw HTML and JSON payloads with gzip compression to ./raw/<date>/."""
    def __init__(self, raw_base_dir: str = "./raw", retention_days: int = 14):
        self.base_dir = Path(raw_base_dir)
        self.retention_days = retention_days

    def save_raw_dump(self, content: str, prefix: str = "store_discovery") -> Path:
        date_str = datetime.now().strftime("%Y-%m-%d")
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_dir = self.base_dir / date_str
        target_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = target_dir / f"{prefix}_{ts_str}.html.gz"
        with gzip.open(file_path, "wt", encoding="utf-8") as f:
            f.write(content)
        
        logger.info(f"Saved raw compressed dump to: {file_path}")
        self._prune_old_dumps()
        return file_path

    def save_raw_json(self, data: Any, prefix: str = "store_feed") -> Path:
        date_str = datetime.now().strftime("%Y-%m-%d")
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_dir = self.base_dir / date_str
        target_dir.mkdir(parents=True, exist_ok=True)

        file_path = target_dir / f"{prefix}_{ts_str}.json.gz"
        with gzip.open(file_path, "wt", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved raw compressed JSON to: {file_path}")
        self._prune_old_dumps()
        return file_path

    def _prune_old_dumps(self):
        try:
            if not self.base_dir.exists():
                return
            cutoff = datetime.now().timestamp() - (self.retention_days * 86400)
            for folder in self.base_dir.iterdir():
                if folder.is_dir() and folder.stat().st_mtime < cutoff:
                    for f in folder.iterdir():
                        f.unlink(missing_ok=True)
                    folder.rmdir()
        except Exception as e:
            logger.debug(f"Raw dumps cleanup note: {e}")


class MeeshoStoreParser:
    """Parses store listing HTML using Selectolax with BeautifulSoup fallback."""
    def __init__(self, selectors: Optional[Dict[str, Any]] = None):
        self.selectors = selectors or load_selectors()
        self.store_sel = self.selectors.get("store_page", {})

    def parse_store_page(
        self,
        html_content: str,
        run_type: str = "scheduled",
        captured_payloads: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[List[ProductRecord], List[RejectedRecord]]:
        valid_records: List[ProductRecord] = []
        rejected_records: List[RejectedRecord] = []

        if not html_content and not captured_payloads:
            return valid_records, rejected_records

        # 1. Primary parse via Selectolax (Lexbor)
        raw_items = self._parse_with_selectolax(html_content) if html_content else []

        # 2. Fallback to BeautifulSoup if Selectolax yielded no products
        if not raw_items and html_content:
            logger.warning("Selectolax found 0 cards. Triggering BeautifulSoup + lxml fallback...")
            raw_items = self._parse_with_beautifulsoup(html_content)

        # 3. Supplemental extraction from captured JSON responses (meri-shop/feed)
        if captured_payloads:
            feed_items = self._extract_from_feed_payload(captured_payloads)
            if feed_items:
                logger.info(f"Captured JSON feed yielded {len(feed_items)} enriched catalog items.")
                # Merge: index feed items by product_id
                feed_map = {item["product_id"]: item for item in feed_items}
                merged = []
                seen_feed_ids = set()
                for dom_item in raw_items:
                    pid = dom_item.get("product_id")
                    if pid in feed_map:
                        enriched = {**dom_item, **{k: v for k, v in feed_map[pid].items() if v is not None}}
                        merged.append(enriched)
                        seen_feed_ids.add(pid)
                    else:
                        merged.append(dom_item)
                # Add any feed items not seen in the current DOM slice
                for pid, fitem in feed_map.items():
                    if pid not in seen_feed_ids:
                        merged.append(fitem)
                raw_items = merged

        # 4. Also inspect __NEXT_DATA__ if present for supplemental data
        next_items = self._extract_from_next_data(html_content) if html_content else []
        if next_items and len(next_items) > len(raw_items):
            logger.info(f"__NEXT_DATA__ contained {len(next_items)} products (richer than DOM). Using Next.js payload.")
            raw_items = next_items

        # 4. Validate every row via Pydantic v2 ProductRecord
        seen_ids = set()
        for raw in raw_items:
            pid = raw.get("product_id")
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)

            raw["run_type"] = run_type
            raw["scraped_at"] = datetime.now()

            try:
                record = ProductRecord(**raw)
                valid_records.append(record)
            except Exception as val_err:
                rejected = RejectedRecord(
                    raw_data=raw,
                    reason=f"Validation failed: {val_err}"
                )
                rejected_records.append(rejected)

        return valid_records, rejected_records

    def _parse_with_selectolax(self, html: str) -> List[Dict[str, Any]]:
        items = []
        parser = LexborHTMLParser(html)
        card_sel = self.store_sel.get("product_card", "a[href*='/p/']")
        cards = parser.css(card_sel)

        for card in cards:
            href = card.attributes.get("href", "")
            if not href or "/p/" not in href:
                continue
            
            full_url = f"https://www.meesho.com{href}" if href.startswith("/") else href
            m_id = re.search(r'/p/([a-zA-Z0-9_-]+)', full_url)
            pid = m_id.group(1) if m_id else ""
            if not pid:
                continue

            text_lines = [l.strip() for l in card.text(separator="\n").split("\n") if l.strip()]
            name, price, mrp, disc, rating, reviews = self._extract_fields_from_lines(text_lines)

            img_node = card.css_first("img")
            img_url = img_node.attributes.get("src", "") if img_node else ""

            items.append({
                "product_id": pid,
                "name": name,
                "url": full_url,
                "price": price,
                "mrp": mrp,
                "discount_pct": disc,
                "rating": rating,
                "review_count": reviews,
                "image_url": img_url,
                "in_stock": True,
                "supplier": "Spice Nest Impex Private Limited"
            })
        return items

    def _parse_with_beautifulsoup(self, html: str) -> List[Dict[str, Any]]:
        items = []
        soup = BeautifulSoup(html, "lxml")
        card_sel = self.store_sel.get("product_card", "a[href*='/p/']")
        cards = soup.select(card_sel)

        for card in cards:
            href = card.get("href", "")
            if not href or "/p/" not in href:
                continue

            full_url = f"https://www.meesho.com{href}" if href.startswith("/") else href
            m_id = re.search(r'/p/([a-zA-Z0-9_-]+)', full_url)
            pid = m_id.group(1) if m_id else ""
            if not pid:
                continue

            text_lines = [l.strip() for l in card.get_text("\n").split("\n") if l.strip()]
            name, price, mrp, disc, rating, reviews = self._extract_fields_from_lines(text_lines)

            img_node = card.find("img")
            img_url = img_node.get("src", "") if img_node else ""

            items.append({
                "product_id": pid,
                "name": name,
                "url": full_url,
                "price": price,
                "mrp": mrp,
                "discount_pct": disc,
                "rating": rating,
                "review_count": reviews,
                "image_url": img_url,
                "in_stock": True,
                "supplier": "Spice Nest Impex Private Limited"
            })
        return items

    def _extract_from_feed_payload(self, payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        items = []
        for pl in payloads:
            catalogs = pl.get("catalogs", [])
            for c in catalogs:
                pid = str(c.get("product_id") or c.get("hero_pid") or c.get("id") or "")
                name = c.get("name") or c.get("hero_product_name") or ""
                price = c.get("min_product_price") or c.get("min_catalog_price") or 0.0
                mrp = c.get("original_price") or price
                disc = float(c.get("max_product_discount") or 0.0)
                reviews_summary = c.get("catalog_reviews_summary", {}) or {}
                rating_str = reviews_summary.get("average_rating_str") or reviews_summary.get("average_rating")
                rating = float(rating_str) if rating_str else None
                review_count = int(reviews_summary.get("rating_count") or reviews_summary.get("review_count") or 0)
                slug = c.get("slug") or ""
                url = f"https://www.meesho.com/{slug}/p/{pid}?ms=2" if slug else f"https://www.meesho.com/s/p/{pid}"
                img_url = c.get("image") or (c.get("images") or [""])[0] if isinstance(c.get("images"), list) else ""

                if pid and name and price:
                    items.append({
                        "product_id": pid,
                        "name": str(name).strip(),
                        "url": url,
                        "price": float(price),
                        "mrp": float(mrp),
                        "discount_pct": disc,
                        "rating": rating,
                        "review_count": review_count,
                        "image_url": img_url,
                        "in_stock": True,
                        "supplier": "Spice Nest Impex Private Limited",
                        "mall_verified": bool(c.get("mall_verified", False)),
                        "is_ad_product": bool(c.get("isAdProduct", False)),
                        "category_path": c.get("sub_sub_category_name"),
                        "description": c.get("description")
                    })
        return items

    def _extract_from_next_data(self, html: str) -> List[Dict[str, Any]]:
        items = []
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if not m:
            return items

        try:
            data = json.loads(m.group(1))
            init = data.get("props", {}).get("pageProps", {}).get("initialState", {})
            shop_listing = init.get("shopListing", {}).get("listing", {})
            products = shop_listing.get("products", []) or shop_listing.get("catalogs", [])

            for p in products:
                pid = str(p.get("id") or p.get("product_id") or "")
                name = p.get("name") or p.get("title")
                price = p.get("discounted_price") or p.get("price") or p.get("selling_price")
                mrp = p.get("original_price") or p.get("mrp")
                rating = p.get("rating") or p.get("average_rating")
                reviews = p.get("review_count") or p.get("rating_count")

                if pid and name and price:
                    items.append({
                        "product_id": pid,
                        "name": str(name).strip(),
                        "url": f"https://www.meesho.com/s/p/{pid}",
                        "price": float(price),
                        "mrp": float(mrp) if mrp else float(price),
                        "discount_pct": round(((float(mrp) - float(price)) / float(mrp) * 100), 1) if mrp and float(mrp) > float(price) else 0.0,
                        "rating": float(rating) if rating else None,
                        "review_count": int(reviews) if reviews else 0,
                        "image_url": (p.get("images") or [""])[0] if isinstance(p.get("images"), list) else "",
                        "in_stock": True,
                        "supplier": "Spice Nest Impex Private Limited"
                    })
        except Exception as e:
            logger.debug(f"__NEXT_DATA__ extraction exception: {e}")

        return items

    def _extract_fields_from_lines(self, lines: List[str]) -> Tuple[str, float, float, float, float, int]:
        name = ""
        price = 0.0
        mrp = 0.0
        disc = 0.0
        rating = 4.1
        reviews = 0

        for line in lines:
            line_str = line.strip()
            if not line_str or re.match(r'^\+\d+\s+More', line_str, re.I):
                continue

            # Price detection: '₹154'
            if "₹" in line_str:
                prices = re.findall(r'₹\s*([\d,]+)', line_str)
                if prices:
                    p1 = float(prices[0].replace(",", ""))
                    if not price:
                        price = p1
                    elif not mrp:
                        mrp = p1
                    if len(prices) > 1 and not mrp:
                        mrp = float(prices[1].replace(",", ""))

            # Discount detection: '34% off'
            elif "% off" in line_str.lower() or "off" in line_str.lower():
                m_disc = re.search(r'(\d+)\s*%', line_str)
                if m_disc:
                    disc = float(m_disc.group(1))

            # Review count: '1735 Reviews' or '1735 Ratings'
            elif "review" in line_str.lower() or "rating" in line_str.lower():
                m_rev = re.search(r'([\d,]+)\s*(?:Reviews?|Ratings?)', line_str, re.I)
                if m_rev:
                    try:
                        reviews = int(m_rev.group(1).replace(",", ""))
                    except Exception:
                        pass

            # Rating: standalone number e.g. '4.0' or '4.1 ★'
            elif re.match(r'^[1-5](\.\d+)?\s*★?$', line_str):
                try:
                    val = float(re.search(r'[1-5](\.\d+)?', line_str).group(0))
                    if 1.0 <= val <= 5.0:
                        rating = val
                except Exception:
                    pass

            # Skip supplier badge or delivery lines
            elif any(k in line_str.lower() for k in ["supplier", "free delivery", "delivery"]):
                continue

            # Product Name: first non-badge, non-price, non-discount descriptive string
            elif not name:
                name = line_str

        if not mrp and price and disc:
            mrp = round(price / (1 - (disc / 100)), 1)
        elif not mrp and price:
            mrp = price

        return name or "Spice Nest Product", price, mrp, disc, rating, reviews
