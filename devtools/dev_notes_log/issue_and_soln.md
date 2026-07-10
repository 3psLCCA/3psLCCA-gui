# Issue: `pdflatex failed` — `listingsutf8.sty' not found`

## Symptom

```
RuntimeError: pdflatex failed (exit 1) on attempt 2/2.

LaTeX errors:
Package: infwarerr 2019/12/03 v1.5 Providing info/warning/error messages (HO)
! LaTeX Error: File `listingsutf8.sty' not found.
! Emergency stop.
!  ==> Fatal error occurred, no output PDF file produced!
```

Confusing because **`listingsutf8` is never referenced anywhere in this codebase** —
no `\usepackage{listingsutf8}`, no `lstlisting`, no `\lstset`. `devtools/latex_env_check_gui.py`
(and `SETTINGS.verify_packages()`) also don't list it, since neither checks anything but the
top-level `REQUIRED_LATEX_PACKAGES` keys.

## Root cause

`src/three_ps_lcca_gui/code_to_latex/SETTINGS.py` had:

```python
"tcolorbox": ["most"],
```

`most` is a **style bundle** inside `tcolorbox.sty`, not a single option. It auto-loads a
group of tcolorbox *libraries*:

```
# Library/share/osdag_latex_env/texmf-dist/tex/latex/tcolorbox/tcolorbox.sty:3043
\tcb@add@library@style{most}{many,listingsutf8,external,magazine,vignette,poster}
```

One of those libraries is `listingsutf8`, whose code does:

```
# .../tcolorbox/tcblistingsutf8.code.tex:34
\RequirePackage{listingsutf8}[2011/11/10]
```

`listingsutf8.sty` is a **separate CTAN package** (not a tcolorbox file) and it is not part of
the `osdag_latex_env` bundle shipped with this app. So `most` silently pulls in a hard
dependency the project never asked for and never uses (we only use plain
`\begin{tcolorbox}[enhanced,...]` / `\newtcolorbox{...}`, which only needs the `skins` library).

**Fix:** use the narrower `many` style instead of `most`:

```
# tcolorbox.sty:3042
\tcb@add@library@style{many}{raster,skins,breakable,hooks,theorems,fitting}
```

`many` covers `skins` (needed for `enhanced`) without dragging in `listingsutf8`, `external`,
`magazine`, `vignette`, or `poster`.

```python
# SETTINGS.py
"tcolorbox": ["many"],
```

## Second trap: the fix "didn't work"

After changing `SETTINGS.py` and rerunning, the **exact same error** came back. Cause: this
package is installed into the `H:\3psIsHere` conda env as a **regular (non-editable) copy** in
`site-packages`, not via `pip install -e .`. Editing `src/.../SETTINGS.py` only changes the
source tree — the app was still importing the stale copy:

```
H:\3psIsHere\Lib\site-packages\three_ps_lcca_gui\code_to_latex\SETTINGS.py
```

**Fix:** reinstall in editable mode so `site-packages` points back at `src/`:

```bash
cd "c:\Users\Asus\Desktop\3psLCCA is here\osbridgelcca_new"
H:\3psIsHere\python.exe -m pip install -e .
```

Verify it actually resolved to source before trusting any further edits:

```bash
H:\3psIsHere\python.exe -c "import three_ps_lcca_gui.code_to_latex.SETTINGS as s; print(s.__file__)"
# should print the src/... path, not Lib/site-packages/...
```

## Takeaways for future package/option changes in `SETTINGS.py`

1. **Don't reach for `most`/`all` package option bundles** (tcolorbox or otherwise) just because
   they're convenient — they can silently require packages outside the bundled
   `osdag_latex_env` texmf tree. Only request the options/libraries actually used.
2. Before trusting `devtools/latex_env_check_gui.py` or `verify_packages()` as a completeness
   check: they only validate the packages *listed* in `REQUIRED_LATEX_PACKAGES`, not transitive
   deps pulled in by option bundles like `most`/`all`/`many`. A missing transitive `.sty` won't
   show up there — only in an actual `pdflatex` run.
3. After editing anything under `src/three_ps_lcca_gui/`, confirm the env is running in editable
   mode (`pip show three_ps_lcca_gui` → `Editable project location:`, or check for
   `__editable__.three_ps_lcca_gui-*.pth` in `site-packages`) before assuming a source edit will
   take effect.
4. If a genuinely new `.sty` is required going forward, add it to the bundle
   (`osdag_latex_env` texmf-dist) rather than relying on a system TeX install having it —
   the whole point of the bundle is that end users don't need a separate TeX distribution.
