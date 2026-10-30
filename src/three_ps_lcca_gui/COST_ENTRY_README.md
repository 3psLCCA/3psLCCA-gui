# Maintenance & Demolition costs: percentage or amount

The web app (3pslcca-web-v2) lets the 9 Maintenance / Demolition cost fields be entered either
as a percentage (as here) or as an amount. This note is what the desktop app needs to change to
save and read the same format.

## Format

Today the desktop saves a bare percentage:

```json
"major_inspection_cost": 0.5
```

The web saves one object per key, at the same key:

```json
"major_inspection_cost": { "mode": "percent", "percent": 0.5, "amount": null }
"bearing_exp_joint_cost": { "mode": "amount", "percent": null, "amount": 818724.32 }
```

- `mode`: `"percent"` or `"amount"`, the one the user entered.
- `percent`: the percentage when `mode` is `"percent"`, else `null`.
- `amount`: the amount when `mode` is `"amount"`, else `null`. A currency amount, or kgCO₂e for the carbon keys.

Only the side `mode` names is stored. The other is worked out from the live base when needed,
so it never goes stale when the structure, transport or machinery data change.

## The 9 keys

Key names are unchanged, so a file opens in both apps.

| Chunk | Key | Percentage of (base) | Amount is |
| :--- | :--- | :--- | :--- |
| maintenance_data | `routine_inspection_cost` | initial construction cost | currency per inspection |
| maintenance_data | `periodic_maintenance_cost` | initial construction cost | currency per maintenance |
| maintenance_data | `periodic_maintenance_carbon_cost` | initial carbon emissions | kgCO₂e per maintenance |
| maintenance_data | `major_inspection_cost` | initial construction cost | currency per inspection |
| maintenance_data | `major_repair_cost` | initial construction cost | currency per repair |
| maintenance_data | `major_repair_carbon_cost` | initial carbon emissions | kgCO₂e per repair |
| maintenance_data | `bearing_exp_joint_cost` | superstructure cost | currency per replacement |
| demolition_data | `demolition_cost_pct` | initial construction cost | currency |
| demolition_data | `demolition_carbon_cost_pct` | initial carbon emissions | kgCO₂e |

The `_freq` and `_duration` keys stay plain numbers.

The names are misleading now (`*_cost` holds a percentage, `*_pct` can hold an amount), but
they were right when the fields could only be a percentage. Renaming them needs both apps
changed together.

## The engine still takes a percentage

`outputs/data_preparer.py` (lines 203-234) passes each value straight to the engine with
`float(...)`. With the new format, turn the entry into a percentage first:

```python
def cost_percent(raw, base):
    """The percentage a stored cost stands for; None if empty or there is no base."""
    if isinstance(raw, (int, float)):          # older files: a bare percentage
        return float(raw)
    if not isinstance(raw, dict):
        return None
    if raw.get("mode") == "amount":
        amount = raw.get("amount")
        return None if amount is None or not base else amount / base * 100
    return raw.get("percent")
```

The bases, the same ones the engine multiplies the percentage by:

- **initial construction cost**: the grand total of all structure items.
- **superstructure cost**: the superstructure total.
- **initial carbon emissions**: material + transport + machinery emissions, in kgCO₂e. The
  engine's carbon cost is these × the social cost of carbon, so a share of the kgCO₂e is the
  same share of the cost.

An amount with a base of 0 can't be turned into a percentage: the web shows an error and does
not run. An amount larger than its base is also an error.

## Older files

Files from before this change hold bare numbers. They are always percentages, whatever the key
name says. The web wraps them on import (`src/workers/cherryfix/costEntryFix.js`); the desktop
reader should do the same, as `cost_percent` above does.

## Fix while here: wrong unit labels in `maintenance/main.py`

These say `(% of initial construction cost)`, which contradicts their own explanations and the
engine fields in `data_preparer.py`:

| Key | Line | Should be |
| :--- | :--- | :--- |
| `periodic_maintenance_carbon_cost` | 82 | `(% of initial carbon emissions)` |
| `major_repair_carbon_cost` | 157 | `(% of initial carbon emissions)` |
| `bearing_exp_joint_cost` | 203 | `(% of superstructure cost)` |

`demolition/main.py` uses `(%)` for both demolition costs; the web shows
`(% of initial construction cost)` and `(% of initial carbon emissions)`.

## Per event, not per year

The routine engine fields are named `percentage_of_initial_construction_cost_per_year`, but
the engine charges the percentage once per inspection / maintenance, at every interval
(3psLCCA-core `core/stage_cost/stage_cost.py` 270-272, 321-328). So an amount is "per
inspection" / "per maintenance", whatever the frequency.
