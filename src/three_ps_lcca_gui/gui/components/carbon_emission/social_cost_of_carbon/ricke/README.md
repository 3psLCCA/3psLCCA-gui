# Country-level Social Cost of Carbon (CSCC) Explorer

This module provides an interface to the dataset from Ricke et al. (2018), "Country-level Social Cost of Carbon", published in *Nature Climate Change*.

## Dataset Overview
The Social Cost of Carbon (SCC) is an estimate of the economic damages (in USD) caused by emitting one additional tonne of carbon dioxide. This dataset provides these estimates at a **country level** (ISO3 codes) across various climate, socioeconomic, and discounting scenarios.

## Methodology
- **Damage Functions:** Based on Burke, Hsiang, and Miguel (BHM 2015) and Dell, Jones, and Olken (DJO).
- **Projections:** Uses SSP (Shared Socioeconomic Pathways) and RCP (Representative Concentration Pathways).
- **Discounting:** Includes both fixed rates and growth-adjusted rates.

## Parameters
| Parameter | Description |
| :--- | :--- |
| `run` | Damage function specification (e.g., `bhm_sr`, `djo`) |
| `dmgfuncpar` | Statistical method (`bootstrap` or `estimates`) |
| `climate` | Climate uncertainty (`expected` or `uncertain`) |
| `SSP` | Socioeconomic pathway (SSP1 - SSP5) |
| `RCP` | Emissions scenario (rcp45, rcp60, rcp85) |
| `ISO3` | 3-letter country code |
| `prtp` | Pure Rate of Time Preference |
| `eta` | Elasticity of Marginal Utility |
| `dr` | Fixed discount rate (if not using growth-adjusted) |

## Usage

```python
import cscc_explorer as cscc

# Initialize the explorer
explorer = cscc.CSCCExplorer()

# Get a dictionary of all available options for all parameters
# Format: {'param_name': [list_of_values], ...}
all_options = explorer.get_options()
print(all_options['SSP'])  # ['SSP1', 'SSP2', ...]

# Get available values for a single parameter
countries = explorer.get_available_values('ISO3')

# Check if a specific country is available
print(explorer.is_country_available('USA'))  # True
print(explorer.is_country_available('XYZ'))  # False

# Query the Social Cost of Carbon
# Returns a DataFrame with the 16.7%, 50% (median), and 83.3% estimates
results = explorer.get_scc(
    ISO3='USA', 
    SSP='SSP2', 
    RCP='rcp60', 
    run='bhm_sr'
)
```

## Credits
Based on: Ricke, K., Drouet, L., Caldeira, K. & Tavoni, M. *Country-level social cost of carbon*. Nat. Clim. Chang. 8, 895–900 (2018).
DOI: [10.1038/s41558-018-0282-y](https://doi.org/10.1038/s41558-018-0282-y)
