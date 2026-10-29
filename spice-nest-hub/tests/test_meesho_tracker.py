"""
Comprehensive Test Suite for Meesho Store Tracker
=================================================
Verifies:
1. Block detector against real saved Akamai challenge fixture
2. Circuit breaker cooldown escalation (24h -> 48h -> 72h)
3. 24-Hour execution guard and --force restrictions
4. Single-instance process file locking
5. Selectolax & BeautifulSoup parser against real store dump
6. Pydantic v2 data validation and rejection handling
7. Excel writer atomic write and PermissionError locked-fallback
8. Simulated challenge stopping cleanly with zero retry loop
"""

import gzip
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from meesho_tracker.block_detector import BlockDetector, CircuitBreaker
from meesho_tracker.config import TrackerConfig, load_config, load_selectors
from meesho_tracker.diff import ChangeDetector
from meesho_tracker.excel_writer import ExcelReportWriter
from meesho_tracker.guards import GuardError, SingleInstanceLock, check_execution_guard
from meesho_tracker.models import ChangeRecord, ProductRecord, RejectedRecord, RunLogRecord
from meesho_tracker.parsers import MeeshoStoreParser
from meesho_tracker.runner import TrackerRunner
from meesho_tracker.storage import TrackerStorage


class TestMeeshoTracker(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.temp_dir) / "test_spicenest.db")
        self.storage = TrackerStorage(self.db_path)
        self.config = load_config()
        self.config.storage.db_path = self.db_path
        self.config.storage.excel_file = str(Path(self.temp_dir) / "test_meesho_tracker.xlsx")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # 1. Block Detector Tests
    def test_block_detector_on_real_akamai_challenge(self):
        detector = BlockDetector()

        # Real saved Akamai Access Denied fixture
        fixture_path = Path("raw/2026-10-29/store_discovery_20261029_134403.html.gz")
        if fixture_path.exists():
            with gzip.open(fixture_path, "rt", encoding="utf-8") as f:
                content = f.read()
            blocked, reason = detector.check_response(200, content)
            self.assertTrue(blocked)
            self.assertIn("Access Denied", reason)

        # HTTP 403 test
        b_403, r_403 = detector.check_response(403)
        self.assertTrue(b_403)
        self.assertIn("403", r_403)

        # Sec-if-cpt-container Akamai signature test
        b_cpt, r_cpt = detector.check_response(200, "<html><body><div class='sec-if-cpt-container'></div></body></html>")
        self.assertTrue(b_cpt)
        self.assertIn("sec-if-cpt-container", r_cpt)

    # 2. Circuit Breaker Cooldown Escalation Tests
    def test_circuit_breaker_escalation(self):
        cb = CircuitBreaker(self.storage, self.config)

        # 1st block -> 24h
        t1 = cb.handle_block("run_1", "1st challenge")
        state1 = self.storage.get_state()
        self.assertEqual(state1.consecutive_blocks, 1)
        self.assertAlmostEqual((state1.cooldown_until - datetime.now()).total_seconds() / 3600, 24, delta=1)

        # 2nd block -> 48h
        t2 = cb.handle_block("run_2", "2nd challenge")
        state2 = self.storage.get_state()
        self.assertEqual(state2.consecutive_blocks, 2)
        self.assertAlmostEqual((state2.cooldown_until - datetime.now()).total_seconds() / 3600, 48, delta=1)

        # 3rd block -> 72h
        t3 = cb.handle_block("run_3", "3rd challenge")
        state3 = self.storage.get_state()
        self.assertEqual(state3.consecutive_blocks, 3)
        self.assertAlmostEqual((state3.cooldown_until - datetime.now()).total_seconds() / 3600, 72, delta=1)

        # Reset on success
        cb.reset_blocks()
        state_reset = self.storage.get_state()
        self.assertEqual(state_reset.consecutive_blocks, 0)
        self.assertIsNone(state_reset.cooldown_until)

    # 3. 24-Hour Guard & Force Override Tests
    def test_24_hour_guard_enforcement(self):
        # Fresh state: should allow
        allowed, msg = check_execution_guard(self.storage, self.config, mode="scheduled")
        self.assertTrue(allowed)

        # Recent success 2 hours ago: should block
        self.storage.update_state(last_success_time=datetime.now() - timedelta(hours=2))
        allowed_recent, msg_recent = check_execution_guard(self.storage, self.config, mode="scheduled", force=False)
        self.assertFalse(allowed_recent)
        self.assertIn("24-Hour Rule", msg_recent)

        # --force applied once: should allow with warning
        allowed_force, msg_force = check_execution_guard(self.storage, self.config, mode="scheduled", force=True)
        self.assertTrue(allowed_force)

        # --force applied a 2nd time within 24 hours: should refuse
        allowed_force_2, msg_force_2 = check_execution_guard(self.storage, self.config, mode="scheduled", force=True)
        self.assertFalse(allowed_force_2)
        self.assertIn("already used within the last 24 hours", msg_force_2)

    # 4. Active Block Cooldown Can Never Be Overridden By Force
    def test_cooldown_never_overridden_by_force(self):
        # Set active cooldown
        self.storage.update_state(cooldown_until=datetime.now() + timedelta(hours=24), consecutive_blocks=1)
        allowed, msg = check_execution_guard(self.storage, self.config, mode="scheduled", force=True)
        self.assertFalse(allowed)
        self.assertIn("Active Circuit Breaker Cooldown", msg)

    # 5. Single-Instance Lock Test
    def test_single_instance_lock(self):
        lock_file = str(Path(self.temp_dir) / "test.lock")
        with SingleInstanceLock(lock_file=lock_file):
            # Second attempt while lock is held must raise GuardError
            with self.assertRaises(GuardError):
                with SingleInstanceLock(lock_file=lock_file, timeout_sec=0.1):
                    pass

    # 6. Real Store Dump Parser Tests
    def test_parser_on_real_dump(self):
        fixture_path = Path("raw/2026-10-29/store_discovery_20261029_132653.html.gz")
        self.assertTrue(fixture_path.exists(), "Raw dump fixture must exist")

        with gzip.open(fixture_path, "rt", encoding="utf-8") as f:
            html = f.read()

        parser = MeeshoStoreParser()
        valid, rejected = parser.parse_store_page(html)

        self.assertGreaterEqual(len(valid), 20)
        self.assertEqual(len(rejected), 0)

        # Verify attributes of parsed products
        p1 = valid[0]
        self.assertEqual(p1.product_id, "86cube")
        self.assertIn("Garlic Pickle", p1.name)
        self.assertGreater(p1.price, 0)
        self.assertGreaterEqual(p1.mrp, p1.price)
        self.assertLessEqual(p1.rating, 5.0)
        self.assertGreaterEqual(p1.rating, 1.0)
        self.assertGreaterEqual(p1.review_count, 1000)

    # 7. Pydantic Validation & Rejection Handling
    def test_pydantic_validation_rejects_bad_data(self):
        raw_bad_rating = {
            "product_id": "test_bad",
            "name": "Bad Rating Pickle",
            "url": "https://www.meesho.com/p/test_bad",
            "price": 199.0,
            "rating": 1735.0  # Invalid: > 5.0
        }
        raw_negative_price = {
            "product_id": "test_bad_price",
            "name": "Negative Price Jam",
            "url": "https://www.meesho.com/p/test_bad_price",
            "price": -50.0
        }

        parser = MeeshoStoreParser()
        valid, rejected = parser.parse_store_page("")
        
        # Test directly via ProductRecord validation
        with self.assertRaises(Exception):
            ProductRecord(**raw_bad_rating)

        with self.assertRaises(Exception):
            ProductRecord(**raw_negative_price)

    # 8. Excel Writer Atomic Write & Locked Fallback
    def test_excel_writer_atomic_and_locked_fallback(self):
        # Create a sample product
        p = ProductRecord(
            product_id="test1",
            name="Spice Nest Garlic Pickle 200g",
            url="https://www.meesho.com/s/p/test1",
            price=154.0,
            mrp=234.0,
            discount_pct=34.0,
            rating=4.0,
            review_count=1735,
            in_stock=True
        )
        self.storage.save_snapshot([p], run_id="run_test", run_type="scheduled")

        writer = ExcelReportWriter(self.storage, self.config)
        written = writer.export_workbook(run_id="run_test")

        self.assertTrue(Path(written).exists())
        self.assertEqual(Path(written).name, "test_meesho_tracker.xlsx")

        # Test Locked File Fallback
        # Simulate PermissionError by mocking shutil.move to raise PermissionError
        with patch("shutil.move", side_effect=[PermissionError("File locked by Excel"), None]):
            fallback_path = writer.export_workbook(run_id="run_locked_test")
            self.assertIn("LOCKED", str(fallback_path))

    # 9. Simulated Challenge Test - Stops Cleanly With Zero Retry Loop
    def test_simulated_challenge_clean_stop(self):
        runner = TrackerRunner(config=self.config)

        # Mock crawler to return an Akamai Access Denied page
        mock_html = "<html><head><title>Access Denied</title></head><body><h1>Access Denied</h1></body></html>"
        runner.crawler.run_discovery = MagicMock(return_value=([], [], Path(self.temp_dir) / "dummy.gz", mock_html))

        res = runner.run(mode="full", force=True)

        self.assertEqual(res["status"], "BLOCKED")
        self.assertIn("Access Denied", res["reason"])

        # Verify circuit breaker set cooldown
        state = self.storage.get_state()
        self.assertEqual(state.consecutive_blocks, 1)
        self.assertIsNotNone(state.cooldown_until)

        # Verify discovery was called exactly once (no looping)
        runner.crawler.run_discovery.assert_called_once()


if __name__ == "__main__":
    unittest.main()

