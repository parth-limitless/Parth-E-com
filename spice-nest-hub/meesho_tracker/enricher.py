"""
Meesho Tracker - Product Detail Page Enricher (Full Scan Mode)
==============================================================
Visits product pages sequentially with strict politeness limits:
- Powered by PlaywrightSession with honest browser configuration
- Dynamic waits, loading spinner detachment, and challenge detection
- Concurrency = 1
- Randomized delay 4.0 - 9.0 s between product pages
- Extra 20 - 40 s pause every 10 pages
- Maximum 80 page loads, max 20 min runtime
- Extracts application/ld+json and __NEXT_DATA__
- Integrated block detection and circuit breaker
"""

import asyncio
import json
import logging
import random
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from meesho_tracker.block_detector import BlockDetector, CircuitBreaker
from meesho_tracker.config import TrackerConfig, load_config, load_selectors
from meesho_tracker.models import ProductRecord
from meesho_tracker.playwright_engine import (
    ChallengeDetector,
    ManualInterventionHandler,
    PlaywrightSession,
    ResilientActions,
    TaskPacer,
)
from meesho_tracker.storage import TrackerStorage

logger = logging.getLogger("meesho_tracker.enricher")


class ProductPageEnricher:
    def __init__(
        self,
        config: Optional[TrackerConfig] = None,
        storage: Optional[TrackerStorage] = None,
        selectors: Optional[Dict[str, Any]] = None
    ):
        self.config = config or load_config()
        self.storage = storage or TrackerStorage(self.config.storage.db_path)
        self.selectors = selectors or load_selectors()
        self.block_detector = BlockDetector(selectors=self.selectors)
        self.circuit_breaker = CircuitBreaker(self.storage, self.config)

    def enrich_products(
        self,
        products: List[ProductRecord],
        run_id: str
    ) -> Tuple[List[ProductRecord], bool, Optional[str]]:
        """
        Synchronously runs the product enrichment crawler.
        Returns: (enriched_products: List[ProductRecord], partial: bool, error_msg: Optional[str])
        """
        return asyncio.run(self._enrich_products_async(products, run_id))

    async def _enrich_products_async(
        self,
        products: List[ProductRecord],
        run_id: str
    ) -> Tuple[List[ProductRecord], bool, Optional[str]]:
        logger.info(f"Starting resilient product enrichment for {len(products)} products [Run {run_id}]...")

        start_time = time.time()
        max_duration_sec = self.config.limits.max_run_duration_min * 60
        max_pages = min(len(products), self.config.limits.max_pages_per_run)

        enriched: List[ProductRecord] = []
        is_blocked = False
        block_reason = None

        pacer = TaskPacer(
            min_action_delay=self.config.limits.min_delay_product_sec,
            max_action_delay=self.config.limits.max_delay_product_sec,
            max_actions_per_minute=self.config.limits.max_requests_per_minute,
        )
        actions = ResilientActions(pacer=pacer)
        intervention_handler = ManualInterventionHandler(timeout_sec=120.0)

        # Persistent honest browser session across enrichment sequence
        async with PlaywrightSession(headless=True, filter_media=True) as session:
            page = await session.new_page()

            for idx, prod in enumerate(products[:max_pages], start=1):
                # Runtime limit guard
                elapsed = time.time() - start_time
                if elapsed >= max_duration_sec:
                    logger.warning(
                        f"Max run duration ({self.config.limits.max_run_duration_min} min) reached. Stopping enrichment."
                    )
                    enriched.extend(products[idx - 1:])
                    return enriched, True, "Max run duration reached"

                logger.info(f"Enriching [{idx}/{max_pages}]: {prod.name[:30]} ({prod.url})")

                extracted_data = None
                for attempt in range(1, self.config.limits.max_request_retries + 2):
                    attempt_blocked, attempt_reason, p_data = await self._visit_product_page_resilient(
                        page, prod.url, actions, intervention_handler
                    )

                    if not attempt_blocked:
                        extracted_data = p_data
                        break

                    logger.warning(f"Block/Challenge detected on {prod.url} (Attempt {attempt}): {attempt_reason}")

                    if attempt == 1 and self.config.limits.max_request_retries > 0:
                        wait_sec = random.uniform(60.0, 120.0)
                        logger.info(f"Waiting {wait_sec:.1f} s before single retry of blocked page...")
                        await asyncio.sleep(wait_sec)
                    else:
                        is_blocked = True
                        block_reason = attempt_reason
                        self.circuit_breaker.handle_block(run_id, reason=attempt_reason or "Product page block")
                        break

                if is_blocked:
                    logger.error(f"Run aborted due to security challenge: {block_reason}. Saving partial data.")
                    enriched.append(prod)
                    enriched.extend(products[idx:])
                    return enriched, True, block_reason

                if extracted_data:
                    prod.sku = extracted_data.get("sku") or prod.sku
                    prod.supplier = extracted_data.get("supplier") or prod.supplier
                    prod.is_ad_product = extracted_data.get("is_ad_product", prod.is_ad_product)
                    prod.mall_verified = extracted_data.get("mall_verified", prod.mall_verified)
                    prod.category_path = extracted_data.get("category_path") or prod.category_path
                    prod.description = extracted_data.get("description") or prod.description
                    if extracted_data.get("in_stock") is not None:
                        prod.in_stock = extracted_data["in_stock"]

                enriched.append(prod)

                # Politeness pacing
                if idx % self.config.limits.pause_every_n_pages == 0 and idx < max_pages:
                    pause_sec = random.uniform(
                        self.config.limits.pause_duration_min_sec,
                        self.config.limits.pause_duration_max_sec
                    )
                    logger.info(f"Batch checkpoint ({self.config.limits.pause_every_n_pages} pages). Politeness pause for {pause_sec:.1f} s...")
                    await asyncio.sleep(pause_sec)
                elif idx < max_pages:
                    delay_sec = random.uniform(
                        self.config.limits.min_delay_product_sec,
                        self.config.limits.max_delay_product_sec
                    )
                    await asyncio.sleep(delay_sec)

            # Persist session state after successful completion
            await session.save_session()

        return enriched, False, None

    async def _visit_product_page_resilient(
        self,
        page,
        url: str,
        actions: ResilientActions,
        intervention_handler: ManualInterventionHandler
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Visits a product page using dynamic waits and honest compliance.
        """
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=35000)
            status_code = response.status if response else 200

            # 1. Anti-bot Challenge Inspection
            is_challenged, challenge_reason = await ChallengeDetector.inspect_page(page)
            if is_challenged:
                logger.warning(f"Challenge encountered on PDP {url}: {challenge_reason}")
                resolved = await intervention_handler.wait_for_resolution(page, challenge_reason or "Challenge")
                if not resolved:
                    return True, challenge_reason, None

            # 2. Dynamic wait for loading indicators and dismiss unexpected modals
            await actions.wait_for_loading_complete(page)
            await actions.dismiss_modal_dialogs(page)

            html = await page.content()

            # 3. Block detector inspection
            blocked, reason = self.block_detector.check_response(status_code, html)
            if blocked:
                return True, reason, None

            # 4. Extract structured details
            parsed = self._parse_product_details(html)
            return False, None, parsed

        except Exception as e:
            logger.warning(f"Exception visiting product page {url}: {e}")
            return False, None, None

    def _parse_product_details(self, html: str) -> Dict[str, Any]:
        result = {}
        if not html:
            return result

        # 1. Parse application/ld+json
        ld_matches = re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S)
        for ld_text in ld_matches:
            try:
                data = json.loads(ld_text)
                if isinstance(data, dict) and data.get("@type") == "Product":
                    result["sku"] = data.get("sku")
                    result["description"] = data.get("description")
                    offers = data.get("offers", {})
                    if isinstance(offers, dict):
                        avail = offers.get("availability", "")
                        result["in_stock"] = "InStock" in avail
            except Exception:
                pass

        # 2. Parse __NEXT_DATA__
        m_next = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if m_next:
            try:
                data = json.loads(m_next.group(1))
                init = data.get("props", {}).get("pageProps", {}).get("initialState", {})
                product_state = init.get("product", {}).get("details", {})
                if product_state:
                    result["sku"] = result.get("sku") or product_state.get("sku")
                    result["supplier"] = product_state.get("supplier_name") or product_state.get("supplierHandle")
                    result["mall_verified"] = bool(product_state.get("mall_verified", False))
                    result["is_ad_product"] = bool(product_state.get("isAdProduct", False))
                    result["category_path"] = product_state.get("category_name")
                    if "in_stock" not in result and "in_stock" in product_state:
                        result["in_stock"] = bool(product_state["in_stock"])
            except Exception:
                pass

        return result
