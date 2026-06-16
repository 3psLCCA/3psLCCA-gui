# 3psLCCA Linux Segfault — Root Cause & Permanent Fix

**Status: FIXED.** Permanent fix applied and verified on this machine on 2026-06-16.

**Symptom:** On Linux, launching `threePSLCCA` printed
```
qt.qpa.plugin: Could not find the Qt platform plugin "wayland" in ""
Segmentation fault (core dumped)
```
The same install worked fine on Windows, and reportedly worked on Linux during earlier development.

---

## 1. Root Cause

`/home/renu/threePSLCCA` is a **conda environment** (prefix-based, confirmed via `conda-meta/`), not a plain `pip`/venv install. PySide6 (Qt for Python) inside this environment links against the environment's own shared **fontconfig** library rather than bundling a private copy — this is normal conda-forge packaging behavior (shared deps are centralized, not duplicated per package).

At some point this environment drifted onto **fontconfig 2.18.1** (conda-forge, confirmed via `conda-meta/fontconfig-2.18.1-h27c8c51_0.json`), while the host OS itself only has **fontconfig 2.15.0** (Ubuntu 24.04 system package). That 2.18.1 build has a real bug: when Qt's text layout engine needs a **fallback font** for a glyph that isn't covered by the app's active font, it asks fontconfig to search font charsets for one that covers the codepoint. That search crashes inside `FcCharSetFindLeafForward`.

> Note: an earlier draft of this doc said "2.17.0" — that number came from misreading the shared library filename `libfontconfig.so.1.17.0`. That `1.17.0` suffix is fontconfig's internal libtool/SONAME version, not its release version, and coincidentally looks like one. The `conda-meta` JSON file is the authoritative source: the actual installed package was **2.18.1**.

The app's UI is full of glyphs the bundled "Ubuntu" font doesn't cover — arrows (`↗ ↺ ↻ ↩ ▼ ›`), emoji (`🗂 🔒 🗑️ 🔍`), checkmarks (`✓ ✅ ❌`), and the subscript `₂` used throughout in "kg CO₂e" labels. Any of these triggers the font-fallback path and crashes. This was confirmed in total isolation, outside the app entirely:

```python
# 6-line repro, no app code involved
import sys
from PySide6.QtWidgets import QApplication, QPushButton
app = QApplication(sys.argv)
btn = QPushButton("Run Comparison ↗")   # crashed on .show() before the fix
btn.show()
app.processEvents()
```
Removing the `↗` glyph alone (plain `"Run Comparison"`) did **not** crash. Forcing `LD_PRELOAD` to the **system** `libfontconfig.so.1` (2.15.0) instead of the conda one also did **not** crash, for either the repro or the full app. That two-way isolation was the proof: it was a fontconfig 2.18.1 regression, not an app bug, and not a missing `libxcb-cursor0` (a similar-looking but different known PySide6 issue, ruled out — the conda env bundles its own xcb-cursor and resolved it fine via rpath).

This explains why Windows was unaffected (Windows uses DirectWrite/GDI for font fallback, no fontconfig involved at all), and why an older Linux dev environment likely worked (it probably had an older, pre-regression fontconfig before a `conda update`/fresh install pulled in 2.18.1 for this environment).

---

## 2. Permanent Fix (applied)

Pinned `fontconfig` down to the known-good `2.15.0` build directly in the live conda environment:

```bash
conda install -p /home/renu/threePSLCCA 'fontconfig=2.15.0' -y
```

Dry-run beforehand confirmed minimal blast radius — **only** `fontconfig` itself changed (2.18.1 → 2.15.0), no other package in the environment was pulled in or downgraded as a side effect.

Verified after pinning:
- The 6-line repro above no longer crashes, with no `LD_PRELOAD` or other workaround in place.
- `threePSLCCA` launches and stays alive in its event loop (confirmed via `PYTHONFAULTHANDLER=1` + `timeout`, no segfault, no crash output).

A temporary stop-gap (`LD_PRELOAD` re-exec guard added to `three_ps_lcca_gui/gui/main.py`) was used during diagnosis and has since been **removed** now that the real fix is in place — the codebase carries no workaround code for this issue.

