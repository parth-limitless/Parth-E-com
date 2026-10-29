"""
Configuration Loader & Pydantic v2 Validator
=============================================
Loads and validates config.yaml and selectors.yaml with clear error messages.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional
import yaml
from pydantic import BaseModel, Field

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = MODULE_DIR.parent
DEFAULT_CONFIG_PATH = MODULE_DIR / "config.yaml"
DEFAULT_SELECTORS_PATH = MODULE_DIR / "selectors.yaml"


class StoreConfig(BaseModel):
    name: str = "Spice Nest Impex Private Limited"
    url: str = "https://www.meesho.com/SpiceNestImpexPrivateLimited?ms=2"
    expected_product_count: int = 51
    batch_size: int = 20


class LimitsConfig(BaseModel):
    concurrency: int = Field(1, le=1)
    max_requests_per_minute: int = Field(8, le=15)
    min_delay_product_sec: float = 4.0
    max_delay_product_sec: float = 9.0
    pause_every_n_pages: int = 10
    pause_duration_min_sec: float = 20.0
    pause_duration_max_sec: float = 40.0
    max_pages_per_run: int = 80
    max_run_duration_min: int = 20
    max_request_retries: int = 1


class CircuitBreakerConfig(BaseModel):
    cooldown_base_hours: int = 24
    cooldown_2nd_hours: int = 48
    cooldown_3rd_hours: int = 72
    retry_after_block_wait_sec: int = 60


class GuardsConfig(BaseModel):
    min_hours_between_full_scans: int = 24
    min_minutes_between_live_scans: int = 30
    schema_drift_drop_pct_threshold: float = 30.0
    empty_fields_threshold_pct: float = 20.0


class StorageConfig(BaseModel):
    db_path: str = "spicenest.db"
    raw_dir: str = "./raw"
    output_dir: str = "./output"
    logs_dir: str = "./logs"
    excel_file: str = "./output/meesho_store_tracker.xlsx"
    raw_retention_days: int = 14
    history_warning_row_count: int = 100000


class AlertsConfig(BaseModel):
    telegram_enabled: bool = False
    price_change_alert_threshold_pct: float = 10.0
    rating_drop_alert_threshold: float = 0.1


class TrackerConfig(BaseModel):
    store: StoreConfig = StoreConfig()
    limits: LimitsConfig = LimitsConfig()
    circuit_breaker: CircuitBreakerConfig = CircuitBreakerConfig()
    guards: GuardsConfig = GuardsConfig()
    storage: StorageConfig = StorageConfig()
    alerts: AlertsConfig = AlertsConfig()


def load_config(config_path: Optional[Path] = None) -> TrackerConfig:
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return TrackerConfig()
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return TrackerConfig(**data)


def load_selectors(selectors_path: Optional[Path] = None) -> Dict[str, Any]:
    path = selectors_path or DEFAULT_SELECTORS_PATH
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

