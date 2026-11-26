"""
Generic form builder for ScrollableForm subclasses.

Core function
-------------
    build_form(host, fields, doc_opener) -> list[str]

Iterates a list of Section / FieldDef entries, creates the appropriate
Qt widgets, registers them on the host via host.field(), wires up
style-reset signals, and returns the list of required field keys.

The host must expose:
    host.form          - QFormLayout to add rows to
    host.field(key, w) - registers widget and returns it (ScrollableForm API)
    host._on_field_changed() - called after upload_img interactions
"""

from __future__ import annotations

import base64
from typing import Any

from PySide6.QtCore import Qt, QRegularExpression
from PySide6.QtGui import QPixmap, QRegularExpressionValidator
from three_ps_lcca_gui.gui.themes import get_token
from three_ps_lcca_gui.gui.theme import FS_SECTION, INPUT_MIN_H, TEXTAREA_H
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from three_ps_lcca_gui.gui.themes import get_token
from .form_definitions import FieldDef, Section
from .image_utils import compress_image, resolve_img_settings
from .percent_or_value import PercentOrValueInput
from ..validation_helpers import confirm_clear_all
from ..doc_link import doc_inline, doc_label



_PLACEHOLDER = "-- select --"
# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def make_section_label(title: str, pad_top: int = 16, pad_bottom: int = 4) -> QLabel:
    """Return a QLabel styled according to Tier 2 section heading typography."""
    header = QLabel(title)
    header.setStyleSheet(
        f"font-size: {FS_SECTION}pt; font-weight: {get_token('weight-semibold')}; padding-top: {pad_top}px; padding-bottom: {pad_bottom}px;"
    )
    return header


def make_section_header(title: str, pad_top: int = 16, pad_bottom: int = 4) -> list[QWidget]:
    """Return [header QLabel, divider QWidget] ready to add to a QFormLayout or QBoxLayout."""
    header = make_section_label(title, pad_top=pad_top, pad_bottom=pad_bottom)

    divider = QWidget()
    divider.setFixedHeight(1)
    divider.setStyleSheet("background-color: palette(mid);")

    return [header, divider]


_make_section_header = make_section_header




