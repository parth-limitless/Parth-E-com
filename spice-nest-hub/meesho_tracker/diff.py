"""
Meesho Tracker - Change Detection & Diff Engine
===============================================
Compares the current snapshot against the previous snapshot in SQLite.
Detects:
- Price changes
- Discount changes
- Rating drop >= 0.1
- Review count deltas
- Stock status changes
- New or removed products
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from meesho_tracker.models import ChangeRecord, ProductRecord
from meesho_tracker.storage import TrackerStorage

logger = logging.getLogger("meesho_tracker.diff")


class ChangeDetector:
    def __init__(self, storage: TrackerStorage, rating_drop_threshold: float = 0.1):
        self.storage = storage
        self.rating_drop_threshold = rating_drop_threshold

    def compute_changes(
        self,
        current_products: List[ProductRecord],
        run_id: str
    ) -> List[ChangeRecord]:
        """
        Compares current_products against the most recent snapshot in SQLite.
        Returns a list of ChangeRecord instances ready to be saved.
        """
        previous_products = self.storage.get_latest_products()
        prev_map: Dict[str, ProductRecord] = {p.product_id: p for p in previous_products}
        curr_map: Dict[str, ProductRecord] = {p.product_id: p for p in current_products}

        changes: List[ChangeRecord] = []
        now = datetime.now()

        # 1. Detect new products and modified products
        for pid, curr in curr_map.items():
            if pid not in prev_map:
                changes.append(ChangeRecord(
                    run_id=run_id,
                    product_id=pid,
                    name=curr.name,
                    change_type="NEW_PRODUCT",
                    old_value=None,
                    new_value=curr.name,
                    detected_at=now
                ))
                continue

            prev = prev_map[pid]

            # Price change
            if curr.price is not None and prev.price is not None and round(curr.price, 2) != round(prev.price, 2):
                pct = round(((curr.price - prev.price) / prev.price) * 100, 1) if prev.price else 0.0
                changes.append(ChangeRecord(
                    run_id=run_id,
                    product_id=pid,
                    name=curr.name,
                    change_type="PRICE_CHANGE",
                    old_value=str(prev.price),
                    new_value=str(curr.price),
                    pct_change=pct,
                    detected_at=now
                ))

            # Discount change
            if curr.discount_pct is not None and prev.discount_pct is not None and round(curr.discount_pct, 1) != round(prev.discount_pct, 1):
                changes.append(ChangeRecord(
                    run_id=run_id,
                    product_id=pid,
                    name=curr.name,
                    change_type="DISCOUNT_CHANGE",
                    old_value=str(prev.discount_pct),
                    new_value=str(curr.discount_pct),
                    detected_at=now
                ))

            # Rating drop >= threshold
            if curr.rating is not None and prev.rating is not None:
                drop = round(prev.rating - curr.rating, 2)
                if drop >= self.rating_drop_threshold:
                    changes.append(ChangeRecord(
                        run_id=run_id,
                        product_id=pid,
                        name=curr.name,
                        change_type="RATING_DROP",
                        old_value=str(prev.rating),
                        new_value=str(curr.rating),
                        detected_at=now
                    ))

            # Review count delta
            if curr.review_count is not None and prev.review_count is not None and curr.review_count != prev.review_count:
                changes.append(ChangeRecord(
                    run_id=run_id,
                    product_id=pid,
                    name=curr.name,
                    change_type="REVIEW_COUNT_DELTA",
                    old_value=str(prev.review_count),
                    new_value=str(curr.review_count),
                    detected_at=now
                ))

            # Stock status change
            if curr.in_stock != prev.in_stock:
                changes.append(ChangeRecord(
                    run_id=run_id,
                    product_id=pid,
                    name=curr.name,
                    change_type="STOCK_CHANGE",
                    old_value=str(prev.in_stock),
                    new_value=str(curr.in_stock),
                    detected_at=now
                ))

        # 2. Detect removed products
        for pid, prev in prev_map.items():
            if pid not in curr_map:
                changes.append(ChangeRecord(
                    run_id=run_id,
                    product_id=pid,
                    name=prev.name,
                    change_type="REMOVED_PRODUCT",
                    old_value=prev.name,
                    new_value=None,
                    detected_at=now
                ))

        logger.info(f"Diff computation complete for Run {run_id}: {len(changes)} changes detected.")
        return changes

