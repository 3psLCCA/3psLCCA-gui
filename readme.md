<div align="center">

<img src="./src/three_ps_lcca_gui/gui/assets/logo/logo-3psLCCA-dark.svg" alt="3psLCCA Logo" width="480"/>

<!-- # 3psLCCA -->

<!-- ### Bridge Life Cycle Cost Analysis -->

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-GUI-41CD52?style=flat-square&logo=qt&logoColor=white)](https://doc.qt.io/qtforpython/)
[![Version](https://img.shields.io/badge/version-1.0.0-blue?style=flat-square)](https://github.com/swas02/3psLCCA-gui/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey?style=flat-square&logo=windows&logoColor=white)](https://github.com/swas02/3psLCCA-gui)
[![Conda](https://img.shields.io/badge/conda--forge-available-44A833?style=flat-square&logo=anaconda&logoColor=white)](https://conda-forge.org/)
[![LaTeX](https://img.shields.io/badge/PDF%20Reports-LaTeX-008080?style=flat-square&logo=latex&logoColor=white)](https://miktex.org/)
[![Maintained](https://img.shields.io/badge/maintained-yes-brightgreen?style=flat-square)](https://github.com/swas02/3psLCCA-gui/commits/main)

**3psLCCA** is a desktop application for evaluating the full economic life cycle of bridge infrastructure — from construction through maintenance, traffic disruption, carbon impact, and end-of-life recycling — with professional PDF report output.

[Features](#-features) · [Installation](#-installation) · [Running the App](#-running-the-app) · [Development Setup](#-development-setup) · [PDF Reports](#-pdf-report-generation) · [Troubleshooting](#-troubleshooting)

</div>

---

## ✨ Features

| Module | Description |
|---|---|
| 🏗️ **Bridge & Project Data** | Dimensions, design life, construction schedule, country, agency |
| 💰 **Financial Parameters** | Discount rate, inflation, interest rates, investment ratios |
| 🧱 **Structure Work Data** | Bill of quantities — foundation, sub-structure, super-structure, misc |
| 🔧 **Maintenance & Repair** | Routine inspection, periodic/major maintenance, bearing & joint replacement |
| 🚗 **Traffic & Road Costs** | Vehicle counts, road user costs, accident rates, work-zone multipliers |
| 🏚️ **Demolition** | End-of-life cost and carbon cost as % of construction value |
| 🌿 **Carbon Emissions** | Machinery, material transport, traffic diversion, and social cost of carbon |
| ♻️ **Recyclability** | Scrap/salvage value of materials at demolition |
| 📊 **Outputs & Reports** | LCCA summary charts, PDF/LaTeX reports, Excel export |

---

## 📦 Installation

### Recommended — Conda (includes portable LaTeX for PDF reports)

> Requires [Miniconda](https://docs.conda.io/en/latest/miniconda.html) installed.

**Step 1 — Configure channels** *(run once)*

```bash
conda config --remove channels defaults
conda config --add channels conda-forge
conda config --add channels osdag
conda config --add channels zehen-249
```

**Step 2 — Create and activate the environment**

```bash
conda create -n 3pslcca
conda activate 3pslcca
```

**Step 3 — Install**

```bash
conda install three-ps-lcca-gui
```

---

### Lightweight — Python venv

> PDF reports require a separately installed [MiKTeX](https://miktex.org/) (added to PATH).

```bash
# 1. Create and activate virtual environment
python -m venv venv
source venv/bin/activate        # Linux / macOS
venv\Scripts\activate           # Windows

# 2. Clone the repos
git clone https://github.com/3psLCCA/3psLCCA-gui.git
cd 3psLCCA-gui
git clone https://github.com/3psLCCA/3psLCCA-core.git

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
cd src
python -m three_ps_lcca_gui.gui.main
```

<details>
<summary><b>Windows PowerShell — script execution error?</b></summary>

Run once in PowerShell as Administrator, then retry activation:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

</details>

---

## 🚀 Running the App

```bash
conda activate 3pslcca
threePSLCCA
```

> Re-activate the environment every time you open a new terminal.

---

## 🔄 Updating

```bash
conda activate 3pslcca
git pull origin main
conda env update -f environment.yml --prune
pip install --upgrade git+https://github.com/swas02/3psLCCA-core.git@main
pip install -e .
threePSLCCA
```

---

## 🛠️ Development Setup

```bash
# Clone
git clone https://github.com/swas02/3psLCCA-gui.git
cd 3psLCCA-gui

# Create environment from file
conda env create -f environment.yml -n 3pslcca
conda activate 3pslcca

# Install in editable mode
pip install -e .

# Run
threePSLCCA
```

### Internal Dev Tools

```bash
python devtools/launcher.py
```

| Tool | Purpose |
|---|---|
| **WPI Database** | Manage Wholesale Price Index data |
| **Catalog Builder** | Rebuild material and section catalogs |
| **Project Inspector** | Repair and inspect `.3ps` project files |

---

## 📄 PDF Report Generation

| Setup | LaTeX |
|---|---|
| **Conda** | Portable LaTeX bundled — no extra setup |
| **venv / manual** | Install [MiKTeX](https://miktex.org/) and add to system `PATH` |

---

## ❓ Troubleshooting

<details>
<summary><b>SSL Error on Windows (CondaSSLError / record layer failure)</b></summary>

```bash
conda config --set ssl_verify false
conda env create -f environment.yml
```

> Disconnect any active VPN and retry if the error persists.

</details>

<details>
<summary><b>App won't launch after update</b></summary>

```bash
conda activate 3pslcca
pip install -e .
threePSLCCA
```

</details>

---

## 🗑️ Uninstall

```bash
conda deactivate
conda env remove -n 3pslcca
```

---

## 🏗️ Project Structure

```
3psLCCA-gui/
├── src/three_ps_lcca_gui/
│   ├── gui/               # PySide6 UI components
│   ├── core/              # Report generation (LaTeX/PDF)
│   └── code_to_latex/     # Data → LaTeX converters
├── 3psLCCA-core/          # Calculation engine (submodule)
├── devtools/              # Internal admin tools
└── environment.yml        # Conda environment spec
```

---

## 📬 Contact & Credits

Developed by the [Osdag](https://osdag.fossee.in) team at IIT Bombay under FOSSEE.

---

<div align="center">
<sub>Built with PySide6 · LaTeX · matplotlib · pandas</sub>
</div>
