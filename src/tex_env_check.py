import os
import shutil
import subprocess
import tempfile
import sys
from pathlib import Path

# Try to import the single source of truth from the app
try:
    # Add src to path if needed for standalone run
    src_path = str(Path(__file__).resolve().parent)
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    
    from three_ps_lcca_gui.code_to_latex.SETTINGS import REQUIRED_LATEX_PACKAGES
    PACKAGES_SOURCE = "SETTINGS.py"
except ImportError:
    # Fallback if run outside the expected structure
    REQUIRED_LATEX_PACKAGES = {
        "mathptmx": None,
        "geometry": None,
        "graphicx": None,
        "amsmath": None,
        "xcolor": None,
        "booktabs": None,
        "longtable": None,
        "tabularx": None,
        "fancyhdr": None,
    }
    PACKAGES_SOURCE = "Hardcoded Fallback"

def check_tex_env():
    print("=== LaTeX Environment Diagnostic ===")
    print(f"Package List Source: {PACKAGES_SOURCE}")
    
    # 1. Check Source (Osdag vs Standard)
    pdf_source = "pdflatex"
    try:
        from osdag_latex_env import OsdagLatexEnv
        env = OsdagLatexEnv()
        pdf_source = str(getattr(env, "pdflatex", "pdflatex (from OsdagLatexEnv)"))
        print(f"Source: Osdag Module (Path: {pdf_source})")
    except ImportError:
        print("Source: Standard System Path (osdag_latex_env not found)")
    except Exception as e:
        print(f"Source: Standard System Path (Osdag module check failed: {e})")

    # 2. Check pdflatex availability
    executable = shutil.which("pdflatex")
    if not executable and pdf_source != "pdflatex":
         # Check the specific path provided by Osdag
         if os.path.exists(pdf_source):
             executable = pdf_source

    if executable:
        print(f"pdflatex Executable: {executable}")
        try:
            version = subprocess.check_output([executable, "--version"], text=True).splitlines()[0]
            print(f"pdflatex Version: {version}")
        except Exception:
            print("pdflatex Version: Could not retrieve version info.")
    else:
        print("pdflatex Executable: NOT FOUND in PATH.")
        return

    # 3. Check for specific packages from the single source of truth
    print("\n--- Package Availability Check ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        for pkg, options in REQUIRED_LATEX_PACKAGES.items():
            test_file = Path(tmpdir) / "test_pkg.tex"
            opt_str = f"[{','.join(options)}]" if options else ""
            content = f"\\documentclass{{article}}\\usepackage{opt_str}{{{pkg}}}\\begin{{document}}test\\end{{document}}"
            test_file.write_text(content)
            
            try:
                result = subprocess.run(
                    [executable, "-interaction=nonstopmode", "test_pkg.tex"],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=15
                )
                if result.returncode == 0:
                    print(f"[ OK ] {pkg}")
                else:
                    if f"{pkg}.sty' not found" in result.stdout:
                        print(f"[MISSING] {pkg}")
                    else:
                        print(f"[ERROR] {pkg} (Compilation failed, check distribution)")
            except Exception as e:
                print(f"[FAIL] {pkg} (Check process failed: {e})")

    print("\n=== Diagnostic Complete ===")

if __name__ == "__main__":
    check_tex_env()