---

## 3. Caveats / what's still fragile

This fix lives in **this specific conda environment's installed state**, not in the installer/build pipeline that produced it. It will be silently lost if:
- The `.sh` installer is re-run and recreates `/home/renu/threePSLCCA` from scratch.
- Someone runs `conda update --all` (or similar) in this environment, which could pull `fontconfig` back up past 2.15.0 — re-resolve against the original spec.
- The app is installed fresh on a different machine, since the installer's environment spec presumably has no constraint at all on `fontconfig` and will grab whatever conda-forge's latest is at install time.

**To make this durable, the actual installer/build pipeline needs the pin baked in.** Find whatever conda environment spec the `.sh` installer uses (`environment.yml`, `construct.yaml`, an explicit `conda create` package list, etc.) and add:
```yaml
dependencies:
  - fontconfig =2.15.0
```
or at minimum `fontconfig <2.17` to stay clear of the 2.17.x/2.18.x line. Before locking that upper bound permanently, check conda-forge's fontconfig changelog/issue tracker — a later patch release after 2.18.1 may turn out to fix `FcCharSetFindLeafForward` cleanly, in which case the pin could instead be a lower bound on that fixed version.

Also worth doing, lower priority, as general hardening (not required for this fix to hold):
- Pin `PySide6` itself in `pyproject.toml`/`setup.cfg` (`Requires-Dist: PySide6` is currently unpinned, so every fresh install grabs whatever's latest — the same kind of drift that caused this).
- Consider migrating the riskiest decorative glyphs (🗑️ 🔒 ▶ ✓ etc.) to bundled `QIcon`s instead of Unicode characters in button/label text, so they don't depend on font-fallback behavior on any future machine's font set.

---

## 4. How to verify this is still fixed, on this or any other machine

```bash
# 1. Check the installed version
conda list -p /home/renu/threePSLCCA fontconfig
# expect: fontconfig   2.15.0   h27c8c51_2   conda-forge   (or another verified-safe version)

# 2. Run the isolated repro — must NOT segfault
cat > /tmp/repro.py << 'EOF'
import sys
from PySide6.QtWidgets import QApplication, QPushButton
app = QApplication(sys.argv)
btn = QPushButton("Run Comparison ↗")
btn.show()
app.processEvents()
print("OK - no crash on show")
sys.exit(0)
EOF
PYTHONFAULTHANDLER=1 /home/renu/threePSLCCA/bin/python3.12 /tmp/repro.py

# 3. Launch the real app — should stay running, not crash immediately
PYTHONFAULTHANDLER=1 timeout 8 /home/renu/threePSLCCA/bin/threePSLCCA
echo "exit $?"   # 124 (timeout killed a still-running process) = healthy. 139 = segfault, still broken.
```

---

## Appendix: diagnostic commands used to find this

```bash
# Get the exact Python-level crash frame (bypasses print() being monkey-patched to a no-op in non-dev builds)
PYTHONFAULTHANDLER=1 /home/renu/threePSLCCA/bin/threePSLCCA

# Get the native crash frame across all threads
gdb -q -batch -ex run -ex "bt full" -ex "info threads" --args \
  /home/renu/threePSLCCA/bin/python3.12 /home/renu/threePSLCCA/bin/threePSLCCA

# Confirm this is a conda env, and read the real installed version from conda-meta (authoritative —
# do NOT infer the version from the .so filename suffix, see note in §1)
ls /home/renu/threePSLCCA/conda-meta/ | grep -i fontconfig
fc-cache --version    # system fontconfig for comparison: 2.15.0

# Confirm the fix direction before committing to it
LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libfontconfig.so.1 /home/renu/threePSLCCA/bin/threePSLCCA

# Dry-run the pin to see blast radius before applying
conda install -p /home/renu/threePSLCCA 'fontconfig=2.15.0' --dry-run

# Apply the permanent fix
conda install -p /home/renu/threePSLCCA 'fontconfig=2.15.0' -y
```
