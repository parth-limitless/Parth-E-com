"""
SQLite Persistent Storage for Meesho Store Tracker
===================================================
Internal source of truth for snapshots, historical deltas, state, and run logs.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from meesho_tracker.models import ChangeRecord, ProductRecord, RejectedRecord, RunLogRecord, TrackerState


class TrackerStorage:
    def __init__(self, db_path: str = "spicenest.db"):
        self.db_path = db_path
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self._get_connection() as conn:
            # 1. Snapshots Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS meesho_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    url TEXT,
                    price REAL NOT NULL,
                    mrp REAL,
                    discount_pct REAL,
                    rating REAL,
                    review_count INTEGER,
                    image_url TEXT,
                    in_stock INTEGER DEFAULT 1,
                    sku TEXT,
                    supplier TEXT,
                    category_path TEXT,
                    description TEXT,
                    is_ad_product INTEGER DEFAULT 0,
                    mall_verified INTEGER DEFAULT 0,
                    run_id TEXT NOT NULL,
                    run_type TEXT NOT NULL,
                    scraped_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_m_snap_pid ON meesho_snapshots(product_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_m_snap_run ON meesho_snapshots(run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_m_snap_date ON meesho_snapshots(scraped_at)")

            # 2. Run Log Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS meesho_run_logs (
                    run_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    duration_sec REAL,
                    products_found INTEGER DEFAULT 0,
                    products_valid INTEGER DEFAULT 0,
                    products_rejected INTEGER DEFAULT 0,
                    cooldown_until TEXT,
                    notes TEXT
                )
            """)

            # 3. Singleton Tracker State (for 24h rule & circuit breaker)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS meesho_tracker_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_success_time TEXT,
                    last_run_time TEXT,
                    last_live_time TEXT,
                    cooldown_until TEXT,
                    consecutive_blocks INTEGER DEFAULT 0,
                    force_used_at TEXT
                )
            """)
            conn.execute("""
                INSERT OR IGNORE INTO meesho_tracker_state (id, consecutive_blocks)
                VALUES (1, 0)
            """)

            # 4. Changes Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS meesho_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    product_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    change_type TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    pct_change REAL,
                    detected_at TEXT NOT NULL
                )
            """)

            # 5. Rejected Rows Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS meesho_rejected (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    raw_data TEXT,
                    reason TEXT,
                    rejected_at TEXT NOT NULL
                )
            """)

            conn.commit()

    def get_state(self) -> TrackerState:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM meesho_tracker_state WHERE id = 1").fetchone()
            if not row:
                return TrackerState()
            
            def parse_dt(v):
                if v:
                    try: return datetime.fromisoformat(v)
                    except Exception: pass
                return None

            return TrackerState(
                last_success_time=parse_dt(row["last_success_time"]),
                last_run_time=parse_dt(row["last_run_time"]),
                last_live_time=parse_dt(row["last_live_time"]),
                cooldown_until=parse_dt(row["cooldown_until"]),
                consecutive_blocks=row["consecutive_blocks"] or 0,
                force_used_at=parse_dt(row["force_used_at"])
            )

    def update_state(
        self,
        last_success_time: Optional[datetime] = None,
        last_run_time: Optional[datetime] = None,
        last_live_time: Optional[datetime] = None,
        cooldown_until: Optional[datetime] = None,
        consecutive_blocks: Optional[int] = None,
        force_used_at: Optional[datetime] = None,
        reset_blocks: bool = False
    ):
        with self._get_connection() as conn:
            cur_state = self.get_state()
            
            succ = (last_success_time.isoformat() if last_success_time 
                    else (cur_state.last_success_time.isoformat() if cur_state.last_success_time else None))
            run = (last_run_time.isoformat() if last_run_time 
                   else (cur_state.last_run_time.isoformat() if cur_state.last_run_time else None))
            live = (last_live_time.isoformat() if last_live_time 
                    else (cur_state.last_live_time.isoformat() if cur_state.last_live_time else None))
            if reset_blocks or cooldown_until == "CLEAR":
                cool = None
            elif cooldown_until is not None:
                cool = cooldown_until.isoformat()
            else:
                cool = cur_state.cooldown_until.isoformat() if cur_state.cooldown_until else None
            blocks = 0 if reset_blocks else (consecutive_blocks if consecutive_blocks is not None else cur_state.consecutive_blocks)
            force = (force_used_at.isoformat() if force_used_at 
                     else (cur_state.force_used_at.isoformat() if cur_state.force_used_at else None))

            conn.execute("""
                UPDATE meesho_tracker_state SET
                    last_success_time = ?,
                    last_run_time = ?,
                    last_live_time = ?,
                    cooldown_until = ?,
                    consecutive_blocks = ?,
                    force_used_at = ?
                WHERE id = 1
            """, (succ, run, live, cool, blocks, force))
            conn.commit()

    def save_snapshot(self, records: List[ProductRecord], run_id: Optional[str] = None, run_type: Optional[str] = None):
        with self._get_connection() as conn:
            from datetime import datetime
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for r in records:
                rid = run_id or getattr(r, "run_id", "manual_run")
                rtype = run_type or r.run_type
                conn.execute("""
                    INSERT INTO meesho_snapshots (
                        product_id, name, url, price, mrp, discount_pct, rating, review_count,
                        image_url, in_stock, sku, supplier, category_path, description,
                        is_ad_product, mall_verified, run_id, run_type, scraped_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    r.product_id, r.name, r.url, r.price, r.mrp, r.discount_pct, r.rating, r.review_count,
                    r.image_url, 1 if r.in_stock else 0, r.sku, r.supplier, r.category_path, r.description,
                    1 if r.is_ad_product else 0, 1 if r.mall_verified else 0, rid, rtype, r.scraped_at.isoformat()
                ))

                # Upsert into meesho_catalog
                conn.execute("""
                    INSERT INTO meesho_catalog (product_id, title, price, product_url, image_url, status, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
                    ON CONFLICT(product_id) DO UPDATE SET
                        title=excluded.title,
                        price=excluded.price,
                        product_url=excluded.product_url,
                        image_url=excluded.image_url,
                        status='ACTIVE',
                        last_seen=excluded.last_seen,
                        deactivated_at=NULL
                """, (r.product_id, r.name, r.price, r.url, r.image_url or "", now_str, now_str))

                # Upsert into meesho_public_catalog
                conn.execute("""
                    INSERT INTO meesho_public_catalog 
                    (product_id, name, price, mrp, supplier_name, rating, review_count, in_stock, image_url, product_url, data_source, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'store_discovery', CURRENT_TIMESTAMP)
                    ON CONFLICT(product_id) DO UPDATE SET
                        name=excluded.name,
                        price=excluded.price,
                        mrp=excluded.mrp,
                        supplier_name=excluded.supplier_name,
                        rating=excluded.rating,
                        review_count=excluded.review_count,
                        in_stock=excluded.in_stock,
                        image_url=excluded.image_url,
                        product_url=excluded.product_url,
                        data_source=excluded.data_source,
                        updated_at=CURRENT_TIMESTAMP
                """, (
                    r.product_id, r.name, r.price, r.mrp or r.price,
                    r.supplier or "Spice Nest Impex Private Limited",
                    r.rating or 4.1, r.review_count or 100,
                    1 if r.in_stock else 0, r.image_url or "", r.url
                ))
            conn.commit()

    def get_latest_snapshot(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            # Find latest successful run_id
            latest_run = conn.execute("""
                SELECT run_id FROM meesho_run_logs 
                WHERE status IN ('SUCCESS', 'SUSPECT') 
                ORDER BY started_at DESC LIMIT 1
            """).fetchone()
            if not latest_run:
                # Fallback to absolute latest snapshot run_id
                r = conn.execute("SELECT run_id FROM meesho_snapshots ORDER BY scraped_at DESC LIMIT 1").fetchone()
                if not r:
                    return []
                run_id = r["run_id"]
            else:
                run_id = latest_run["run_id"]

            rows = conn.execute("""
                SELECT * FROM meesho_snapshots WHERE run_id = ? ORDER BY price DESC
            """, (run_id,)).fetchall()
            return [dict(row) for row in rows]

    def get_latest_products(self) -> List[ProductRecord]:
        rows = self.get_latest_snapshot()
        prods = []
        for r in rows:
            try:
                scraped_at = datetime.fromisoformat(r["scraped_at"]) if isinstance(r.get("scraped_at"), str) else (r.get("scraped_at") or datetime.now())
                p = ProductRecord(
                    product_id=r["product_id"],
                    name=r["name"],
                    url=r.get("url") or f"https://www.meesho.com/s/p/{r['product_id']}",
                    price=float(r["price"]),
                    mrp=float(r["mrp"]) if r.get("mrp") is not None else None,
                    discount_pct=float(r["discount_pct"]) if r.get("discount_pct") is not None else None,
                    rating=float(r["rating"]) if r.get("rating") is not None else None,
                    review_count=int(r["review_count"]) if r.get("review_count") is not None else None,
                    image_url=r.get("image_url"),
                    in_stock=bool(r.get("in_stock", 1)),
                    sku=r.get("sku"),
                    supplier=r.get("supplier"),
                    category_path=r.get("category_path"),
                    description=r.get("description"),
                    is_ad_product=bool(r.get("is_ad_product", 0)),
                    mall_verified=bool(r.get("mall_verified", 0)),
                    run_type=r.get("run_type", "scheduled"),
                    scraped_at=scraped_at
                )
                prods.append(p)
            except Exception:
                pass
        return prods

    def get_history(self, limit: int = 5000) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM meesho_snapshots ORDER BY scraped_at DESC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(row) for row in rows]

    def get_history_products(self, limit: int = 100000) -> List[ProductRecord]:
        rows = self.get_history(limit=limit)
        prods = []
        for r in rows:
            try:
                scraped_at = datetime.fromisoformat(r["scraped_at"]) if isinstance(r.get("scraped_at"), str) else (r.get("scraped_at") or datetime.now())
                p = ProductRecord(
                    product_id=r["product_id"],
                    name=r["name"],
                    url=r.get("url") or f"https://www.meesho.com/s/p/{r['product_id']}",
                    price=float(r["price"]),
                    mrp=float(r["mrp"]) if r.get("mrp") is not None else None,
                    discount_pct=float(r["discount_pct"]) if r.get("discount_pct") is not None else None,
                    rating=float(r["rating"]) if r.get("rating") is not None else None,
                    review_count=int(r["review_count"]) if r.get("review_count") is not None else None,
                    image_url=r.get("image_url"),
                    in_stock=bool(r.get("in_stock", 1)),
                    sku=r.get("sku"),
                    supplier=r.get("supplier"),
                    category_path=r.get("category_path"),
                    description=r.get("description"),
                    is_ad_product=bool(r.get("is_ad_product", 0)),
                    mall_verified=bool(r.get("mall_verified", 0)),
                    run_type=r.get("run_type", "scheduled"),
                    scraped_at=scraped_at
                )
                prods.append(p)
            except Exception:
                pass
        return prods

    def save_run_log(self, log: RunLogRecord):
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO meesho_run_logs (
                    run_id, mode, status, started_at, finished_at, duration_sec,
                    products_found, products_valid, products_rejected, cooldown_until, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    finished_at=excluded.finished_at,
                    duration_sec=excluded.duration_sec,
                    products_found=excluded.products_found,
                    products_valid=excluded.products_valid,
                    products_rejected=excluded.products_rejected,
                    cooldown_until=excluded.cooldown_until,
                    notes=excluded.notes
            """, (
                log.run_id, log.mode, log.status, log.started_at.isoformat(),
                log.finished_at.isoformat() if log.finished_at else None,
                log.duration_sec, log.products_found, log.products_valid, log.products_rejected,
                log.cooldown_until.isoformat() if log.cooldown_until else None,
                log.notes
            ))
            conn.commit()

    def get_run_logs(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM meesho_run_logs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_recent_run_logs(self, limit: int = 100) -> List[RunLogRecord]:
        rows = self.get_run_logs(limit=limit)
        result = []
        for r in rows:
            try:
                started = datetime.fromisoformat(r["started_at"]) if isinstance(r.get("started_at"), str) else (r.get("started_at") or datetime.now())
                finished = datetime.fromisoformat(r["finished_at"]) if r.get("finished_at") else None
                cool = datetime.fromisoformat(r["cooldown_until"]) if r.get("cooldown_until") else None
                result.append(RunLogRecord(
                    run_id=r["run_id"],
                    mode=r.get("mode") or "scheduled",
                    status=r.get("status") or "SUCCESS",
                    started_at=started,
                    finished_at=finished,
                    duration_sec=float(r["duration_sec"]) if r.get("duration_sec") is not None else None,
                    products_found=int(r.get("products_found") or 0),
                    products_valid=int(r.get("products_valid") or 0),
                    products_rejected=int(r.get("products_rejected") or 0),
                    cooldown_until=cool,
                    notes=r.get("notes") or ""
                ))
            except Exception:
                pass
        return result

    def save_changes(self, changes: List[ChangeRecord], run_id: Optional[str] = None):
        with self._get_connection() as conn:
            for c in changes:
                rid = run_id or getattr(c, "run_id", "manual_run")
                conn.execute("""
                    INSERT INTO meesho_changes (
                        run_id, product_id, name, change_type, old_value, new_value, pct_change, detected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rid, c.product_id, c.name, c.change_type, c.old_value, c.new_value,
                    c.pct_change, c.detected_at.isoformat()
                ))
            conn.commit()

    def get_changes(self, limit: int = 500) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM meesho_changes ORDER BY detected_at DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_recent_changes(self, limit: int = 500) -> List[ChangeRecord]:
        rows = self.get_changes(limit=limit)
        result = []
        for r in rows:
            try:
                dt = datetime.fromisoformat(r["detected_at"]) if isinstance(r.get("detected_at"), str) else (r.get("detected_at") or datetime.now())
                result.append(ChangeRecord(
                    product_id=r["product_id"],
                    name=r.get("name") or "",
                    change_type=r.get("change_type") or "",
                    old_value=r.get("old_value"),
                    new_value=r.get("new_value"),
                    pct_change=float(r["pct_change"]) if r.get("pct_change") is not None else None,
                    detected_at=dt
                ))
            except Exception:
                pass
        return result

    def save_rejected(self, rejected_list: List[RejectedRecord], run_id: Optional[str] = None):
        with self._get_connection() as conn:
            for r in rejected_list:
                rid = run_id or "manual_run"
                conn.execute("""
                    INSERT INTO meesho_rejected (run_id, raw_data, reason, rejected_at)
                    VALUES (?, ?, ?, ?)
                """, (rid, json.dumps(r.raw_data, ensure_ascii=False), r.reason, r.rejected_at.isoformat()))
            conn.commit()

    def get_rejected(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM meesho_rejected ORDER BY rejected_at DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_recent_rejected(self, limit: int = 200) -> List[RejectedRecord]:
        rows = self.get_rejected(limit=limit)
        result = []
        for r in rows:
            try:
                raw_data = json.loads(r["raw_data"]) if isinstance(r.get("raw_data"), str) else (r.get("raw_data") or {})
                rej_at = datetime.fromisoformat(r["rejected_at"]) if isinstance(r.get("rejected_at"), str) else (r.get("rejected_at") or datetime.now())
                result.append(RejectedRecord(
                    raw_data=raw_data,
                    reason=r.get("reason") or "Schema validation failure",
                    rejected_at=rej_at
                ))
            except Exception:
                pass
        return result

