from pylatex import NoEscape
from pylatex.utils import escape_latex

from ..gui.components.maintenance.main import MAINTENANCE_FIELDS
from ..gui.components.outputs.data_preparer import DataPreparer
from ..gui.components.utils.form_builder.form_definitions import FieldDef
from ..gui.components.utils.form_builder.percent_or_value import resolve_per_or_val
from ..gui.project_controller import ProjectController
from .common_code import fields_to_latex

CHUNK = "maintenance_data"


def _bases(controller: ProjectController) -> dict:
    """Base amount for each percent_of key; None when it can't be worked out."""
    cw = controller.get_chunk("construction_work_data") or {}
    ce = controller.get_chunk("carbon_emission_data") or {}

    def safe(fn):
        try:
            return fn()
        except (AttributeError, TypeError, ValueError):
            return None

    return {
        "initial_construction_cost": safe(lambda: float(cw.get("grand_total"))),
        "superstructure_cost": safe(lambda: float(cw.get("Super-Structure").get("total"))),
        "initial_carbon_emissions": safe(lambda: DataPreparer._total_kgco2e(ce)),
    }


def _fmt(x: float, decimals: int) -> str:
    s = f"{x:,.{decimals}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _per_or_val_text(f: FieldDef, raw, base) -> NoEscape | None:
    """'2,500 (25% of initial construction cost)'; None when blank."""
    pct, amount = resolve_per_or_val(raw, base)
    if pct is None and amount is None:
        return None
    of = f.percent_of.replace("_", " ")
    unit = escape_latex(f.unit).replace("₂", r"\textsubscript{2}")
    pct_text = escape_latex(f"{_fmt(pct, 3)}% of {of}") if pct is not None else ""
    if amount is None:
        return NoEscape(pct_text)
    text = f"{escape_latex(_fmt(amount, 2))} {unit}".rstrip()
    return NoEscape(f"{text} ({pct_text})" if pct_text else text)


def maintenance_data_to_latex(controller: ProjectController) -> str:
    data = dict(controller.get_chunk(CHUNK))
    bases = _bases(controller)
    overrides = {}
    for f in MAINTENANCE_FIELDS:
        if isinstance(f, FieldDef) and f.field_type == "per_or_val":
            data[f.key] = _per_or_val_text(f, data.get(f.key), bases.get(f.percent_of))
            overrides[f.key] = ""  # unit is already in the text
    return fields_to_latex(MAINTENANCE_FIELDS, data, "Maintenance Data Summary",
                           "tab:maintenance_data", unit_overrides=overrides)
