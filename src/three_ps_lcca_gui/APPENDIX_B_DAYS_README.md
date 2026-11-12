# Report Appendix B: days per month, not working days

Appendix B (Calculation Methodology) multiplies every road user cost and rerouting emission
formula by $D_{wm}$, "Number of working days in a month". Neither the engine nor the current
workbook does that: they use **days per month** (`bridge_data.days_per_month`, workbook
`Input_Steel!D12`, "this value is required for the RUC"). Working days in a month
(`working_days_per_month`, workbook `Input_Steel!D11`) are not used for road user cost at all.

## Where it is

The same text is in two files:

- `report/sections/appendix_B_content.py`
- `code_to_latex/pdf_generation_v3/appendix_B_content.py`

Line 25 (glossary):

```latex
\item $D_{wm}$ = Number of working days in a month
```

and 20 formulas: $VOC$, $VOT$, $A_{Tn}$ and $VEC$ for construction, major repair, bearing and
expansion joint replacement, demolition for reconstruction, reconstruction and end-of-life
demolition (lines 154, 443, 462, 478, 528-747).

## Fix

The web app (3pslcca-web-v2, `src/views/gui/outputs/report/static/appendices.js`) renamed the
symbol and its meaning:

```latex
\item $D_{m}$ = Number of days in a month the traffic is affected
```

and replaced every `D_{wm}` with `D_{m}`. Do the same in both files above.

## Why

- **Engine** (3psLCCA-core): affected days are `months × days_per_month` for construction,
  major repair, demolition and reconstruction (`core/stage_cost/stage_cost.py` 706, 449-451,
  660-665, 843-846). `working_days_per_month` is only validated (`inputs/input.py` 46-47,
  52-53, at most `days_per_month`) and never used in a result.
- **Workbook**: `LCC_calculations!D13 = Input_Steel!D12` drives the construction period in
  days (`D39 = D11*D13`) and the vehicles affected during construction (`J40`), major repairs
  (`J73`) and demolition (`D131`). The rerouting carbon (`J42`, `J74`, `D132`) and the three
  `Road_User_Cost_*` sheets (`E24`) read `Input_Steel!D12` directly.
- **Working days** in the workbook only set the site-office electricity hours
  (`Steel_Env_Cost_2!E37 = D10 * D11 * 12`), which end up in the initial carbon emissions.
  In the app, the "Site office (If Grid electricity is used)" machinery row has its own hours
  and days, so `working_days_per_month` feeds nothing. Only the abandoned
  `LCC_calculations_not_required` sheet multiplied road user cost by working days, which is
  where $D_{wm}$ came from.

## Not fixed yet

The same formulas also use $DC_m$ ("Duration of construction in months") for every period.
The engine uses each period's own duration:

| Period | Engine affected days |
| :--- | :--- |
| Construction, reconstruction | `construction_period_months × days_per_month` |
| Major repair | `repairs_duration_months × days_per_month` |
| Demolition | `duration_for_demolition_and_disposal_in_months × days_per_month` |
| Bearing & expansion joint replacement | `duration_of_replacement_in_days` (no days per month) |

So the major repair, replacement and demolition formulas should use their own duration, and
the replacement ones should drop $D_{m}$. This is still open in both apps.