def _make_upload_img_widget(
    host: Any,
    key: str,
    preset: Any,
) -> tuple[QWidget, QLabel, QLineEdit]:
    """
    Build the image upload container (preview + Browse / Clear buttons).

    Returns
    -------
    container  : QWidget  - the outer widget added to the form layout
    preview    : QLabel   - the image preview label (caller may store a ref)
    logo_input : QLineEdit - hidden input holding the base64 string
    """
    # Validate the preset early so misconfigured field defs fail at startup,
    # not at runtime when the user actually clicks Browse.
    resolve_img_settings(preset)

    container = QWidget()
    file_layout = QVBoxLayout(container)
    file_layout.setContentsMargins(0, 0, 0, 0)
    file_layout.setSpacing(6)

    # Hidden QLineEdit stores the base64-encoded image for save/load.
    # Base64 images can be hundreds of KB - raise the default 32767-char cap.
    logo_input = QLineEdit()
    logo_input.setObjectName(key)   # needed for findChild(QLineEdit, key) lookups
    logo_input.setMaxLength(10_000_000)
    logo_input.setReadOnly(True)
    logo_input.hide()

    preview = QLabel("No image selected")
    preview.setFixedHeight(180)
    preview.setAlignment(Qt.AlignCenter)
    preview.setStyleSheet(f"border: 1px solid {get_token('surface_mid')};")

    btn_browse = QPushButton("Browse Image")
    btn_browse.setMinimumHeight(30)

    btn_clear = QPushButton("Clear Image")
    btn_clear.setMinimumHeight(30)

    # ---- closures --------------------------------------------------------
    def browse_file(
        _checked: bool = False,
        _input: QLineEdit = logo_input,
        _preview: QLabel = preview,
    ) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            host,
            "Select Image",
            "",
            "Images (*.png *.jpg *.jpeg)",
        )
        if not file_path:
            return

        try:
            settings = resolve_img_settings(preset)
            img_bytes = compress_image(file_path, settings)
        except Exception as e:
            QMessageBox.warning(host, "Image Error",
                                f"Could not process image:\n{e}")
            return

        pixmap = QPixmap()
        pixmap.loadFromData(img_bytes)
        w = _preview.width() or 120
        scaled = pixmap.scaled(
            w, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        _preview.setPixmap(scaled)

        _input.setText(base64.b64encode(img_bytes).decode("utf-8"))
        host._on_field_changed()

    def clear_image(
        _checked: bool = False,
        _input: QLineEdit = logo_input,
        _preview: QLabel = preview,
    ) -> None:
        if not confirm_clear_all(host):
            return
        _input.clear()
        _preview.setPixmap(QPixmap())
        _preview.setText("No image selected")
        host._on_field_changed()

    btn_browse.clicked.connect(browse_file)
    btn_clear.clicked.connect(clear_image)

    btn_row = QWidget()
    btn_row_layout = QVBoxLayout(btn_row)
    btn_row_layout.setContentsMargins(0, 0, 0, 0)
    btn_row_layout.setSpacing(6)
    btn_row_layout.setAlignment(Qt.AlignTop)
    btn_browse.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    btn_clear.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    btn_row_layout.addWidget(btn_browse)
    btn_row_layout.addWidget(btn_clear)

    row = QWidget()
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(12)
    row_layout.setAlignment(Qt.AlignTop)
    preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    row_layout.addWidget(preview, 1, Qt.AlignTop)
    row_layout.addWidget(btn_row, 1, Qt.AlignTop)

    file_layout.addWidget(row)

    return container, preview, logo_input, btn_row


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

#: Stores upload_img preview labels keyed by field key so the host's
#: clear_all() implementation can reset them without knowing internals.
#: Attached to the host as  host._img_previews  by build_form().
_IMG_PREVIEWS_ATTR = "_img_previews"
_IMG_BTN_ROWS_ATTR = "_img_btn_rows"


def freeze_img_uploads(host, fields: list, frozen: bool) -> None:
    """Freeze/unfreeze Browse+Clear buttons for all upload_img fields."""
    btn_rows: dict = getattr(host, _IMG_BTN_ROWS_ATTR, {})
    for f in fields:
        if isinstance(f, FieldDef) and f.field_type == "upload_img":
            btn_row = btn_rows.get(f.key)
            if btn_row:
                from ..validation_helpers import freeze_widgets
                for btn in btn_row.findChildren(QPushButton):
                    freeze_widgets(frozen, btn)


_HALF_WIDTH_TYPES = {"text", "phone", "int", "float", "combo", "per_or_val"}

# Width breakpoints (px) -> column count, like CSS media queries
_BP_TABLET = 700    # below: 1 column (mobile)
_BP_DESKTOP = 1200  # below: 2 columns (tablet); at/above: 3 (desktop)


class _ResponsiveGrid(QWidget):
    """Holds short field sections and reflows them into 1/2/3 columns by width.
    max_cols caps the column count (e.g. 2 keeps value/source pairs on one row)."""

    def __init__(self, max_cols: int = 3):
        super().__init__()
        self._max_cols = max_cols
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(24)
        self._grid.setVerticalSpacing(12)
        self._items: list[QWidget] = []
        self._cols = 0

    def add(self, w: QWidget) -> None:
        self._items.append(w)
        self._reflow(self._cols_for(self.width()) if self._cols else 1)

    def _cols_for(self, width: int) -> int:
        if width < _BP_TABLET:
            return 1
        return min(self._max_cols, 2 if width < _BP_DESKTOP else 3)

    def _reflow(self, cols: int) -> None:
        self._cols = cols
        for w in self._items:
            self._grid.removeWidget(w)
        for i, w in enumerate(self._items):
            self._grid.addWidget(w, i // cols, i % cols, Qt.AlignTop)
        for c in range(3):
            self._grid.setColumnStretch(c, 1 if c < cols else 0)

    def resizeEvent(self, event):
        cols = self._cols_for(event.size().width())
        if cols != self._cols:
            self._reflow(cols)
        super().resizeEvent(event)


def build_form(
    host: Any,
    fields: list[Section | FieldDef],
    max_cols: int = 3,
) -> list[str]:
    """
    Iterate *fields* and populate ``host.form`` (a QFormLayout).

    For each FieldDef:
    - Creates a labeled section widget with explanation text + optional docs link
    - Instantiates the correct Qt input widget for the field type
    - Registers it via ``host.field(key, widget)`` and sets it as ``host.<key>``
    - Wires up style-reset signals
    - Tracks required keys

    For each Section:
    - Renders a bold header label and a horizontal divider

    Parameters
    ----------
    host : ScrollableForm subclass
        The form instance being populated.
    fields : list[Section | FieldDef]
        Declarative field definitions (see form_definitions.py).
    max_cols : int
        Most columns short fields may use on wide screens (1-3).

    Returns
    -------
    list[str]
        Keys of all required fields, ready to assign to ``host.required_keys``.
    """
    # Ensure a dict exists on the host for tracking upload_img previews
    if not hasattr(host, _IMG_PREVIEWS_ATTR):
        setattr(host, _IMG_PREVIEWS_ATTR, {})
    if not hasattr(host, _IMG_BTN_ROWS_ATTR):
        setattr(host, _IMG_BTN_ROWS_ATTR, {})

    img_previews: dict[str, QLabel] = getattr(host, _IMG_PREVIEWS_ATTR)
    img_btn_rows: dict[str, QWidget] = getattr(host, _IMG_BTN_ROWS_ATTR)
    required_keys: list[str] = []
    open_row: _ResponsiveGrid | None = None  # current group of short fields

    for entry in fields:

        # ── Section header ────────────────────────────────────────────────
        if isinstance(entry, Section):
            open_row = None
            for widget in _make_section_header(entry.title):
                host.form.addRow(widget)
            continue

        # ── Field entry ───────────────────────────────────────────────────
        f: FieldDef = entry

        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(6)

        # Title
        if f.required:
            title_label = QLabel(f'{f.title} <span style="color:{get_token("danger")};">*</span>')
            title_label.setTextFormat(Qt.RichText)
        else:
            title_label = QLabel(f.title)
        title_label.setStyleSheet(f"font-weight: {get_token('weight-semibold')};")
        layout.addWidget(title_label)

        # ── text ──────────────────────────────────────────────────────────
        if f.field_type == "text":
            widget = QLineEdit()
            widget.setMinimumHeight(INPUT_MIN_H)
            if f.placeholder_text:
                widget.setPlaceholderText(f.placeholder_text)
            setattr(host, f.key, host.field(f.key, widget))
            widget.textChanged.connect(lambda _, w=widget: w.setStyleSheet(""))

        # ── textarea ──────────────────────────────────────────────────────
        elif f.field_type == "textarea":
            widget = QTextEdit()
            widget.setFixedHeight(TEXTAREA_H)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            if f.placeholder_text:
                widget.setPlaceholderText(f.placeholder_text)
            setattr(host, f.key, host.field(f.key, widget))

        # ── int ───────────────────────────────────────────────────────────
        elif f.field_type == "int":
            lo, hi = f.options
            widget = QSpinBox()
            widget.setRange(lo, hi)
            if f.unit:
                widget.setSuffix(f" {f.unit}")
            if f.default is not None:
                widget.setValue(int(f.default))
                if int(f.default) == lo:
                    widget.setSpecialValueText(" ")
            widget.setMinimumHeight(INPUT_MIN_H)
            setattr(host, f.key, host.field(f.key, widget))
            widget.valueChanged.connect(
                lambda _, w=widget: w.setStyleSheet(""))

        elif f.field_type == "phone":
            widget = QLineEdit()
            widget.setMinimumHeight(INPUT_MIN_H)
            # widget.setPlaceholderText("e.g. +1 555 123 4567")

            # Allow: optional +, digits, spaces, dashes, parentheses
            regex = QRegularExpression(r"^\+?[0-9\s\-\(\)]{7,20}$")
            validator = QRegularExpressionValidator(regex)
            widget.setValidator(validator)

            setattr(host, f.key, host.field(f.key, widget))

            widget.textChanged.connect(lambda _, w=widget: w.setStyleSheet(""))

        # ── float ─────────────────────────────────────────────────────────
        elif f.field_type == "float":
            lo, hi, decimals = f.options
            widget = QDoubleSpinBox()
            widget.setRange(lo, hi)
            widget.setDecimals(decimals)
            if f.unit:
                widget.setSuffix(f" {f.unit}")
            if f.default is not None:
                widget.setValue(float(f.default))
                if float(f.default) == lo:
                    widget.setSpecialValueText(" ")
            widget.setMinimumHeight(INPUT_MIN_H)
            setattr(host, f.key, host.field(f.key, widget))
            widget.valueChanged.connect(
                lambda _, w=widget: w.setStyleSheet(""))

        # ── combo ─────────────────────────────────────────────────────────
        elif f.field_type == "combo":
            widget = QComboBox()
            if f.combo_placeholder != "":
                widget.addItem(f.combo_placeholder if f.combo_placeholder is not None else _PLACEHOLDER)
            widget.addItems(f.options or [])
            if f.default is not None:
                idx = widget.findText(str(f.default))
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            
            widget.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            widget.setMinimumContentsLength(15)
            
            widget.setMinimumHeight(INPUT_MIN_H)
            setattr(host, f.key, host.field(f.key, widget))
            widget.currentIndexChanged.connect(
                lambda _, w=widget: w.setStyleSheet(""))

        # ── per_or_val ────────────────────────────────────────────────────
        elif f.field_type == "per_or_val":
            widget = PercentOrValueInput(
                unit=f.unit, percent_of=f.percent_of,
                decimals=f.options if isinstance(f.options, int) else 2,
                min_pct=f.min_pct, max_pct=f.max_pct,
                min_val=f.min_val, max_val=f.max_val,
            )
            setattr(host, f.key, host.field(f.key, widget))
            widget.changed.connect(lambda w=widget: w.line.setStyleSheet(""))

        # ── upload_img ────────────────────────────────────────────────────
        elif f.field_type == "upload_img":
            container, preview, logo_input, btn_row = _make_upload_img_widget(
                host, f.key, f.options
            )
            img_previews[f.key] = preview
            img_btn_rows[f.key] = btn_row
            setattr(host, f.key, host.field(f.key, logo_input))
            layout.addWidget(container)

        else:
            raise ValueError(
                f"Unknown field_type {f.field_type!r} for key '{f.key}'. "
                f"Expected one of: text, textarea, int, float, combo, upload_img, per_or_val."
            )

        # upload_img adds its own container widget above; all others add here
        if f.field_type != "upload_img":
            layout.addWidget(widget)

        # Help text sits below the input so inputs in a row line up
        if f.explanation:
            html = f.explanation + (" " + doc_inline(f.doc_slug) if f.doc_slug else "")
            help_label = doc_label(html)
            help_label.setStyleSheet(f"color: {get_token('text_secondary')};")
            layout.addWidget(help_label)

        # Permanently blocked fields are frozen at build time
        if f.blocked:
            from ..validation_helpers import freeze_form
            freeze_form([f], host, frozen=True)

        if f.required:
            required_keys.append(f.key)

        # Short fields share a responsive grid; wide ones take the full row
        if f.field_type in _HALF_WIDTH_TYPES:
            if open_row is None:
                open_row = _ResponsiveGrid(max_cols)
                host.form.addRow(open_row)
            open_row.add(section)
        else:
            open_row = None
            host.form.addRow(section)

    # ── Patch load_data_dict to restore image previews on project load ───────
    #
    # base_widget.load_data_dict only knows about registered QLineEdit/QComboBox
    # etc. The upload_img preview QLabel is a separate widget it never touches.
    # We wrap the host's method here so that after the base restore runs, any
    # base64 strings saved under upload_img keys are decoded and shown in their
    # preview labels.
    #
    _original_load = host.load_data_dict

    def _load_data_dict_with_previews(data: dict) -> None:
        # 1. Restore all standard fields (including the hidden logo_input QLineEdit)
        _original_load(data)

        # 2. Restore image previews for any upload_img fields
        previews: dict[str, QLabel] = getattr(host, _IMG_PREVIEWS_ATTR, {})
        for key, preview in previews.items():
            b64 = data.get(key, "")
            if not b64:
                preview.setPixmap(QPixmap())
                preview.setText("No image selected")
                continue
            try:
                img_bytes = base64.b64decode(b64)
                pixmap = QPixmap()
                pixmap.loadFromData(img_bytes)
                if pixmap.isNull():
                    raise ValueError("QPixmap could not decode image data")
                w = preview.width() or 120
                scaled = pixmap.scaled(
                    w, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                preview.setPixmap(scaled)
            except Exception:
                preview.setPixmap(QPixmap())
                preview.setText("No image selected")

    host.load_data_dict = _load_data_dict_with_previews

    return required_keys


