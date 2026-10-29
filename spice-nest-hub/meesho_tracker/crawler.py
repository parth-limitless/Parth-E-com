"""
Crawlee PlaywrightCrawler for Meesho Store Discovery
====================================================
Uses real Chromium with honest settings, route aborts for media/fonts,
slow scrolling with randomized pauses, and raw Gzip dumping.
Explicitly disables browser-fingerprint spoofing and proxy rotation.
"""

import asyncio
import logging
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext

from meesho_tracker.config import TrackerConfig, load_config, load_selectors
from meesho_tracker.models import ProductRecord, RejectedRecord
from meesho_tracker.parsers import MeeshoStoreParser, RawDumpManager
from meesho_tracker.playwright_engine import (
    ChallengeDetector,
    IdempotencyGuard,
    ManualInterventionHandler,
    MeeshoLocators,
    ResilientActions,
    TaskPacer,
)

logger = logging.getLogger("meesho_tracker.crawler")


class StoreDiscoveryCrawler:
    def __init__(self, config: Optional[TrackerConfig] = None, selectors: Optional[Dict[str, Any]] = None):
        self.config = config or load_config()
        self.selectors = selectors or load_selectors()
        self.dump_manager = RawDumpManager(
            raw_base_dir=self.config.storage.raw_dir,
            retention_days=self.config.storage.raw_retention_days
        )
        self.parser = MeeshoStoreParser(selectors=self.selectors)

    def run_discovery(
        self,
        store_url: Optional[str] = None,
        run_type: str = "scheduled"
    ) -> Tuple[List[ProductRecord], List[RejectedRecord], Path, str]:
        """
        Synchronous wrapper around the async Crawlee discovery crawler.
        """
        target_url = store_url or self.config.store.url
        return asyncio.run(self._run_discovery_async(target_url, run_type))

    async def _run_discovery_async(
        self,
        target_url: str,
        run_type: str
    ) -> Tuple[List[ProductRecord], List[RejectedRecord], Path, str]:
        logger.info(f"Starting Crawlee Discovery on: {target_url} (run_type={run_type})")
        
        captured_html: List[str] = []
        captured_json_payloads: List[Dict[str, Any]] = []

        # Initialize Crawlee PlaywrightCrawler with strict safety settings
        # Explicitly disable fingerprint spoofing, proxy rotation, and session rotation on block
        crawler = PlaywrightCrawler(
            fingerprint_generator=None,
            use_session_pool=False,
            retry_on_blocked=False,
            proxy_configuration=None,
            max_requests_per_crawl=1,
            max_request_retries=self.config.limits.max_request_retries,
            headless=True,
            browser_new_context_options={"viewport": {"width": 1280, "height": 800}}
        )

        # 1. Route Filtering: Block images, media, and fonts
        @crawler.pre_navigation_hook
        async def before_navigation_hook(context: PlaywrightCrawlingContext):
            page = context.page

            # Intercept API responses for raw dump retention
            async def handle_response(response):
                if "meri-shop/feed" in response.url and response.status == 200:
                    try:
                        res_json = await response.json()
                        captured_json_payloads.append(res_json)
                        self.dump_manager.save_raw_json(res_json, prefix="store_feed")
                    except Exception as e:
                        logger.debug(f"Note on feed response interception: {e}")
            page.on("response", handle_response)

            async def handle_route(route):
                if route.request.resource_type in ["image", "media", "font"]:
                    await route.abort()
                else:
                    await route.continue_()
            await page.route("**/*", handle_route)

        # 2. Main Discovery Handler with dynamic waiting & realistic pacing
        pacer = TaskPacer(min_action_delay=0.4, max_action_delay=0.9)
        actions = ResilientActions(pacer=pacer)
        intervention_handler = ManualInterventionHandler(timeout_sec=120.0)

        @crawler.router.default_handler
        async def default_handler(context: PlaywrightCrawlingContext):
            page = context.page
            locators = MeeshoLocators(page)
            logger.info("Page loaded. Performing anti-bot inspection & dynamic wait...")

            # 1. Anti-bot Challenge Inspection
            is_challenged, challenge_reason = await ChallengeDetector.inspect_page(page)
            if is_challenged:
                logger.warning(f"Challenge detected on store page: {challenge_reason}")
                resolved = await intervention_handler.wait_for_resolution(page, challenge_reason or "Challenge")
                if not resolved:
                    raise RuntimeError(f"Manual intervention timed out: {challenge_reason}")

            # 2. Wait for loading indicators and dismiss unexpected promo modals
            await actions.wait_for_loading_complete(page)
            await actions.dismiss_modal_dialogs(page)

            prev_card_count = 0
            max_scrolls = 8

            for scroll_idx in range(1, max_scrolls + 1):
                # Count current product cards using accessibility-based semantic locator
                current_card_count = await locators.product_cards.count()
                logger.info(f"Scroll {scroll_idx}/{max_scrolls}: {current_card_count} product cards detected.")

                if scroll_idx > 2 and current_card_count == prev_card_count:
                    logger.info("Product card count stabilized. Ending scroll.")
                    break

                prev_card_count = current_card_count
                
                # Paced, smooth scrolling with request animation settlement
                await pacer.scroll_smoothly(page, delta_y=1000, steps=4)
                await actions.dismiss_modal_dialogs(page)

            html = await page.content()
            captured_html.append(html)

        # Execute crawl
        await crawler.run([target_url])

        final_html = captured_html[0] if captured_html else ""
        
        # Save raw compressed dump
        raw_dump_path = self.dump_manager.save_raw_dump(final_html, prefix="store_discovery")

        # Parse extracted page
        valid_records, rejected_records = self.parser.parse_store_page(
            final_html, 
            run_type=run_type,
            captured_payloads=captured_json_payloads
        )
        logger.info(f"Discovery parsing complete: {len(valid_records)} valid, {len(rejected_records)} rejected.")

        return valid_records, rejected_records, raw_dump_path, final_html
