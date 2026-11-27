"""
devtools/check_dependency_versions.py

Check that every dependency file lists the same packages with the same
version specs:

    pyproject.toml          [project] dependencies and requires-python
    requirements.txt        pip installs for development
    environment.yml         conda environment for development
    conda-recipe/meta.yaml  run requirements of the conda package / installer
    installer/construct.yaml  extra specs of the installer (fontconfig)

Reports a package that is missing from a file, a package listed twice in
one file, and a package whose version spec differs between files. Also
checks that pyproject.toml and meta.yaml carry the same app version.
construct.yaml's app version is not checked: the release workflow
overwrites it (and the other two) from the git tag.

Usage:  python devtools/check_dependency_versions.py
Exit code 0 when everything matches, 1 when something differs.
tests/test_dependency_versions.py runs check() in the test suite.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

# Packages that only belong in the conda files (conda installs Python and
# pip itself; the LaTeX bundle and fontconfig are conda-only packages).
CONDA_ONLY = {"python", "pip", "osdag-latex-env", "fontconfig"}


def _read(path: Path) -> str:
    """Text of a file; utf-8-sig also accepts a byte-order mark (Notepad, PowerShell)."""
    return path.read_text(encoding="utf-8-sig")


def norm_name(name: str) -> str:
    """'zehen-249::three-ps-lcca-core' / 'three_ps_lcca_core' -> 'three-ps-lcca-core'."""
    name = name.split("::")[-1]
    return re.sub(r"[-_.]+", "-", name).lower()


def split_spec(text: str) -> tuple[str, str]:
    """'PySide6>=6.11,!=6.11.3,<6.12' -> ('pyside6', '!=6.11.3,<6.12,>=6.11')."""
    text = text.split("#")[0].strip()
    m = re.match(r"^([A-Za-z0-9_.\-:]+)\s*(.*)$", text)
    if not m:
        raise ValueError(f"cannot read dependency {text!r}")
    name, spec = m.groups()
    parts = sorted(p.strip() for p in spec.replace(" ", "").split(",") if p.strip())
    return norm_name(name), ",".join(parts)


def _to_dict(fname: str, pairs: list[tuple[str, str]], problems: list[str]) -> dict[str, str]:
    """Pairs -> {name: spec}; a name listed twice is a problem (the later
    entry would silently hide the earlier one)."""
    deps: dict[str, str] = {}
    for name, spec in pairs:
        if name in deps:
            problems.append(f"{name}: listed twice in {fname} "
                            f"({deps[name] or '(any)'} and {spec or '(any)'})")
        deps[name] = spec
    return deps


def _pyproject() -> dict:
    return tomllib.loads(_read(ROOT / "pyproject.toml"))["project"]


def read_pyproject() -> list[tuple[str, str]]:
    return [split_spec(d) for d in _pyproject()["dependencies"]]


def read_requirements() -> list[tuple[str, str]]:
    pairs = []
    for line in _read(ROOT / "requirements.txt").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        if line.startswith("-e"):  # local editable package: use its own name
            path = ROOT / line[2:].strip()
            name = tomllib.loads(_read(path / "pyproject.toml"))["project"]["name"]
            pairs.append((norm_name(name), ""))
            continue
        pairs.append(split_spec(line))
    return pairs


def read_environment() -> list[tuple[str, str]]:
    data = yaml.safe_load(_read(ROOT / "environment.yml"))
    pairs = []
    for d in data["dependencies"]:
        for item in (d["pip"] if isinstance(d, dict) else [d]):
            pairs.append(split_spec(str(item)))
    return pairs


def _yaml_list(path: Path, section: str, indent: int) -> list[str]:
    """Items of a '- item' list under 'section:' (meta.yaml is Jinja, not plain YAML)."""
    items, inside = [], False
    for line in _read(path).splitlines():
        stripped = line.strip()
        if stripped == f"{section}:" and len(line) - len(line.lstrip()) == indent:
            inside = True
            continue
        if inside:
            if stripped.startswith("- "):
                items.append(stripped[2:])
            elif stripped and not stripped.startswith("#"):
                break
    return items


def read_meta() -> list[tuple[str, str]]:
    return [split_spec(i) for i in _yaml_list(ROOT / "conda-recipe" / "meta.yaml", "run", 2)]


def read_construct() -> list[tuple[str, str]]:
    pairs = [split_spec(i) for i in _yaml_list(ROOT / "installer" / "construct.yaml", "specs", 0)]
    # the app itself; its version is set by the release workflow
    return [(n, s) for n, s in pairs if n != "three-ps-lcca-gui"]


def app_versions() -> dict[str, str]:
    pyproject = _pyproject().get("version", "?")  # '?' if set dynamically (setuptools_scm)
    meta = re.search(r'{%\s*set version\s*=\s*"([^"]+)"', _read(ROOT / "conda-recipe" / "meta.yaml"))
    return {"pyproject.toml": pyproject, "conda-recipe/meta.yaml": meta.group(1) if meta else "?"}


def check(verbose: bool = False) -> list[str]:
    """All problems found, as one line each; empty when the files agree."""
    problems: list[str] = []
    files = {
        "pyproject.toml": _to_dict("pyproject.toml", read_pyproject(), problems),
        "requirements.txt": _to_dict("requirements.txt", read_requirements(), problems),
        "environment.yml": _to_dict("environment.yml", read_environment(), problems),
        "conda-recipe/meta.yaml": _to_dict("conda-recipe/meta.yaml", read_meta(), problems),
    }
    conda_files = {"environment.yml", "conda-recipe/meta.yaml"}

    names = sorted(set().union(*files.values()))
    width = max(len(n) for n in names)
    table = [f"{'package':<{width}}  " + "  ".join(f"{f:<24}" for f in files)]
    for name in names:
        row, specs = [], set()
        for fname, deps in files.items():
            expected = fname in conda_files or name not in CONDA_ONLY
            if name in deps:
                row.append(deps[name] or "(any)")
                specs.add(deps[name])
            elif expected:
                row.append("MISSING")
                problems.append(f"{name}: missing from {fname}")
            else:
                row.append("-")
        if len(specs) > 1:
            problems.append(f"{name}: different versions {sorted(specs)}")
        table.append(f"{name:<{width}}  " + "  ".join(f"{c:<24}" for c in row))

    # installer extras must match the conda recipe
    construct = _to_dict("installer/construct.yaml", read_construct(), problems)
    for name, spec in construct.items():
        meta_spec = files["conda-recipe/meta.yaml"].get(name)
        if meta_spec != spec:
            problems.append(f"{name}: installer/construct.yaml has {spec or '(any)'}, "
                            f"meta.yaml has {meta_spec}")

    # pyproject's requires-python must match the conda python spec
    requires = _pyproject().get("requires-python", "")
    _, py_spec = split_spec("python" + requires)
    for fname in conda_files:
        if files[fname].get("python") != py_spec:
            problems.append(f"python: pyproject requires-python {py_spec or '(none)'}, "
                            f"{fname} has {files[fname].get('python')}")

    versions = app_versions()
    if "?" in versions.values():
        problems.append(f"app version not found: {versions}")
    elif len(set(versions.values())) > 1:
        problems.append(f"app version differs: {versions}")

    if verbose:
        print("\n".join(table))
        print("\napp version: " + ", ".join(f"{f} {v}" for f, v in versions.items()))
    return problems


def main() -> int:
    problems = check(verbose=True)
    if problems:
        print("\nMISMATCHES:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nOK: all dependency files agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
