"""
Meesho Tracker - Power BI Ready Multi-Sheet Excel Writer
=========================================================
Generates production-grade Excel deliverable at ./output/meesho_store_tracker.xlsx:
- Sheets: Dashboard (KPI cards + native openpyxl charts), Latest, History, Changes, Run_Log, Rejected
- Real numeric/datetime types, frozen headers, autofilter, snake_case headers
- Atomic write (.tmp -> rename), 7-day rolling backups, Excel-lock PermissionError fallback
"""

import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import openpyxl
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from meesho_tracker.config import TrackerConfig
from meesho_tracker.models import ChangeRecord, ProductRecord, RejectedRecord, RunLogRecord
from meesho_tracker.storage import TrackerStorage

logger = logging.getLogger("meesho_tracker.excel_writer")


class ExcelReportWriter:
    def __init__(self, storage: TrackerStorage, config: TrackerConfig):
        self.storage = storage
        self.config = config
        self.output_file = Path(config.storage.excel_file)
        self.backup_dir = self.output_file.parent / "backups"

    def export_workbook(self, run_id: Optional[str] = None) -> Path:
        """
        Builds the multi-sheet Excel report from SQLite and writes it atomically.
        Returns the path of the written file.
        """
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        wb = openpyxl.Workbook()
        # Remove default sheet
        wb.remove(wb.active)

        # 1. Fetch data from SQLite
        latest_products = self.storage.get_latest_products()
        history_products = self.storage.get_history_products()
        changes = self.storage.get_recent_changes(limit=500)
        run_logs = self.storage.get_recent_run_logs(limit=100)
        rejected = self.storage.get_recent_rejected(limit=200)

        # Warn if history exceeds threshold
        if len(history_products) > self.config.storage.history_warning_row_count:
            logger.warning(
                f"History sheet contains {len(history_products)} rows "
                f"(exceeds threshold of {self.config.storage.history_warning_row_count}). Consider archiving."
            )

        # 2. Build Sheets
        self._build_dashboard_sheet(wb, latest_products, changes)
        self._build_latest_sheet(wb, latest_products)
        self._build_history_sheet(wb, history_products)
        self._build_changes_sheet(wb, changes)
        self._build_run_log_sheet(wb, run_logs)
        self._build_rejected_sheet(wb, rejected)

        # 3. Write atomically with backup & lock handling
        written_path = self._save_atomic(wb)
        return written_path

    # -------------------------------------------------------------------------
    # Sheet Builders
    # -------------------------------------------------------------------------

    def _build_dashboard_sheet(
        self,
        wb: openpyxl.Workbook,
        products: List[ProductRecord],
        changes: List[ChangeRecord]
    ):
        ws = wb.create_sheet(title="Dashboard", index=0)
        ws.views.sheetView[0].showGridLines = True

        # Header Title
        ws.merge_cells("B2:J2")
        title_cell = ws["B2"]
        title_cell.value = f"Spice Nest - Meesho Store Analytics Dashboard"
        title_cell.font = Font(name="Segoe UI", size=16, bold=True, color="1F497D")
        title_cell.alignment = Alignment(vertical="center")

        subtitle = ws["B3"]
        subtitle.value = f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Target: {self.config.store.name}"
        subtitle.font = Font(name="Segoe UI", size=10, italic=True, color="595959")

        # Compute KPI Metrics
        total_products = len(products)
        ratings = [p.rating for p in products if p.rating is not None]
        avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else 0.0
        total_reviews = sum(p.review_count or 0 for p in products)
        price_changes_today = sum(1 for c in changes if c.field_changed == "price")

        # KPI Cards (Row 5 & 6)
        kpis = [
            ("Tracked Products", str(total_products), "B", "C", "D9E1F2"),
            ("Average Rating", f"{avg_rating} ★", "D", "E", "E2EFDA"),
            ("Total Reviews", f"{total_reviews:,}", "F", "G", "FFF2CC"),
            ("Price Changes Today", str(price_changes_today), "H", "I", "FCE4D6")
        ]

        border_thin = Side(border_style="thin", color="D9D9D9")
        card_border = Border(top=border_thin, left=border_thin, right=border_thin, bottom=border_thin)

        for label, val, c1, c2, bg in kpis:
            # Label
            ws.merge_cells(f"{c1}5:{c2}5")
            lbl_cell = ws[f"{c1}5"]
            lbl_cell.value = label.upper()
            lbl_cell.font = Font(name="Segoe UI", size=9, bold=True, color="595959")
            lbl_cell.alignment = Alignment(horizontal="center", vertical="center")
            lbl_cell.fill = PatternFill(start_color=bg, end_color=bg, fill_type="solid")
            lbl_cell.border = card_border

            # Value
            ws.merge_cells(f"{c1}6:{c2}6")
            val_cell = ws[f"{c1}6"]
            val_cell.value = val
            val_cell.font = Font(name="Segoe UI", size=18, bold=True, color="1F497D")
            val_cell.alignment = Alignment(horizontal="center", vertical="center")
            val_cell.fill = PatternFill(start_color=bg, end_color=bg, fill_type="solid")
            val_cell.border = card_border

        # Top 5 Reviewed Products Table for Native Excel Chart (Row 9+)
        sorted_by_reviews = sorted(products, key=lambda x: x.review_count or 0, reverse=True)[:5]

        ws["B9"] = "Product"
        ws["C9"] = "Reviews"
        ws["B9"].font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
        ws["B9"].fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
        ws["C9"].font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
        ws["C9"].fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")

        row = 10
        for p in sorted_by_reviews:
            name_short = (p.name[:25] + "..") if len(p.name) > 25 else p.name
            ws[f"B{row}"] = name_short
            ws[f"C{row}"] = p.review_count or 0
            row += 1

        # Add Native openpyxl BarChart
        if sorted_by_reviews:
            chart = BarChart()
            chart.type = "col"
            chart.style = 10
            chart.title = "Top 5 Products by Customer Reviews"
            chart.y_axis.title = "Review Count"
            chart.x_axis.title = "Product"
            chart.height = 12
            chart.width = 18

            data_ref = Reference(ws, min_col=3, min_row=9, max_row=row - 1)
            cats_ref = Reference(ws, min_col=2, min_row=10, max_row=row - 1)
            chart.add_data(data_ref, titles_from_data=True)
            chart.set_categories(cats_ref)
            chart.legend = None

            ws.add_chart(chart, "E9")

    def _build_latest_sheet(self, wb: openpyxl.Workbook, products: List[ProductRecord]):
        headers = [
            ("product_id", "string"),
            ("name", "string"),
            ("price", "currency"),
            ("mrp", "currency"),
            ("discount_pct", "percentage"),
            ("rating", "decimal"),
            ("review_count", "integer"),
            ("in_stock", "boolean"),
            ("sku", "string"),
            ("supplier", "string"),
            ("mall_verified", "boolean"),
            ("is_ad_product", "boolean"),
            ("url", "string"),
            ("image_url", "string"),
            ("scraped_at", "datetime")
        ]

        data_rows = []
        for p in products:
            data_rows.append([
                p.product_id,
                p.name,
                p.price,
                p.mrp,
                p.discount_pct,
                p.rating,
                p.review_count,
                p.in_stock,
                p.sku or "",
                p.supplier or "",
                p.mall_verified,
                p.is_ad_product,
                p.url,
                p.image_url,
                p.scraped_at
            ])

        self._create_data_sheet(wb, "Latest", headers, data_rows)

    def _build_history_sheet(self, wb: openpyxl.Workbook, products: List[ProductRecord]):
        headers = [
            ("snapshot_id", "integer"),
            ("product_id", "string"),
            ("name", "string"),
            ("price", "currency"),
            ("mrp", "currency"),
            ("discount_pct", "percentage"),
            ("rating", "decimal"),
            ("review_count", "integer"),
            ("in_stock", "boolean"),
            ("run_type", "string"),
            ("scraped_at", "datetime")
        ]

        data_rows = []
        for idx, p in enumerate(products, start=1):
            data_rows.append([
                idx,
                p.product_id,
                p.name,
                p.price,
                p.mrp,
                p.discount_pct,
                p.rating,
                p.review_count,
                p.in_stock,
                p.run_type,
                p.scraped_at
            ])

        self._create_data_sheet(wb, "History", headers, data_rows)

    def _build_changes_sheet(self, wb: openpyxl.Workbook, changes: List[ChangeRecord]):
        headers = [
            ("change_id", "integer"),
            ("run_id", "string"),
            ("product_id", "string"),
            ("field_changed", "string"),
            ("old_value", "string"),
            ("new_value", "string"),
            ("detected_at", "datetime")
        ]

        data_rows = []
        for idx, c in enumerate(changes, start=1):
            data_rows.append([
                idx,
                c.run_id,
                c.product_id,
                c.field_changed,
                c.old_value or "",
                c.new_value or "",
                c.detected_at
            ])

        self._create_data_sheet(wb, "Changes", headers, data_rows)

    def _build_run_log_sheet(self, wb: openpyxl.Workbook, logs: List[RunLogRecord]):
        headers = [
            ("run_id", "string"),
            ("run_type", "string"),
            ("started_at", "datetime"),
            ("completed_at", "datetime"),
            ("elapsed_sec", "decimal"),
            ("status", "string"),
            ("products_found", "integer"),
            ("products_saved", "integer"),
            ("partial", "boolean"),
            ("error_message", "string")
        ]

        data_rows = []
        for l in logs:
            data_rows.append([
                l.run_id,
                l.run_type,
                l.started_at,
                l.completed_at,
                l.elapsed_sec,
                l.status,
                l.products_found,
                l.products_saved,
                l.partial,
                l.error_message or ""
            ])

        self._create_data_sheet(wb, "Run_Log", headers, data_rows)

    def _build_rejected_sheet(self, wb: openpyxl.Workbook, rejected: List[RejectedRecord]):
        headers = [
            ("rejected_id", "integer"),
            ("reason", "string"),
            ("raw_data", "string"),
            ("rejected_at", "datetime")
        ]

        data_rows = []
        for idx, r in enumerate(rejected, start=1):
            data_rows.append([
                idx,
                r.reason,
                str(r.raw_data),
                r.rejected_at
            ])

        self._create_data_sheet(wb, "Rejected", headers, data_rows)

    # -------------------------------------------------------------------------
    # Shared Data Sheet Formatting Helper
    # -------------------------------------------------------------------------

    def _create_data_sheet(
        self,
        wb: openpyxl.Workbook,
        title: str,
        headers: List[tuple],
        data_rows: List[List[Any]]
    ):
        ws = wb.create_sheet(title=title)
        ws.views.sheetView[0].showGridLines = True

        # Header Row Styling
        header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
        header_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
        border_thin = Side(border_style="thin", color="D9D9D9")
        cell_border = Border(top=border_thin, left=border_thin, right=border_thin, bottom=border_thin)

        for col_idx, (col_name, _) in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = cell_border

        # Insert Data Rows with Typed Formatting
        for row_idx, row_values in enumerate(data_rows, start=2):
            for col_idx, ((_, col_type), val) in enumerate(zip(headers, row_values), start=1):
                cell = ws.cell(row=row_idx, column=col_idx)

                if val is None:
                    cell.value = ""
                elif col_type == "currency":
                    try:
                        cell.value = float(val)
                        cell.number_format = '₹#,##0.00'
                    except Exception:
                        cell.value = val
                elif col_type == "percentage":
                    try:
                        cell.value = float(val)
                        cell.number_format = '0.0"%"'
                    except Exception:
                        cell.value = val
                elif col_type == "decimal":
                    try:
                        cell.value = float(val)
                        cell.number_format = '0.00'
                    except Exception:
                        cell.value = val
                elif col_type == "integer":
                    try:
                        cell.value = int(val)
                        cell.number_format = '#,##0'
                    except Exception:
                        cell.value = val
                elif col_type == "datetime":
                    if isinstance(val, datetime):
                        cell.value = val
                        cell.number_format = 'yyyy-mm-dd hh:mm:ss'
                    else:
                        cell.value = str(val)
                elif col_type == "boolean":
                    cell.value = bool(val)
                else:
                    cell.value = str(val)

                cell.font = Font(name="Segoe UI", size=9)
                cell.border = cell_border

        # Freeze Header & Add Autofilter
        ws.freeze_panes = "A2"
        max_col_letter = get_column_letter(len(headers))
        ws.auto_filter.ref = f"A1:{max_col_letter}{max(len(data_rows) + 1, 1)}"

        # Column Widths Auto-Calculation
        for col_idx, (col_name, _) in enumerate(headers, start=1):
            max_len = len(col_name)
            for row in range(2, min(len(data_rows) + 2, 50)):
                v = ws.cell(row=row, column=col_idx).value
                if v:
                    max_len = max(max_len, min(len(str(v)), 45))
            ws.column_dimensions[get_column_letter(col_idx)].width = max(max_len + 3, 12)

    # -------------------------------------------------------------------------
    # Atomic Save & Backup Engine
    # -------------------------------------------------------------------------

    def _save_atomic(self, wb: openpyxl.Workbook) -> Path:
        """
        Saves workbook to a temp file, creates a backup of the existing report,
        and atomically renames the temp file. If PermissionError occurs, saves to fallback.
        """
        temp_fd, temp_path_str = tempfile.mkstemp(suffix=".tmp.xlsx", dir=self.output_file.parent)
        os.close(temp_fd)
        temp_path = Path(temp_path_str)

        try:
            wb.save(temp_path)

            # 1. Backup existing workbook if present
            if self.output_file.exists():
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = self.backup_dir / f"meesho_store_tracker_{ts}.xlsx"
                try:
                    shutil.copy2(self.output_file, backup_path)
                    logger.info(f"Created Excel daily backup at: {backup_path}")
                    self._prune_old_backups(keep_count=7)
                except Exception as b_err:
                    logger.warning(f"Backup notice: {b_err}")

            # 2. Atomic Rename
            shutil.move(str(temp_path), str(self.output_file))
            logger.info(f"Successfully generated Power BI Excel report: {self.output_file}")
            return self.output_file

        except PermissionError:
            # File is locked in Excel or Power BI Desktop
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            fallback_path = self.output_file.parent / f"meesho_store_tracker_LOCKED_{ts_str}.xlsx"
            shutil.move(str(temp_path), str(fallback_path))
            logger.error(
                f"PermissionError: {self.output_file} is locked by an external process (Excel/Power BI). "
                f"Saved to timestamped fallback: {fallback_path}"
            )
            return fallback_path
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def _prune_old_backups(self, keep_count: int = 7):
        try:
            backups = sorted(
                list(self.backup_dir.glob("meesho_store_tracker_*.xlsx")),
                key=lambda f: f.stat().st_mtime,
                reverse=True
            )
            for old in backups[keep_count:]:
                old.unlink(missing_ok=True)
        except Exception as e:
            logger.debug(f"Backup pruning note: {e}")

