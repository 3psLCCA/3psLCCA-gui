from three_ps_lcca_gui.gui.themes import get_token
from three_ps_lcca_gui.gui._CONFIG import LOG_DATA_UPDATES
from three_ps_lcca_gui.gui.theme import SP1, SP2, SP3, SP4, FS_MD, FS_SECTION, FW_BOLD
from three_ps_lcca_gui.gui.styles import font
from ..carbon_emission.widgets.transport_emissions import _named_label, _stat_grid
from three_ps_lcca_gui.gui.assets.themes.column_style import (
    apply_column_style,
    pin_last_column,
    pinned_view,
    refit,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QFrame,
    QScrollArea,
    QToolTip,
    QStyleOptionViewItem,
)
from PySide6.QtCore import Qt, QTimer, QRect, QEvent, QModelIndex

import json
import time
import datetime

from ..utils.definitions import UNIT_DISPLAY
from ..utils.display_format import fmt, fmt_comma, DECIMAL_PLACES
from ..utils.icons import make_icon
from ..utils.table_widgets import (
    GroupedHeaderView,
    BaseActionDelegate,
    TooltipTableMixin,
    TableCard,
    fit_to_contents,
)

# rebuild log: prints only with LOG_DATA_UPDATES on (_CONFIG.py)
_dev_log = print if LOG_DATA_UPDATES else (lambda *a, **k: None)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHUNKS = [
    ("str_foundation", "Foundation"),
    ("str_sub_structure", "Sub-Structure"),
    ("str_super_structure", "Super-Structure"),
    ("str_misc", "Misc"),
]


REASON_INCOMPLETE = "Incomplete Data"
REASON_EXCLUDED   = "Manually Excluded"


# ---------------------------------------------------------------------------
# Validity check
# ---------------------------------------------------------------------------


def _fmt_unit(code: str) -> str:
    return UNIT_DISPLAY.get(code.lower(), code) if code else code


def _recycle_pct(v: dict) -> float:
    """Read recyclability % - checks both field names for backward compat."""
    return float(
        v.get("post_demolition_recovery_percentage")
        or v.get("recyclability_percentage")
        or 0
    )


def is_recyclable_valid(item: dict) -> bool:
    v = item.get("values", {})
    try:
        return all(
            [
                _recycle_pct(v) > 0,
                float(v.get("scrap_rate") or 0) > 0,
                float(v.get("quantity") or 0) > 0,
            ]
        )
    except (TypeError, ValueError):
        return False


def calc_recyclable_qty(item: dict) -> float:
    """Recyclable Quantity = quantity × (recyclability% / 100)"""
    v = item.get("values", {})
    try:
        return float(v.get("quantity", 0) or 0) * (_recycle_pct(v) / 100)
    except (TypeError, ValueError):
        return 0.0


def calc_recovered_value(item: dict) -> float:
    """Recovered Value = Recyclable Qty × scrap_rate"""
    v = item.get("values", {})
    try:
        return calc_recyclable_qty(item) * float(v.get("scrap_rate") or 0)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Action column delegate
# ---------------------------------------------------------------------------


