"""Every bundled SOR JSON in registry/material_database has the required fields.

Two checks per file:
  1. The app's own schema check (material_catalog.check_integrity_by_path):
     all keys present, rate/conversion_factor numeric or null, component valid.
  2. The fields an SOR entry cannot do without have a value:
     name, unit and rate_src non-empty, rate a number.
"""
import json
from pathlib import Path

import pytest

from three_ps_lcca_gui.gui.components.structure.registry import material_catalog

DB_ROOT = Path(material_catalog.__file__).parent / "material_database"
FILES = sorted(DB_ROOT.rglob("*.json"))
REQUIRED_TEXT = ("name", "unit", "rate_src")


def _ids(paths):
    return [p.relative_to(DB_ROOT).as_posix() for p in paths]


def test_database_files_found():
    assert FILES, f"no JSON files under {DB_ROOT}"


@pytest.mark.parametrize("path", FILES, ids=_ids(FILES))
def test_schema(path):
    report = material_catalog.check_integrity_by_path(str(path))
    assert report["status"] == "OK", "\n".join(report["errors"][:20])


@pytest.mark.parametrize("path", FILES, ids=_ids(FILES))
def test_required_values(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    for sheet in data:
        for i, item in enumerate(sheet.get("data", [])):
            ref = f"{sheet.get('sheetName', '?')}[{i}] {item.get('src_id', '')} {item.get('name', '?')!r}"
            for key in REQUIRED_TEXT:
                val = item.get(key)
                if not isinstance(val, str) or not val.strip():
                    problems.append(f"{ref}: empty '{key}'")
            rate = item.get("rate")
            if isinstance(rate, bool) or not isinstance(rate, (int, float)):
                problems.append(f"{ref}: rate is {rate!r}")
    assert not problems, f"{len(problems)} problem(s):\n" + "\n".join(problems[:20])
