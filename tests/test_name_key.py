"""name_key: how duplicate-name checks compare material names.

Rule: case ignored, outer whitespace ignored, any run of inner whitespace is
one space; every other difference keeps the names apart.
"""

import pytest

from three_ps_lcca_gui.gui.components.structure.widgets.material_dialog import name_key

# every whitespace character str.split() knows, as single characters
_WS = ["\t", "\n", "\x0b", "\x0c", "\r", "\x85", " ", " ",
       " ", " ", " ", " ", " ", " ", " ",
       " ", " ", " ", " ", " ", " ", " ",
       " ", "　"]


# ── 1. same name ─────────────────────────────────────────────────────────

SAME = {
    "abc": [
        "abc\n", "\r\nabc\r\n", "\fabc\v", "\x0babc\x0c",
        " abc ", " ABC ", " abc ", "　abc　",
        " abc ", "\x85abc", " abc ", " abc ",
        " \t\n\r\x0b\x0c 　abc  \n", "AbC", "aBc", "ABc",
    ],
    "abc def": [
        "abc\ndef", "abc\r\ndef", "abc\x0bdef", "abc\x0cdef",
        "abc def", "abc def", "abc　def", "abc def",
        "abc def", "abc\x85def", "abc def", "abc def",
        "abc  def", "abc \t \n  def", "　ABC  DEF ",
        "aBC dEF", "Abc\tDef",
    ],
    "m25 concrete": ["M25 Concrete", "  m25\t\tCONCRETE ", "M25 concrete"],
    "12 mm bar": ["12 MM BAR", "12 mm bar", "  12   mm\nbar"],
    "m-25 (opc), grade-a": ["M-25 (OPC), Grade-A", "  m-25\t(opc),　GRADE-A "],
    "fe500d tmt": ["FE500D TMT", "Fe500D tmt"],
    "सीमेंट मिश्रण": [
        " सीमेंट  मिश्रण ",
        "सीमेंट\tमिश्रण",
        "सीमेंट मिश्रण\n",
    ],
    "béton armé": ["BÉTON ARMÉ", " Béton Armé ", "béton\n\narmé"],
    "οδος": ["ΟΔΟΣ", " Οδος "],
    "ａｂｃ": ["ＡＢＣ", "　Ａｂｃ "],
    "high strength ready mix concrete": [
        "High  Strength\tReady Mix   Concrete",
        "\nHIGH strength READY mix CONCRETE\r\n",
    ],
    " ".join(["word"] * 500): ["\t".join(["WORD"] * 500) + "  ", "  ".join(["Word"] * 500)],
    "x" * 10000: ["X" * 10000 + "\n"],
    # Python lower-cases these letter-like signs to the plain letter: one
    # material either way (Kelvin K, Ohm, Angstrom)
    "k": ["K"],
    "ω": ["Ω"],
    "å": ["Å"],
    "ß": ["ẞ"],
}


@pytest.mark.parametrize("target,name", [(t, n) for t, ns in SAME.items() for n in ns])
def test_same_name(target, name):
    assert name_key(name) == target


@pytest.mark.parametrize("ws", _WS)
def test_every_whitespace_is_squeezed(ws):
    assert name_key(f"{ws}abc{ws}{ws}def{ws}") == "abc def"


# ── 2. different names ───────────────────────────────────────────────────

DIFFERENT = [
    ("abc", "ab​c"), ("abc", "abc​"), ("abc def", "abc​def"),
    ("abc", "a‍bc"), ("abc", "﻿abc"), ("abc", "a⁠bc"),
    ("abc def", "abc᠎def"),
    ("abc def", "abc-def"), ("abc def", "abc_def"), ("abc def", "abc.def"),
    ("abc def", "abcdef"), ("a bc", "abc"), ("12 mm", "12mm"),
    ("m25, opc", "m25 , opc"),
    ("abc", "ａｂｃ"), ("12", "１２"), ("12", "१२"),
    ("m2", "m²"), ("10x20", "10×20"),
    ("é", "é"), ("क़", "क़"),
    ("क्ष", "क्‍ष"),
    ("i", "ı"), ("ß", "ss"), ("ﬁx", "fix"), ("ﬁx", "FIX"),
    ("µm", "μm"), ("beton arme", "béton armé"),
    ("İ", "i"), ("I", "ı"), ("STRASSE", "straße"),
    ("ΟΔΟΣ", "οδοσ"),
]


@pytest.mark.parametrize("a,b", DIFFERENT)
def test_different_names(a, b):
    assert name_key(a) != name_key(b)


# ── 3. blank ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", [None, "", " ", "   ", "\r\n", "".join(_WS),
                                  " \t\n\r\x0b\x0c 　   "])
def test_blank(name):
    assert name_key(name) == ""


@pytest.mark.parametrize("name", ["​", "‍", "﻿", "⁠", "᠎"])
def test_invisible_but_not_whitespace_is_not_blank(name):
    assert name_key(name) != ""


def test_ascii_separator_controls_count_as_whitespace():
    """\\x1c-\\x1f are not Unicode whitespace, but str.split() treats them as
    such; nobody types them into a material name, so they are left that way."""
    assert name_key("abc\x1cdef") == "abc def"
    assert name_key("\x1c\x1d\x1e\x1f") == ""


@pytest.mark.parametrize("value", [12, 12.5, True])
def test_non_text_does_not_raise(value):
    assert name_key(value) == str(value).lower()