class _RecyclingActionDelegate(BaseActionDelegate):
    """Paints circular icon buttons in the recycling table action column.

    Per-row data stored in the action item's Qt.UserRole as a dict:
        {"btns": ["edit", "exclude"], "chunk_id": ..., "comp_name": ...,
         "idx": ..., "item": ...}
    """

    _ICON_CFG = {
        "edit": (None, (46, 204, 113), "Edit"),
        "exclude": (get_token("danger"), (231, 76, 60), "Exclude from calculation"),
        "include": (get_token("success"), (46, 204, 113), "Include in calculation"),
    }

    def __init__(self, table, handler):
        super().__init__(table)
        self._handler = handler
        self._icons = {
            key: (make_icon(key, color=color), hover_rgb, tooltip)
            for key, (color, hover_rgb, tooltip) in self._ICON_CFG.items()
        }

    def _raw_row_data(self, row) -> dict | None:
        item = self._table.item(row, self._action_col())
        return item.data(Qt.UserRole) if item else None

    def _get_btns_for_row(self, row) -> list[tuple]:
        data = self._raw_row_data(row)
        if not data:
            return []
        return [self._icons[key] for key in data.get("btns", [])]

    def editorEvent(self, event, model, option, index):
        if self._frozen:
            return False
        if event.type() == QEvent.MouseButtonRelease:
            data = self._raw_row_data(index.row())
            if not data:
                return False
            btn_keys = data.get("btns", [])
            rects = self._btn_rects(option.rect, len(btn_keys))
            for i, key in enumerate(btn_keys):
                if rects[i].contains(event.pos()):
                    ci, cn, idx, it = (
                        data["chunk_id"],
                        data["comp_name"],
                        data["idx"],
                        data["item"],
                    )
                    if key == "edit":
                        self._handler._open_recyclability_edit(ci, cn, idx, it)
                    elif key == "exclude":
                        self._handler._toggle_inclusion(ci, cn, idx, False)
                    elif key == "include":
                        self._handler._toggle_inclusion(ci, cn, idx, True)
                    return True
        return False


# ---------------------------------------------------------------------------
# Recycling Table
# ---------------------------------------------------------------------------


class RecyclingTable(TooltipTableMixin, QTableWidget):
    _L = Qt.AlignLeft | Qt.AlignVCenter
    _R = Qt.AlignRight | Qt.AlignVCenter
    _C = Qt.AlignCenter

    # Cols 2-3 → "Quantity" group (Value + Unit)
    _GROUPS = [(2, 2, "Quantity")]

    INCLUDED_HEADERS = [
        ("Category", _L),  # 0
        ("Component", _L),  # 1
        ("Value", _C),  # 2  ┐ Quantity group
        ("Unit", _C),  # 3  ┘
        ("Recyclability %", _R),  # 4
        ("Recyclable\nQuantity", _R),  # 5
        ("Scrap Rate", _R),  # 6
        ("Recovered Value", _R),  # 7
        ("Warning", _L),  # 8
        ("Action", _C),  # 9  buttons, pinned to the right edge
    ]

    EXCLUDED_HEADERS = [
        ("Category", _L),  # 0
        ("Component", _L),  # 1
        ("Value", _C),  # 2  ┐ Quantity group
        ("Unit", _C),  # 3  ┘
        ("Recyclability %", _R),  # 4
        ("Scrap Rate", _R),  # 5
        ("Reason", _L),  # 6
        ("Action", _C),  # 7  buttons, pinned to the right edge
    ]

    def __init__(self, is_included: bool, handler, parent=None):
        super().__init__(parent)
        self.is_included = is_included

        self.setHorizontalHeader(GroupedHeaderView(groups=self._GROUPS))

        headers = self.INCLUDED_HEADERS if is_included else self.EXCLUDED_HEADERS
        self.setColumnCount(len(headers))
        for col, (label, align) in enumerate(headers):
            item = QTableWidgetItem(label)
            item.setTextAlignment(align)
            self.setHorizontalHeaderItem(col, item)

        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionMode(QTableWidget.NoSelection)
        self.setTextElideMode(Qt.ElideNone)
        self.verticalHeader().setVisible(False)
        fit_to_contents(self)  # every row shows; the page scrolls down

        # Action buttons: paint and handle clicks in the last column
        self.action_delegate = _RecyclingActionDelegate(self, handler)
        self.setItemDelegateForColumn(len(headers) - 1, self.action_delegate)
        btn_h = self.action_delegate.sizeHint(QStyleOptionViewItem(), QModelIndex()).height()
        self.verticalHeader().setMinimumSectionSize(btn_h)  # rows fit the buttons

        # widths from the header labels (assets/themes/column_style.py); col 1
        # holds the material name (takes the spare width), "Value" is a quantity.
        # The table scrolls sideways itself, with Action pinned to its right edge.
        apply_column_style(self, {1: "name", 2: "quantity"})
        pin_last_column(self)
        self.action_delegate.track(pinned_view(self))

    def viewportEvent(self, event):
        if event.type() == QEvent.ToolTip:
            index = self.indexAt(event.pos())
            action_col = self.columnCount() - 1
            if index.isValid() and index.column() != action_col:
                item = self.item(index.row(), index.column())
                if item and item.text():
                    QToolTip.showText(event.globalPos(), item.text())
                    return True
            QToolTip.hideText()
        return super().viewportEvent(event)

    def update_height(self):
        """Re-fit columns, rows and the pinned Action column to the rows now."""
        refit(self)
        self.updateGeometry()

    def clear_rows(self):
        self.setRowCount(0)
        self.update_height()


