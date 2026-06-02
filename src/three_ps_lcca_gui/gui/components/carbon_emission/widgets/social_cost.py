from PySide6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QWidget,
    QLabel,
    QFormLayout,
    QStackedWidget,
)
from PySide6.QtCore import Qt, QTimer

from ...base_widget import ScrollableForm
from ...utils.form_builder.form_definitions import FieldDef, Section
from ...utils.form_builder.form_builder import build_form
from ...utils.display_format import fmt, DECIMAL_PLACES
from ...utils.validation_helpers import (
    _apply_border_style,
    clear_field_styles,
    freeze_form,
    freeze_widgets,
    confirm_clear_all,
    validate_form,
)
from three_ps_lcca_gui.gui.themes import get_token

# ── Constants ─────────────────────────────────────────────────────────────────

CHUNK = "social_cost_data"
GLOBAL_CHUNK = "general_info"

_MODE_NITI = "NITI Aayog"
_MODE_RICKE = "K. Ricke et al. (Country-Level)"
_MODE_CUSTOM = "Custom / Manual Override"
# _SOURCES = [_MODE_NITI, _MODE_RICKE, _MODE_CUSTOM]
_SOURCES = [_MODE_RICKE, _MODE_CUSTOM]

_SSP_OPTIONS = [
    "SSP1 (Sustainability)",
    "SSP2 (Middle of the Road)",
    "SSP3 (Regional Rivalry)",
    "SSP4 (Inequality)",
    "SSP5 (Fossil-fueled Development)",
]
_SSP_TO_KEY = {
    "SSP1 (Sustainability)": "SSP1",
    "SSP2 (Middle of the Road)": "SSP2",
    "SSP3 (Regional Rivalry)": "SSP3",
    "SSP4 (Inequality)": "SSP4",
    "SSP5 (Fossil-fueled Development)": "SSP5",
}

# Ricke et al. dataset covers rcp45, rcp60, rcp85 only (confirmed from dataset — no rcp26)
_RCP_OPTIONS = [
    "RCP 4.5 (Intermediate)",
    "RCP 6.0 (High)",
    "RCP 8.5 (Extreme)",
]
_RCP_TO_KEY = {
    "RCP 4.5 (Intermediate)": "rcp45",
    "RCP 6.0 (High)": "rcp60",
    "RCP 8.5 (Extreme)": "rcp85",
}

# All five run options confirmed from dataset: bhm_lr, bhm_richpoor_lr, bhm_richpoor_sr, bhm_sr, djo
_RUN_OPTIONS = [
    "BHM Short-Run (bhm_sr)",
    "BHM Long-Run (bhm_lr)",
    "BHM Rich/Poor Short-Run (bhm_richpoor_sr)",
    "BHM Rich/Poor Long-Run (bhm_richpoor_lr)",
    "DJO (djo)",
]
_RUN_TO_KEY = {
    "BHM Short-Run (bhm_sr)": "bhm_sr",
    "BHM Long-Run (bhm_lr)": "bhm_lr",
    "BHM Rich/Poor Short-Run (bhm_richpoor_sr)": "bhm_richpoor_sr",
    "BHM Rich/Poor Long-Run (bhm_richpoor_lr)": "bhm_richpoor_lr",
    "DJO (djo)": "djo",
}
_RUN_FROM_KEY = {v: k for k, v in _RUN_TO_KEY.items()}

NITI_AAYOG_SCC_INR = 6.3936

# ── Explorer lazy singleton ───────────────────────────────────────────────────

_explorer = None
_explorer_load_error = None


def _get_explorer():
    global _explorer, _explorer_load_error
    if _explorer is None and _explorer_load_error is None:
        try:
            from ..social_cost_of_carbon.ricke.cscc_explorer import CSCCExplorer
            _explorer = CSCCExplorer()
        except Exception as e:
            _explorer_load_error = str(e)
    return _explorer


# ── Field Definitions ─────────────────────────────────────────────────────────

