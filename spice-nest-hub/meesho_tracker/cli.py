"""
Meesho Store Tracker - Standalone CLI Interface
===============================================
CLI flags:
  --mode [scheduled | live | full | dry-run | daemon | export-only | health]
  --force (allowed only once per 24 hours, never overrides active block cooldown)
  --url (custom store URL override)
"""

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from meesho_tracker.config import load_config
from meesho_tracker.runner import TrackerRunner
from meesho_tracker.scheduler import start_daemon


def setup_cli_logging(logs_dir_str: str = "./logs"):
    logs_dir = Path(logs_dir_str)
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "meesho_tracker.log"

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Console Handler (utf-8 safe)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)

    # Rotating File Handler (keep up to 5 files of 5MB each)
    file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)


def main():
    parser = argparse.ArgumentParser(description="Spice Nest - Meesho Public Store Tracker")
    parser.add_argument(
        "--mode",
        choices=["scheduled", "live", "full", "dry-run", "daemon", "export-only", "health"],
        default="scheduled",
        help="Execution mode (default: scheduled)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force execution (max once/24h, never overrides active block cooldown)"
    )
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="Override target store URL"
    )

    args = parser.parse_args()

    # Reconfigure stdout for utf-8 on Windows
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    config = load_config()
    setup_cli_logging(config.storage.logs_dir)

    logger = logging.getLogger("meesho_tracker.cli")
    logger.info(f"CLI invocation: mode={args.mode}, force={args.force}")

    if args.mode == "daemon":
        start_daemon()
        return

    runner = TrackerRunner(config=config)
    result = runner.run(mode=args.mode, force=args.force, store_url=args.url)

    if args.mode == "health":
        print("\n=== MEESHO TRACKER HEALTH DIAGNOSTICS ===")
        print(json.dumps(result, indent=2))
        return

    print("\n=== RUN EXECUTION RESULT ===")
    print(f"Status: {result.get('status')}")
    if result.get("reason"):
        print(f"Reason: {result.get('reason')}")
    if result.get("products_saved") is not None:
        print(f"Products Saved: {result.get('products_saved')}")
    if result.get("excel_path"):
        print(f"Excel Deliverable: {result.get('excel_path')}")


if __name__ == "__main__":
    main()

