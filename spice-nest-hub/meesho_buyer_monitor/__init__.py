"""
Meesho Buyer Monitor Package
============================
Enterprise-grade 24-hour buyer-side price monitoring engine powered by Playwright.
Supports product identification without direct links, accurate multi-component
price extraction, persistent background scheduling in Asia/Kolkata timezone,
and historical observation auditing.
"""

from meesho_buyer_monitor.db import (
    init_buyer_monitor_db,
    add_monitored_product,
    confirm_product_match,
    toggle_product_monitoring,
    delete_monitored_product,
    get_monitored_products,
    get_product_observations_history,
    record_price_observation,
    get_scheduler_status,
    get_now_ist_str,
    IST_TZ
)
from meesho_buyer_monitor.searcher import (
    search_meesho_candidates,
    calculate_match_score
)
from meesho_buyer_monitor.collector import (
    collect_single_product_price
)
from meesho_buyer_monitor.scheduler import (
    start_background_scheduler,
    stop_background_scheduler,
    run_monitoring_cycle,
    trigger_manual_check
)
from meesho_buyer_monitor.exporter import (
    export_buyer_monitor_csv,
    export_observations_history_csv
)

__all__ = [
    "init_buyer_monitor_db",
    "add_monitored_product",
    "confirm_product_match",
    "toggle_product_monitoring",
    "delete_monitored_product",
    "get_monitored_products",
    "get_product_observations_history",
    "record_price_observation",
    "get_scheduler_status",
    "get_now_ist_str",
    "IST_TZ",
    "search_meesho_candidates",
    "calculate_match_score",
    "collect_single_product_price",
    "start_background_scheduler",
    "stop_background_scheduler",
    "run_monitoring_cycle",
    "trigger_manual_check",
    "export_buyer_monitor_csv",
    "export_observations_history_csv"
]