HEADER_FIELDS = [
    Section("Economic Valuation Methodology"),
    FieldDef(
        "source",
        "Cost Methodology",
        "Choose between government standards or peer-reviewed scientific models.",
        "combo",
        options=_SOURCES,
        doc_slug=["Carbon_emissions_data", "SSC"],
    ),
]
NITI_FIELDS = [
    Section("Regional Valuation Adjustment"),
    FieldDef(
        "inr_to_local_rate",
        "INR Conversion Rate",
        "As NITI Aayog values are in INR, provide conversion to your global currency.",
        "float",
        options=(1e-6, 1e6, DECIMAL_PLACES),
        unit="(Currency/INR)",
    ),
]
RICKE_FIELDS = [
    Section("Climate & Socioeconomic Scenarios"),
    FieldDef(
        "usd_to_local_rate",
        "USD Conversion Rate",
        "Conversion rate for international scientific model outputs.",
        "float",
        options=(1e-6, 1e6, DECIMAL_PLACES),
        unit="(Currency/USD)",
    ),
    FieldDef(
        "country_iso3",
        "Country",
        "Country for which the social cost of carbon is estimated (Ricke et al. country-level dataset).",
        "combo",
        options=[],  # populated at runtime from CSCCExplorer
        selection_none=True,
        required=True,
    ),
    FieldDef(
        "ssp_scenario",
        "Socioeconomic Pathway (SSP)",
        "Assumptions on future population, GDP, and energy use.",
        "combo",
        options=_SSP_OPTIONS,
        selection_none=True,
        required=True,
    ),
    FieldDef(
        "rcp_scenario",
        "Climate Trajectory (RCP)",
        "Representative Concentration Pathway for greenhouse gases.",
        "combo",
        options=_RCP_OPTIONS,
        selection_none=True,
        required=True,
    ),
    FieldDef(
        "ricke_run",
        "Damage Function",
        "Statistical model used to estimate climate-economy damages.",
        "combo",
        options=_RUN_OPTIONS,
        selection_none=True,
        required=True,
    ),
    Section("Price Level Adjustment"),
    FieldDef(
        "cpi_ratio",
        "CPI Inflation Ratio",
        "Ricke et al. (2018) values are in 2018 USD. Enter (CPI present year) / (CPI 2018) to inflate to current prices. Leave at 1.0 to use published values as-is.",
        "float",
        options=(0.0, 1e6, DECIMAL_PLACES),
    ),
]
CUSTOM_FIELDS = [
    FieldDef(
        "scc_value",
        "Social Cost of Carbon (SCC)",
        "The financial cost attributed to 1 kg of CO₂e emissions.",
        "float",
        options=(0.0, 1e6, DECIMAL_PLACES),
        unit="(Currency/kgCO₂e)",
    ),
]

# ── Widget ────────────────────────────────────────────────────────────────────


