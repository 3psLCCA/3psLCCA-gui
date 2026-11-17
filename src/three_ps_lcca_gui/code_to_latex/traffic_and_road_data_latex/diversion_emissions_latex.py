import pandas as pd
from pylatex import Command
from pylatex.utils import bold, escape_latex
from ...gui.components.traffic_data.main import _VEHICLES
from ..SETTINGS import DECIMAL_PLACES_FOR_LATEX
from ...gui.components.utils.common_requested_data import get_diversion_emissions_data
from ..html_to_latex import format_remarks_latex
from ..common_code import entered_value_block


def _diversion_emissions(data: dict) -> str:

    """Generates the Traffic Diversion Emissions LaTeX section."""
    vehicle_data = data.get("vehicle_data", {})
    em_data = get_diversion_emissions_data()
    mode = em_data.get("mode")

    diversion_latex = ""
    if mode == "Calculate by Vehicle":
        factors = em_data.get("emission_factors", {})
        reroute_km = float(data.get("additional_reroute_distance_km", 0.0))

        em_rows = []
        total_em = 0.0
        for key, label in _VEHICLES:
            vpd = int(vehicle_data.get(key, {}).get("vehicles_per_day", 0))
            factor = float(factors.get(key, 0.0))
            emissions = vpd * factor * reroute_km
            total_em += emissions
            em_rows.append({
                "Vehicle Type": label,
                "Vehicles / Day": vpd,
                "Factor (kg/veh-km)": factor,
                "Emissions (kg/day)": emissions
            })

        # Add total row
        em_rows.append({
            "Vehicle Type": r"\textbf{Total Daily Emissions}",
            "Vehicles / Day": None,
            "Factor (kg/veh-km)": None,
            "Emissions (kg/day)": total_em
        })

        df_em = pd.DataFrame(em_rows)
        diversion_latex = (
            df_em.style
            .hide(axis="index")
            .format({
                "Vehicles / Day": lambda x: f"{int(x)}" if x is not None else "",
                "Factor (kg/veh-km)": f"{{:.{DECIMAL_PLACES_FOR_LATEX}f}}",
                "Emissions (kg/day)": f"{{:.{DECIMAL_PLACES_FOR_LATEX}f}}"
            }, na_rep="")
            .to_latex(
                caption=f"Traffic Diversion Emissions (Detour: {reroute_km:.2f} km)",
                label="tab:diversion_emissions",
                hrules=True,
                column_format="lrrr",
                position="h!",
                position_float="centering",
            )
        ) or ""

    elif mode == "Enter Directly":
        direct = em_data.get("direct_entry", {})
        val = float(direct.get("total_direct_emissions", 0.0))
        source = (direct.get("source") or "").strip()
        comments = (direct.get("comments") or "").strip()

        source_sent = rf" This estimate is based on {escape_latex(source)}." if source else " Source not mentioned."
        comments_sent = rf" {escape_latex(comments)}" if comments else ""

        total_cell = (
            bold(f"{val:,.{DECIMAL_PLACES_FOR_LATEX}f}")
            + "~kgCO" + Command("textsubscript", "2").dumps() + "e/day"
        )
        paragraph = (
            "The total traffic diversion emissions, entered directly, amount to "
            + total_cell + "." + source_sent + comments_sent
        )

        rows = [
            ("Total Daily Diversion Emissions", total_cell),
            ("Source", escape_latex(source) if source else "Not mentioned"),
        ]
        if comments:
            rows.append(("Comments", escape_latex(comments)))

        diversion_latex = entered_value_block(paragraph, rows)

    if not diversion_latex:
        return ""

    remarks = format_remarks_latex(em_data)
    if remarks:
        diversion_latex += "\n\n" + remarks
    
    return diversion_latex