# ---------------------------------------------------------------------------
# RecyclingWidget - main tab
# ---------------------------------------------------------------------------


class Recycling(QWidget):
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.setObjectName("RecyclingWidget")

        self._frozen = False
        self._shown_data = None  # data the table was last built from; None = rebuild on next show
        if controller and hasattr(controller, "project_loaded"):
            controller.project_loaded.connect(self._on_project_reloaded)
        if controller and hasattr(controller, "chunk_updated"):
            _STRUCTURE_CHUNKS = {"str_foundation", "str_sub_structure", "str_super_structure", "str_misc"}
            controller.chunk_updated.connect(
                lambda name: self._on_structure_changed(name) if name in _STRUCTURE_CHUNKS else None
            )

        # page margins as on Carbon Emissions / Construction Works Data
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(24, 20, 24, 16)
        outer_layout.setSpacing(16)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # as on Transportation / Material: keep the scrollbar's room so width stays put
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setSpacing(SP4)

        # Heading row and category totals card, as on Material / Transportation
        # (same helpers and #transportSummary style)
        head = QHBoxLayout()
        head.setContentsMargins(SP1, SP2, SP1, SP1)
        head.setSpacing(SP3)
        title = QLabel("Recycling")
        title.setFont(font(FS_SECTION, FW_BOLD))
        self.count_lbl = _named_label("", "statLabel")
        self.count_lbl.setFont(font(FS_MD))
        self.total_lbl = QLabel("-")
        self.total_lbl.setFont(font(FS_SECTION, FW_BOLD))
        self.total_lbl.setToolTip("Total recovered value")
        head.addWidget(title, 0, Qt.AlignBottom)
        head.addWidget(self.count_lbl, 0, Qt.AlignBottom)
        head.addStretch()
        head.addWidget(self.total_lbl, 0, Qt.AlignBottom)
        main_layout.addLayout(head)

        summary = QFrame()
        summary.setObjectName("transportSummary")
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(SP4, SP3, SP4, SP3)
        cats, (self.foundation_lbl, self.sub_lbl, self.super_lbl, self.misc_lbl) = _stat_grid([
            ("Foundation", "-"),
            ("Sub-Structure", "-"),
            ("Super-Structure", "-"),
            ("Misc", "-"),
        ])
        summary_layout.addLayout(cats)
        main_layout.addWidget(summary)

        # ── Included Section ─────────────────────────────────────────────
        self.included_table = RecyclingTable(is_included=True, handler=self)
        self._included_action = self.included_table.action_delegate
        # card: title and row count above the table
        included_card = TableCard(self.included_table, "Included in Recyclability")
        included_card.count_rows()
        main_layout.addWidget(included_card)

        # ── Excluded Section ─────────────────────────────────────────────
        self.excluded_table = RecyclingTable(is_included=False, handler=self)
        self._excluded_action = self.excluded_table.action_delegate
        # card: title and row count above the table
        excluded_card = TableCard(self.excluded_table, "Excluded from Recyclability")
        excluded_card.count_rows()
        main_layout.addWidget(excluded_card)
        main_layout.addStretch()

        scroll.setWidget(container)
        outer_layout.addWidget(scroll)

    def _get_currency(self) -> str:
        try:
            data = self.controller.engine.fetch_chunk("general_info") or {}
            return data.get("project_currency", "")
        except Exception:
            return ""

    # ── Data Loading ─────────────────────────────────────────────────────

    def on_refresh(self):
        if not self.controller or not getattr(self.controller, "engine", None):
            return
        if LOG_DATA_UPDATES:  # DEBUG rebuild log
            _t0 = time.perf_counter()
            QTimer.singleShot(0, lambda: _dev_log(
                f"[Recycling] rebuilt in {(time.perf_counter() - _t0) * 1000:.0f} ms"))

        result = self._compute()

        included_with_warn = [
            (
                cat,
                chunk_id,
                comp,
                idx,
                item,
                value,
                (
                    "! Zero Quantity"
                    if float(item.get("values", {}).get("quantity", 0) or 0) == 0
                    else ""
                ),
            )
            for cat, chunk_id, comp, idx, item, value in result["included_items"]
        ]

        self._update_currency_headers(result["currency"])
        self._populate_included(included_with_warn, result["currency"])
        self._populate_excluded(result["excluded_items"])
        self._update_summary(
            result["total_recovered_value"],
            result["included_count"],
            result["total_count"],
            result["cat_totals"],
            result["currency"],
        )
        self._shown_data = self._data_snapshot()

    def _update_currency_headers(self, currency: str):
        cu = currency or ""
        def _hdr(text):
            it = QTableWidgetItem(text)
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return it
        # Included table: col 6 = Scrap Rate, col 7 = Recovered Value
        self.included_table.setHorizontalHeaderItem(
            6, _hdr(f"Scrap Rate\n({cu}/unit)" if cu else "Scrap Rate\n(per unit)")
        )
        self.included_table.setHorizontalHeaderItem(
            7, _hdr(f"Recovered Value\n({cu})" if cu else "Recovered Value")
        )
        # Excluded table: col 5 = Scrap Rate
        self.excluded_table.setHorizontalHeaderItem(
            5, _hdr(f"Scrap Rate\n({cu}/unit)" if cu else "Scrap Rate\n(per unit)")
        )

    def _populate_included(self, items, currency: str):
        t = self.included_table
        t.clear_rows()

        for category, chunk_id, comp_name, idx, item, value, warn in items:
            v = item.get("values", {})
            row = t.rowCount()
            t.insertRow(row)

            unit = _fmt_unit(v.get("unit", ""))
            recyclable_qty = f"{fmt(calc_recyclable_qty(item))} {unit}".strip()
            value_str = fmt_comma(value)

            def _ri(text):
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                return it

            t.setItem(row, 0, QTableWidgetItem(category))
            t.setItem(row, 1, QTableWidgetItem(v.get("material_name", "")))
            t.setItem(row, 2, _ri(fmt(v.get("quantity"))))
            t.setItem(row, 3, QTableWidgetItem(unit))
            t.setItem(row, 4, _ri(
                f"{_recycle_pct(v):.{DECIMAL_PLACES}f}%"
                if v.get("post_demolition_recovery_percentage") is not None
                else "-"
            ))
            t.setItem(row, 5, _ri(recyclable_qty))
            t.setItem(row, 6, _ri(fmt(v.get("scrap_rate"))))
            val_item = QTableWidgetItem(value_str)
            val_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t.setItem(row, 7, val_item)
            warn_item = QTableWidgetItem(warn)
            warn_item.setTextAlignment(Qt.AlignCenter)
            t.setItem(row, 8, warn_item)

            action_item = QTableWidgetItem()
            action_item.setData(
                Qt.UserRole,
                {
                    "btns": ["edit", "exclude"],
                    "chunk_id": chunk_id,
                    "comp_name": comp_name,
                    "idx": idx,
                    "item": item,
                },
            )
            action_item.setFlags(Qt.ItemIsEnabled)
            t.setItem(row, 9, action_item)

        t.update_height()

    def _populate_excluded(self, items, currency: str = ""):
        t = self.excluded_table
        t.clear_rows()

        for category, chunk_id, comp_name, idx, item, reason in items:
            v = item.get("values", {})
            row = t.rowCount()
            t.insertRow(row)

            unit = _fmt_unit(v.get("unit", ""))

            def _ri(text):
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                return it

            t.setItem(row, 0, QTableWidgetItem(category))
            t.setItem(row, 1, QTableWidgetItem(v.get("material_name", "")))
            t.setItem(row, 2, _ri(fmt(v.get("quantity"))))
            t.setItem(row, 3, QTableWidgetItem(unit))
            t.setItem(row, 4, _ri(
                f"{_recycle_pct(v):.{DECIMAL_PLACES}f}%"
                if v.get("post_demolition_recovery_percentage") is not None
                else "-"
            ))
            t.setItem(row, 5, _ri(fmt(v.get("scrap_rate"))))
            t.setItem(row, 6, QTableWidgetItem(reason))

            btn_keys = ["edit"] if reason == REASON_INCOMPLETE else ["edit", "include"]
            action_item = QTableWidgetItem()
            action_item.setData(
                Qt.UserRole,
                {
                    "btns": btn_keys,
                    "chunk_id": chunk_id,
                    "comp_name": comp_name,
                    "idx": idx,
                    "item": item,
                },
            )
            action_item.setFlags(Qt.ItemIsEnabled)
            t.setItem(row, 7, action_item)

        t.update_height()

    def _update_summary(
        self,
        total: float,
        included: int,
        total_count: int,
        cat_totals: dict,
        currency: str,
    ):
        def money(v):
            return f"{currency} {fmt_comma(v)}".strip()

        self.total_lbl.setText(money(total))
        self.count_lbl.setText(f"{included} of {total_count} items included")
        for lbl, cat in (
            (self.foundation_lbl, "Foundation"),
            (self.sub_lbl, "Sub-Structure"),
            (self.super_lbl, "Super-Structure"),
            (self.misc_lbl, "Misc"),
        ):
            lbl.setText(money(cat_totals.get(cat, 0)))

    # ── Actions ──────────────────────────────────────────────────────────

    def _toggle_inclusion(
        self, chunk_id: str, comp_name: str, data_index: int, include: bool
    ):
        data = self.controller.engine.fetch_chunk(chunk_id) or {}
        if comp_name in data and data_index < len(data[comp_name]):
            target = data[comp_name][data_index]
            target["state"]["included_in_recyclability"] = include
            target["values"].setdefault("exclusion_reason", {})["recycling"] = "" if include else REASON_EXCLUDED
            self.controller.engine.stage_update(chunk_name=chunk_id, data=data)
            self._mark_dirty()
            QTimer.singleShot(0, self.on_refresh)

    def _open_recyclability_edit(
        self, chunk_id: str, comp_name: str, data_index: int, item: dict
    ):
        from ..structure.widgets.material_dialog import MaterialDialog

        dialog = MaterialDialog(
            comp_name, parent=self, data=item, recyclability_only=True
        )
        if dialog.exec():
            vals = dialog.get_values()
            v_vals = vals.get("values", {})
            data = self.controller.engine.fetch_chunk(chunk_id) or {}
            if comp_name in data and data_index < len(data[comp_name]):
                target = data[comp_name][data_index]
                target["values"]["post_demolition_recovery_percentage"] = v_vals.get(
                    "post_demolition_recovery_percentage"
                )
                target["values"]["scrap_rate"] = v_vals.get("scrap_rate")
                target["values"].setdefault("exclusion_reason", {})["recycling"] = ""
                target["state"]["included_in_recyclability"] = vals.get("state", {}).get(
                    "included_in_recyclability", False
                )
                target["meta"]["modified_on"] = datetime.datetime.now().isoformat()
                self.controller.engine.stage_update(chunk_name=chunk_id, data=data)
                self._mark_dirty()
                QTimer.singleShot(0, self.on_refresh)

    def _mark_dirty(self):
        if self.controller and self.controller.engine:
            eng = self.controller.engine
            eng._last_keystroke_time = time.time()
            eng._has_unsaved_changes = True
            try:
                eng.on_dirty(True)
            except Exception:
                pass

    def _compute(self) -> dict:
        cat_totals = {label: 0.0 for _, label in CHUNKS}
        included_items = []
        excluded_items = []
        total_value = 0.0
        total_count = 0
        included_count = 0

        if not self.controller or not getattr(self.controller, "engine", None):
            return {
                "total_recovered_value": 0.0,
                "cat_totals": cat_totals,
                "included_count": 0,
                "total_count": 0,
                "included_items": [],
                "excluded_items": [],
                "currency": "",
            }

        currency = self._get_currency()

        for chunk_id, category in CHUNKS:
            data = self.controller.engine.fetch_chunk(chunk_id) or {}
            for comp_name, items in data.items():
                for idx, item in enumerate(items):
                    if item.get("state", {}).get("in_trash", False):
                        continue

                    total_count += 1
                    valid = is_recyclable_valid(item)
                    included = item.get("state", {}).get(
                        "included_in_recyclability", True
                    )

                    v = item.get("values", {})
                    if valid and included:
                        included_count += 1
                        value = calc_recovered_value(item)
                        total_value += value
                        cat_totals[category] += value
                        v.setdefault("exclusion_reason", {})["recycling"] = ""
                        included_items.append(
                            (category, chunk_id, comp_name, idx, item, value)
                        )
                    else:
                        reason = REASON_INCOMPLETE if not valid else REASON_EXCLUDED
                        v.setdefault("exclusion_reason", {})["recycling"] = reason
                        excluded_items.append(
                            (category, chunk_id, comp_name, idx, item, reason)
                        )
                    self.controller.engine.stage_update(chunk_name=chunk_id, data=data)

        return {
            "total_recovered_value": total_value,
            "cat_totals": cat_totals,
            "included_count": included_count,
            "total_count": total_count,
            "included_items": included_items,
            "excluded_items": excluded_items,
            "currency": currency,
        }

    def freeze(self, frozen: bool = True):
        self._frozen = frozen
        self._included_action.set_frozen(frozen)
        self._excluded_action.set_frozen(frozen)

    def validate(self) -> dict:
        result = self._compute()
        warnings = []

        if result["total_count"] == 0:
            warnings.append(
                "No materials are available for recycling calculations - add material entries in the Construction Works Data section first"
            )
        elif result["total_recovered_value"] == 0.0:
            warnings.append(
                f"Total recovered (salvage) value is 0 - "
                f"{result['included_count']} of {result['total_count']} materials are included but none yield a positive recycled value; check recyclability percentage and scrap rate entries"
            )

        missing = sum(
            1 for *_, reason in result["excluded_items"] if reason == REASON_INCOMPLETE
        )
        if missing:
            warnings.append(
                f"{missing} material item{'s' if missing != 1 else ''} excluded from recycling calculations - "
                f"recyclability percentage or scrap rate data is missing; complete these fields in the Construction Works Data section"
            )

        return {"errors": [], "warnings": warnings}

    def get_data(self) -> dict:
        result = self._compute()
        return {
            "chunk": "recycling_data",
            "data": {
                "total_recovered_value": result["total_recovered_value"],
                "included_count": result["included_count"],
                "total_count": result["total_count"],
                "cat_totals": result["cat_totals"],
                "currency": result["currency"],
            },
        }

    def _data_snapshot(self) -> str:
        """Everything this page shows, as one string, to tell whether it changed while hidden."""
        if not self.controller or not getattr(self.controller, "engine", None):
            return ""
        return json.dumps([[self.controller.engine.fetch_chunk(c) for c, _ in CHUNKS], self._get_currency()], default=str)

    def _on_structure_changed(self, name):
        # Hidden: skip; showEvent rebuilds if the data differs from what the table was built from
        if self.isVisible():
            _dev_log(f"[Recycling] {name} changed -> rebuild queued")  # DEBUG rebuild log
            QTimer.singleShot(0, self.on_refresh)

    def showEvent(self, event):
        super().showEvent(event)
        if self._shown_data is None or self._data_snapshot() != self._shown_data:
            _dev_log("[Recycling] page shown -> data changed, rebuild")  # DEBUG rebuild log
            self.on_refresh()
        else:
            _dev_log("[Recycling] page shown -> no change, kept")  # DEBUG rebuild log

    def _on_project_reloaded(self):
        _dev_log("[Recycling] project loaded")  # DEBUG rebuild log
        self._shown_data = None
        if self.isVisible():
            self.on_refresh()