class SocialCost(ScrollableForm):
    """
    Economic valuation of carbon emissions using government or scientific models.

    References:
    - Ricke, K., Drouet, L., Caldeira, K. et al. Country-level social cost of carbon.
      Nature Clim Change 8, 895-900 (2018). https://doi.org/10.1038/s41558-018-0282-y
    """
    def __init__(self, controller=None):
        super().__init__(controller=controller, chunk_name=CHUNK)
        self.__suppress = 0
        self._project_currency = ""
        self._synced = False
        self._ricke_base_usd = 0.0  # cached result from last explorer query
        self._build_ui()

    # ── Suppression ───────────────────────────────────────────────────────────
    # Simple counter so nested suppression scopes dont clobber each other.
    # Stored as int; the bool property keeps all `if self._suppress_signals:` checks working.

    @property
    def _suppress_signals(self):
        return self.__suppress > 0

    @_suppress_signals.setter
    def _suppress_signals(self, val):
        # Accept True/False as increment/decrement so existing call-sites work unchanged.
        if val:
            self.__suppress += 1
        else:
            self.__suppress = max(0, self.__suppress - 1)

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        f = self.form  # main QFormLayout

        # Header: methodology selector
        build_form(self, HEADER_FIELDS)
        self._field_map.pop("source", None)  # managed manually, not via base autosave
        self.source.currentIndexChanged.connect(self._on_mode_changed)

        # Effective SCC summary
        _rc, self._result_lbl = self._padded_label(top=10, bottom=6)
        f.addRow(_rc)

        # Stack - one panel per methodology
        self._stack = QStackedWidget()
        f.addRow(self._stack)

        # Clear button — in a proper QWidget container so Qt gives it real geometry
        self.btn_clear = QPushButton("Clear All")
        self.btn_clear.setMinimumHeight(35)
        self.btn_clear.setMaximumHeight(35)
        self.btn_clear.clicked.connect(self.clear_all)
        _btn_container = QWidget()
        _btn_layout = QHBoxLayout(_btn_container)
        _btn_layout.setContentsMargins(0, 8, 0, 0)
        _btn_layout.addWidget(self.btn_clear)
        f.addRow(_btn_container)

        self._stack.addWidget(self._build_niti_panel())  # index 0
        self._stack.addWidget(self._build_ricke_panel())  # index 1
        self._stack.addWidget(self._build_custom_panel())  # index 2

        QTimer.singleShot(0, self._fit_stack)

    def _make_panel_layout(self, parent):
        """Return a QFormLayout on `parent` matching the main form's style."""
        layout = QFormLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.setLabelAlignment(Qt.AlignRight)
        return layout

    def _padded_label(self, text="", top=8, bottom=8):
        """Wrap a QLabel in a slim container widget so vertical breathing room
        is controlled by explicit margins, not QFormLayout row stretch."""
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, top, 0, bottom)
        vbox.setSpacing(0)
        lbl = QLabel(text)
        lbl.setTextFormat(Qt.RichText)
        lbl.setWordWrap(True)
        vbox.addWidget(lbl)
        return container, lbl

    def _find_row_for_widget(self, layout, target_widget):
        """Helper to safely and recursively locate the QFormLayout row index containing a specific widget."""
        def _contains(item, target):
            if not item:
                return False
            if item.widget() == target:
                return True
            if item.widget() and item.widget().isAncestorOf(target):
                return True
            lay = item.layout()
            if lay:
                for j in range(lay.count()):
                    if _contains(lay.itemAt(j), target):
                        return True
            return False

        for i in range(layout.rowCount()):
            for role in (QFormLayout.FieldRole, QFormLayout.SpanningRole, QFormLayout.LabelRole):
                if _contains(layout.itemAt(i, role), target_widget):
                    return i
        return -1

    def _build_niti_panel(self):
        w = QWidget()
        layout = self._make_panel_layout(w)

        _bc, _ = self._padded_label(
            f"Base Value: <b>{NITI_AAYOG_SCC_INR} INR/kgCO₂e</b> (NITI Aayog, 2023)",
            top=4,
            bottom=4,
        )
        layout.addRow(_bc)

        self.form, _saved = layout, self.form
        try:
            build_form(self, NITI_FIELDS)
            self._field_map.pop("inr_to_local_rate", None)
        finally:
            self.form = _saved

        self.inr_to_local_rate.valueChanged.connect(self._update_niti_result)

        self._niti_layout = layout
        self._inr_row = self._find_row_for_widget(layout, self.inr_to_local_rate)

        _nrc, self._niti_result_lbl = self._padded_label(top=6, bottom=4)
        layout.addRow(_nrc)
        return w

    def _build_ricke_panel(self):
        w = QWidget()
        layout = self._make_panel_layout(w)

        _ref_c, _ref_lbl = self._padded_label(
            "<b>Reference:</b> Ricke, K., Drouet, L., Caldeira, K. et al. <i>Country-level social cost of carbon.</i> "
            "Nature Clim Change 8, 895-900 (2018). <a href='https://doi.org/10.1038/s41558-018-0282-y' style='color: palette(highlight);'>"
            "doi:10.1038/s41558-018-0282-y</a>",
            top=0,
            bottom=10,
        )
        _ref_lbl.setOpenExternalLinks(True)
        layout.addRow(_ref_c)

        self.form, _saved = layout, self.form
        try:
            build_form(self, RICKE_FIELDS)
            self._field_map.pop("usd_to_local_rate", None)
            self._field_map.pop("country_iso3", None)
            self._field_map.pop("ssp_scenario", None)
            self._field_map.pop("rcp_scenario", None)
            self._field_map.pop("ricke_run", None)
            self._field_map.pop("cpi_ratio", None)
        finally:
            self.form = _saved

        # Populate country combo from explorer
        self._ricke_iso3_from_display = {}
        self._ricke_display_from_iso3 = {}
        explorer = _get_explorer()
        if explorer:
            self._populate_country_combo(explorer)
        else:
            self.country_iso3.addItem("-- Dataset unavailable --")

        # Set default before connecting signals to avoid firing into a half-built widget
        self.cpi_ratio.blockSignals(True)
        self.cpi_ratio.setValue(1.0)
        self.cpi_ratio.blockSignals(False)

        self._ricke_layout = layout
        self._usd_row = self._find_row_for_widget(layout, self.usd_to_local_rate)

        _rrc, self._ricke_result_lbl = self._padded_label(top=6, bottom=4)
        layout.addRow(_rrc)

        self.usd_to_local_rate.valueChanged.connect(self._update_ricke_result)
        self.country_iso3.currentIndexChanged.connect(self._update_ricke_result)
        self.ssp_scenario.currentIndexChanged.connect(self._update_ricke_result)
        self.rcp_scenario.currentIndexChanged.connect(self._update_ricke_result)
        self.ricke_run.currentIndexChanged.connect(self._update_ricke_result)
        self.cpi_ratio.valueChanged.connect(self._update_ricke_result)
        return w

    def _populate_country_combo(self, explorer):
        try:
            from ...utils.countries_data import data as _countries_data
            iso3_to_name = {c["COUNTRY_CODE"]: c["COUNTRY"].title() for c in _countries_data}
        except Exception:
            iso3_to_name = {}

        for iso3 in explorer.get_available_values("ISO3"):
            name = iso3_to_name.get(iso3, iso3)
            display = f"{name} ({iso3})"
            self._ricke_iso3_from_display[display] = iso3
            self._ricke_display_from_iso3[iso3] = display

        self.country_iso3.addItems(sorted(self._ricke_iso3_from_display))

    def _build_custom_panel(self):
        w = QWidget()
        layout = self._make_panel_layout(w)

        self.form, _saved = layout, self.form
        try:
            build_form(self, CUSTOM_FIELDS)
            self._field_map.pop("scc_value", None)
        finally:
            self.form = _saved

        self.scc_value.valueChanged.connect(self._update_custom_result)
        return w

    # ── Stack height ──────────────────────────────────────────────────────────

    def _fit_stack(self):
        """Lock the stack to exactly its current panel's natural height."""
        w = self._stack.currentWidget()
        if w:
            self._stack.setFixedHeight(max(w.sizeHint().height(), 0))
            self._stack.updateGeometry()

    # ── Mode switching ────────────────────────────────────────────────────────

    def _on_mode_changed(self, _idx=0):
        if self._suppress_signals:
            return
        mode = self.source.currentText()

        # Release the fixed height BEFORE the panel swap - otherwise Qt stretches
        # the new (shorter) panel's rows to fill the old panel's locked height.
        self._stack.setMaximumHeight(16777215)
        self._stack.setMinimumHeight(0)

        if _MODE_NITI in mode:
            self._stack.setCurrentIndex(0)
            self._update_niti_result()
        elif _MODE_RICKE in mode:
            self._stack.setCurrentIndex(1)
            self._update_ricke_result()
        else:
            self._stack.setCurrentIndex(2)
            self._update_custom_result()

        QTimer.singleShot(0, self._fit_stack)

    # ── Calculations ──────────────────────────────────────────────────────────

    def _toggle_currency_rows(self):
        cur = str(self._project_currency or "").strip().upper()

        if hasattr(self, '_inr_row') and self._inr_row >= 0:
            self._niti_layout.setRowVisible(self._inr_row, cur != "INR")

        if hasattr(self, '_usd_row') and self._usd_row >= 0:
            self._ricke_layout.setRowVisible(self._usd_row, cur != "USD")

    def _update_niti_result(self):
        if self._suppress_signals:
            return
        cur = str(self._project_currency or "INR").strip().upper()
        rate = self.inr_to_local_rate.value() if cur != "INR" else 1.0
        val = NITI_AAYOG_SCC_INR * rate

        if cur == "INR":
            self._niti_result_lbl.setText(
                f"NITI Aayog Base: <b>{fmt(NITI_AAYOG_SCC_INR)} INR/kgCO₂e</b>"
            )
        else:
            self._niti_result_lbl.setText(
                f"NITI Aayog Base: <b>{fmt(NITI_AAYOG_SCC_INR)} INR/kgCO₂e</b><br/>"
                f"Adjusted Local Cost: <b>{fmt(val)} {cur}/kgCO₂e</b>"
            )

        self._set_result(
            val,
            mode=_MODE_NITI,
            base_price=NITI_AAYOG_SCC_INR,
            base_unit="INR/kgCO₂e",
            conversion_rate=rate,
            rate_unit=f"{cur}/INR",
        )
        self._on_field_changed()

    def _update_ricke_result(self):
        if self._suppress_signals:
            return

        display = self.country_iso3.currentText()
        iso3 = self._ricke_iso3_from_display.get(display, "")
        ssp_key = _SSP_TO_KEY.get(self.ssp_scenario.currentText(), "")
        rcp_key = _RCP_TO_KEY.get(self.rcp_scenario.currentText(), "")
        run_key = _RUN_TO_KEY.get(self.ricke_run.currentText(), "bhm_sr")
        usd_rate = self.usd_to_local_rate.value()
        cur = str(self._project_currency or "USD").strip().upper()

        cpi_factor = self.cpi_ratio.value() if self.cpi_ratio.value() > 0 else 1.0

        explorer = _get_explorer()
        self._ricke_base_usd = 0.0
        error_msg = None

        if not explorer:
            error_msg = f"Dataset unavailable: {_explorer_load_error}"
        elif not iso3:
            error_msg = "Select a country to get the SCC estimate."
        elif not ssp_key or not rcp_key:
            error_msg = "Select a valid SSP and RCP scenario."
        else:
            results = explorer.get_scc(ISO3=iso3, SSP=ssp_key, RCP=rcp_key, run=run_key)
            if results.empty:
                error_msg = (
                    f"No data found for {iso3} / {ssp_key} / {rcp_key.upper()} / {run_key}."
                )
            else:
                # Dataset unit is USD/tCO₂; divide by 1000 to get USD/kgCO₂e.
                # Take median of the 50th-percentile column across all discount-rate rows.
                self._ricke_base_usd = float(results["50%"].median()) / 1000.0

        # CPI-inflated USD value (2005 USD → present year)
        inflated_usd = self._ricke_base_usd * cpi_factor
        val = inflated_usd * usd_rate

        if error_msg:
            self._ricke_result_lbl.setText(
                f"<span style='color:gray;'>{error_msg}</span>"
            )
            self._set_result(
                0.0,
                mode=_MODE_RICKE,
                base_price=0.0,
                base_unit="USD/kgCO₂e (2018)",
                conversion_rate=usd_rate,
                rate_unit=f"{cur}/USD",
            )
        else:
            lines = [
                f"Scenario Estimate ({iso3}, {ssp_key}/{rcp_key.upper()}/{run_key}): "
                f"<b>${fmt(self._ricke_base_usd)} USD/kgCO₂e</b> (2018 USD)"
            ]
            if cpi_factor != 1.0:
                lines.append(
                    f"CPI-inflated: <b>${fmt(inflated_usd)} USD/kgCO₂e</b> "
                    f"(×{fmt(cpi_factor)} factor)"
                )
            if cur != "USD":
                lines.append(f"Adjusted Local Cost: <b>{fmt(val)} {cur}/kgCO₂e</b>")
            self._ricke_result_lbl.setText("<br/>".join(lines))
            self._set_result(
                val,
                mode=_MODE_RICKE,
                base_price=inflated_usd,
                base_unit="USD/kgCO₂e",
                conversion_rate=usd_rate,
                rate_unit=f"{cur}/USD",
            )
        self._on_field_changed()

    def _update_custom_result(self):
        if self._suppress_signals:
            return
        val = self.scc_value.value()
        cur = self._project_currency or ""
        self._set_result(
            val,
            mode=_MODE_CUSTOM,
            base_price=val,
            base_unit=f"{cur}/kgCO₂e",
            conversion_rate=1.0,
            rate_unit="(direct entry)",
        )
        self._on_field_changed()

    def _set_result(self, value, mode=None, base_price=None, base_unit=None, conversion_rate=None, rate_unit=None):
        cur = self._project_currency or ""
        if mode is not None and base_price is not None and conversion_rate is not None:
            lines = [
                f"<b>Selected Mode:</b> {mode}",
                f"<b>Base Price:</b> {fmt(base_price)} {base_unit}",
            ]
            if rate_unit not in ("INR/INR", "USD/USD"):
                lines.append(f"<b>Conversion Rate:</b> {fmt(conversion_rate)} {rate_unit}")
            lines.append(f"<b>Effective SCC:</b> {fmt(value)} {cur}/kgCO₂e")
            self._result_lbl.setText("<br/>".join(lines))
        else:
            self._result_lbl.setText(f"<b>Effective SCC: {fmt(value)} {cur}/kgCO₂e</b>")

    # ── Global sync ───────────────────────────────────────────────────────────

    def _sync_with_global_settings(self):
        if not self.controller or not self.controller.engine:
            return
        info = self.controller.engine.fetch_chunk(GLOBAL_CHUNK) or {}
        raw_cur = info.get("project_currency", "INR")
        self._project_currency = str(raw_cur).strip().upper() if raw_cur else "INR"
        rate_usd = float(info.get("currency_to_usd_rate", 1.0))

        self.usd_to_local_rate.setSuffix(f" {self._project_currency}/USD")
        self.inr_to_local_rate.setSuffix(f" {self._project_currency}/INR")
        self.scc_value.setSuffix(f" {self._project_currency}/kgCO₂e")

        self._suppress_signals = True
        if rate_usd > 0:
            self.usd_to_local_rate.setValue(1.0 / rate_usd)
        if self._project_currency == "INR":
            self.inr_to_local_rate.setValue(1.0)
        self._suppress_signals = False

        self._toggle_currency_rows()
        self._on_mode_changed()

    # ── Data ──────────────────────────────────────────────────────────────────

    def collect_data(self):
        cur = self._project_currency
        mode = self.source.currentText()

        niti_rate = 1.0 if cur == "INR" else self.inr_to_local_rate.value()
        niti_val = NITI_AAYOG_SCC_INR * niti_rate

        iso3_display = self.country_iso3.currentText()
        iso3 = self._ricke_iso3_from_display.get(iso3_display, "")
        ssp = self.ssp_scenario.currentText()
        rcp = self.rcp_scenario.currentText()
        run_display = self.ricke_run.currentText()
        run_key = _RUN_TO_KEY.get(run_display, "bhm_sr")
        ssp_key = _SSP_TO_KEY.get(ssp, "")
        rcp_key = _RCP_TO_KEY.get(rcp, "")
        usd_base = self._ricke_base_usd  # set by _update_ricke_result
        cpi_factor = self.cpi_ratio.value() if self.cpi_ratio.value() > 0 else 1.0
        inflated_usd = usd_base * cpi_factor
        usd_rate = self.usd_to_local_rate.value()
        ricke_val = inflated_usd * usd_rate

        custom_val = self.scc_value.value()

        final = (
            niti_val
            if _MODE_NITI in mode
            else ricke_val if _MODE_RICKE in mode else custom_val
        )

        return {
            "source": mode,
            "niti": {
                "base_value_inr": NITI_AAYOG_SCC_INR,
                "inr_to_local_rate": niti_rate,
                "cost_local": round(niti_val, DECIMAL_PLACES),
                "currency": cur,
            },
            "ricke": {
                "country_iso3": iso3,
                "ssp": ssp,
                "ssp_key": ssp_key,
                "rcp": rcp,
                "rcp_key": rcp_key,
                "run": run_key,
                "base_value_usd": usd_base,
                "cpi_ratio": round(cpi_factor, DECIMAL_PLACES),
                "inflated_value_usd": round(inflated_usd, DECIMAL_PLACES),
                "usd_to_local_rate": usd_rate,
                "cost_local": round(ricke_val, DECIMAL_PLACES),
                "currency": cur,
            },
            "custom": {
                "entered_value": custom_val,
                "currency": cur,
                "unit": f"{cur}/kgCO₂e",
            },
            "result": {
                "selected_mode": mode,
                "base_price": (
                    NITI_AAYOG_SCC_INR if _MODE_NITI in mode
                    else usd_base if _MODE_RICKE in mode
                    else custom_val
                ),
                "base_price_unit": (
                    "INR/kgCO₂e" if _MODE_NITI in mode
                    else "USD/kgCO₂e" if _MODE_RICKE in mode
                    else f"{cur}/kgCO₂e"
                ),
                "conversion_rate": (
                    niti_rate if _MODE_NITI in mode
                    else usd_rate if _MODE_RICKE in mode
                    else 1.0
                ),
                "cost_of_carbon_local": round(final, DECIMAL_PLACES),
                "currency": cur,
                "unit": f"{cur}/kgCO₂e",
            },
        }

    # ── Base overrides ────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        if not self._synced:
            self._synced = True
            self._sync_with_global_settings()

    def _on_field_changed(self):
        if self._loading or self._suppress_signals:
            return
        if self.controller and self.controller.engine and self.chunk_name:
            self.controller.engine.stage_update(
                chunk_name=self.chunk_name, data=self.collect_data()
            )
        self.data_changed.emit()

    def get_data_dict(self):
        return self.collect_data()

    def refresh_from_engine(self):
        if not self.controller or not self.controller.engine:
            return
        if not self.controller.engine.is_active() or not self.chunk_name:
            return
        data = self.controller.get_chunk(self.chunk_name)
        if not data or data == self._loaded_data:
            self._sync_with_global_settings()
            return
        self._loaded_data = data
        self.load_data_dict(data)
        self._sync_with_global_settings()

    def load_data_dict(self, data):
        if not data:
            return
        self._loading = True
        try:
            self.source.blockSignals(True)
            idx = self.source.findText(data.get("source", _MODE_NITI))
            self.source.setCurrentIndex(idx if idx >= 0 else 0)
            self.source.blockSignals(False)

            niti = data.get("niti", {})
            self.inr_to_local_rate.blockSignals(True)
            self.inr_to_local_rate.setValue(float(niti.get("inr_to_local_rate", 1.0)))
            self.inr_to_local_rate.blockSignals(False)

            ricke = data.get("ricke", {})
            self.usd_to_local_rate.blockSignals(True)
            self.usd_to_local_rate.setValue(float(ricke.get("usd_to_local_rate", 1.0)))
            self.usd_to_local_rate.blockSignals(False)

            # Restore country
            self.country_iso3.blockSignals(True)
            iso3 = ricke.get("country_iso3", "")
            display = self._ricke_display_from_iso3.get(iso3, "")
            i = self.country_iso3.findText(display) if display else -1
            self.country_iso3.setCurrentIndex(i if i >= 0 else 0)
            self.country_iso3.blockSignals(False)

            self.ssp_scenario.blockSignals(True)
            i = self.ssp_scenario.findText(ricke.get("ssp", _SSP_OPTIONS[0]))
            self.ssp_scenario.setCurrentIndex(i if i >= 0 else 0)
            self.ssp_scenario.blockSignals(False)

            self.rcp_scenario.blockSignals(True)
            i = self.rcp_scenario.findText(ricke.get("rcp", _RCP_OPTIONS[0]))
            self.rcp_scenario.setCurrentIndex(i if i >= 0 else 0)
            self.rcp_scenario.blockSignals(False)

            # Restore damage function run
            self.ricke_run.blockSignals(True)
            run_display = _RUN_FROM_KEY.get(ricke.get("run", "bhm_sr"), _RUN_OPTIONS[0])
            i = self.ricke_run.findText(run_display)
            self.ricke_run.setCurrentIndex(i if i >= 0 else 0)
            self.ricke_run.blockSignals(False)

            self.cpi_ratio.blockSignals(True)
            self.cpi_ratio.setValue(float(ricke.get("cpi_ratio", 1.0)))
            self.cpi_ratio.blockSignals(False)

            custom = data.get("custom", {})
            self.scc_value.blockSignals(True)
            self.scc_value.setValue(float(custom.get("entered_value", 0.0)))
            self.scc_value.blockSignals(False)
        finally:
            self._loading = False

        self._suppress_signals = True
        self._on_mode_changed()
        self._suppress_signals = False

    def validate(self) -> dict:
        clear_field_styles(HEADER_FIELDS + NITI_FIELDS + RICKE_FIELDS + CUSTOM_FIELDS, self)

        data = self.collect_data()
        errors = []
        warnings = []
        mode = data.get("source", "")
        result = data.get("result", {})

        if _MODE_RICKE in mode:
            ricke = data.get("ricke", {})

            # validate_form handles required selection_none combos (country, SSP, RCP, run)
            _fr = validate_form(RICKE_FIELDS, self)
            errors.extend(_fr["errors"])
            warnings.extend(_fr["warnings"])

            # Only check dataset result when all selectors are filled (avoids redundant error)
            if (
                ricke.get("country_iso3")
                and ricke.get("ssp_key")
                and ricke.get("rcp_key")
                and ricke.get("base_value_usd", 0.0) == 0.0
            ):
                errors.append(
                    f"No data found for the selected combination ({ricke.get('country_iso3', '')}, "
                    f"{ricke.get('ssp_key', '')}, {ricke.get('rcp_key', '').upper()}, {ricke.get('run', '')}) - "
                    "try a different SSP, RCP, or damage function"
                )
                _apply_border_style(self.ssp_scenario, get_token("danger"))
                _apply_border_style(self.rcp_scenario, get_token("danger"))
                _apply_border_style(self.ricke_run, get_token("danger"))

            if ricke.get("usd_to_local_rate", 0.0) == 0.0:
                warnings.append(
                    "USD Conversion Rate is 0 - the social cost of carbon will compute to 0 in local currency; "
                    "enter the current USD-to-local exchange rate"
                )
                _apply_border_style(self.usd_to_local_rate, get_token("warning"))

            if ricke.get("cpi_ratio", 1.0) <= 0.0:
                warnings.append(
                    "CPI Inflation Ratio must be positive - leave at 1.0 to use 2018 USD values as-is, "
                    "or enter (present year CPI) / (2018 CPI) to inflate to current prices"
                )
                _apply_border_style(self.cpi_ratio, get_token("warning"))

        elif _MODE_NITI in mode:
            niti = data.get("niti", {})
            if niti.get("currency", "INR") != "INR" and niti.get("inr_to_local_rate", 0.0) == 0.0:
                warnings.append(
                    "INR Conversion Rate is 0 - the NITI Aayog social cost of carbon will compute to 0 "
                    "in local currency; enter the current INR-to-local exchange rate"
                )
                _apply_border_style(self.inr_to_local_rate, get_token("warning"))

        elif _MODE_CUSTOM in mode:
            if data.get("custom", {}).get("entered_value", 0.0) <= 0.0:
                warnings.append(
                    "Social Cost of Carbon is 0 - no carbon cost will be applied to emissions; "
                    "enter a positive SCC value"
                )
                _apply_border_style(self.scc_value, get_token("warning"))

        # Fallback: only fire when no mode-specific issue already explains why SCC is 0
        if not errors and not warnings and result.get("cost_of_carbon_local", 0.0) == 0.0:
            warnings.append(
                "Effective Social Cost of Carbon is 0 - no carbon cost will be applied to emissions"
            )

        return {"errors": errors, "warnings": warnings}

    def freeze(self, frozen: bool = True):
        freeze_widgets(frozen, self.btn_clear)
        freeze_form(
            HEADER_FIELDS + NITI_FIELDS + RICKE_FIELDS + CUSTOM_FIELDS,
            self,
            frozen,
        )

    def clear_all(self):
        if not confirm_clear_all(self):
            return

        self._suppress_signals = True
        self.source.setCurrentIndex(0)
        self.inr_to_local_rate.setValue(1.0)
        self.usd_to_local_rate.setValue(1.0)
        self.country_iso3.setCurrentIndex(0)
        self.ssp_scenario.setCurrentIndex(0)
        self.rcp_scenario.setCurrentIndex(0)
        self.ricke_run.setCurrentIndex(0)
        self.cpi_ratio.setValue(1.0)
        self.scc_value.setValue(0.0)
        self._ricke_base_usd = 0.0
        self._suppress_signals = False
        self._on_mode_changed()
        self._on_field_changed()

    def get_data(self) -> dict:
        return {"chunk": CHUNK, "data": self.get_data_dict()}
