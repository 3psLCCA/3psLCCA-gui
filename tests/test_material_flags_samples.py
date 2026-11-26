"""material_flag against the stored materials in data/material_flags_samples.json."""

import json
from pathlib import Path

import pytest

from three_ps_lcca_gui.gui.components.structure.material_flags import material_flag

SAMPLES = json.loads(
    (Path(__file__).parent / "data" / "material_flags_samples.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("sample", SAMPLES, ids=[s["case"] for s in SAMPLES])
def test_sample(sample):
    assert material_flag(sample["item"]) == sample["expect"], sample["why"]
