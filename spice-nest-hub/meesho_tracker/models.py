"""
Pydantic v2 Models for Meesho Store Tracker
============================================
Validated schemas for records, run logs, configurations, and rejected data.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class ProductRecord(BaseModel):
    """Clean validated model representing a single product listing."""
    product_id: str = Field(..., description="Unique Meesho product ID from URL /p/<id>")
    name: str = Field(..., min_length=1, description="Product title / name")
    url: str = Field(..., description="Full URL to public product page")
    price: float = Field(..., ge=0.0, description="Selling price in INR")
    mrp: Optional[float] = Field(None, ge=0.0, description="Original MRP in INR")
    discount_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Discount percentage")
    rating: Optional[float] = Field(None, ge=0.0, le=5.0, description="Average star rating")
    review_count: Optional[int] = Field(None, ge=0, description="Total user reviews count")
    image_url: Optional[str] = Field(None, description="Primary product image URL")
    in_stock: bool = Field(True, description="Stock availability status")
    
    # Enrichment fields (from product page)
    sku: Optional[str] = None
    supplier: Optional[str] = None
    is_ad_product: Optional[bool] = False
    mall_verified: Optional[bool] = False
    category_path: Optional[str] = None
    description: Optional[str] = None

    # Meta
    run_type: str = Field("scheduled", description="Run mode: scheduled | live | full | dry-run")
    scraped_at: datetime = Field(default_factory=datetime.now)

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, v: Any) -> str:
        if v is None:
            raise ValueError("Product name cannot be None")
        cleaned = str(v).strip()
        if not cleaned:
            raise ValueError("Product name cannot be empty")
        return cleaned

    @field_validator("price", mode="before")
    @classmethod
    def clean_price(cls, v: Any) -> float:
        if v is None:
            raise ValueError("Price cannot be None")
        try:
            val = float(str(v).replace("₹", "").replace(",", "").strip())
            if val <= 0:
                raise ValueError("Price must be greater than 0")
            return val
        except Exception:
            raise ValueError(f"Invalid price value: {v}")


class RejectedRecord(BaseModel):
    """Holds unparseable or schema-violating rows for the Rejected sheet."""
    raw_data: Dict[str, Any]
    reason: str
    rejected_at: datetime = Field(default_factory=datetime.now)


class RunLogRecord(BaseModel):
    """Execution log model stored in SQLite and exported to Run_Log sheet."""
    run_id: str
    mode: str = "scheduled"
    run_type: Optional[str] = None
    status: str  # SUCCESS, BLOCKED, SUSPECT, PARTIAL, FAILED
    started_at: datetime
    finished_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_sec: Optional[float] = None
    elapsed_sec: Optional[float] = None
    products_found: int = 0
    products_valid: int = 0
    products_saved: int = 0
    products_rejected: int = 0
    partial: bool = False
    cooldown_until: Optional[datetime] = None
    error_message: Optional[str] = None
    notes: Optional[str] = ""

    def __init__(self, **data):
        if "run_type" in data and "mode" not in data:
            data["mode"] = data["run_type"]
        elif "mode" in data and "run_type" not in data:
            data["run_type"] = data["mode"]
        
        if "completed_at" in data and "finished_at" not in data:
            data["finished_at"] = data["completed_at"]
        elif "finished_at" in data and "completed_at" not in data:
            data["completed_at"] = data["finished_at"]

        if "elapsed_sec" in data and "duration_sec" not in data:
            data["duration_sec"] = data["elapsed_sec"]
        elif "duration_sec" in data and "elapsed_sec" not in data:
            data["elapsed_sec"] = data["duration_sec"]

        if "products_saved" in data and "products_valid" not in data:
            data["products_valid"] = data["products_saved"]
        elif "products_valid" in data and "products_saved" not in data:
            data["products_saved"] = data["products_valid"]

        if "error_message" in data and "notes" not in data:
            data["notes"] = data["error_message"]
        elif "notes" in data and "error_message" not in data:
            data["error_message"] = data["notes"]

        super().__init__(**data)


class TrackerState(BaseModel):
    """Internal SQLite persistent state tracking for the 24-hour rule & circuit breaker."""
    last_success_time: Optional[datetime] = None
    last_run_time: Optional[datetime] = None
    last_live_time: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None
    consecutive_blocks: int = 0
    force_used_at: Optional[datetime] = None


class ChangeRecord(BaseModel):
    """Record of delta changes compared against the previous snapshot."""
    run_id: Optional[str] = "manual_run"
    product_id: str
    name: str
    change_type: str  # PRICE_CHANGE, DISCOUNT_CHANGE, RATING_DROP, STOCK_CHANGE, NEW_PRODUCT, REMOVED_PRODUCT
    field_changed: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    pct_change: Optional[float] = None
    detected_at: datetime = Field(default_factory=datetime.now)

    def model_post_init(self, __context: Any) -> None:
        if not self.field_changed:
            self.field_changed = "price" if self.change_type == "PRICE_CHANGE" else (
                "in_stock" if self.change_type == "STOCK_CHANGE" else self.change_type.lower()
            )

