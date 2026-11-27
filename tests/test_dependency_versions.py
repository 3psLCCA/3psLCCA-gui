"""All dependency files (pyproject, requirements, environment.yml, conda
recipe, installer) list the same packages and versions.
See devtools/check_dependency_versions.py."""

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "devtools" / "check_dependency_versions.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_dependency_versions", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dependency_files_agree():
    problems = _load().check()
    # one line per problem, e.g. "odfpy: missing from environment.yml"
    assert not problems, "Dependency files disagree:\n" + "\n".join(problems)
