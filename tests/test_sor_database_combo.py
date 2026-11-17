"""Material Suggestions (sor_database) combo on the General Info page.

The combo shows a short label ("Madhya Pradesh – MPPWD SOR 2025") but the chunk
must always store the full database key ("INDIA/Madhya_Pradesh/MPPWD SOR 2025").
A saved key that this version doesn't ship is shown as a disabled entry and its
key is kept until the user picks something else.
"""
import random
import string

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from three_ps_lcca_gui.gui.components.global_info import main as gi  # noqa: E402
from three_ps_lcca_gui.gui.components.structure.widgets import material_dialog  # noqa: E402

GeneralInfo = gi.GeneralInfo
label = GeneralInfo._sor_display_label
missing = GeneralInfo._missing_sor_label
NA = " (not available in this version)"


def _opt(db_key, region=None, lbl=None):
    """Option dict as _list_sor_options builds it (region as the registry derives it)."""
    if region is None:
        region = "/".join(db_key.split("/")[1:-1])
    return {"db_key": db_key, "region": region, "label": lbl if lbl is not None else db_key}


# ── label conversion ────────────────────────────────────────────────────────

@pytest.mark.parametrize("db_key, expected", [
    # every database shipped today
    ("INDIA/Bihar/RCD SOR 2025", "Bihar – RCD SOR 2025"),
    ("INDIA/Karnataka/KPWD SOR 2023-24", "Karnataka – KPWD SOR 2023-24"),
    ("INDIA/Madhya_Pradesh/MPPWD SOR 2025", "Madhya Pradesh – MPPWD SOR 2025"),
    ("INDIA/Maharashtra/PWD SSR 2022-23", "Maharashtra – PWD SSR 2022-23"),
    ("INDIA/Rajasthan/RUIDP ISOR 2023", "Rajasthan – RUIDP ISOR 2023"),
    # any depth: every level after the country is shown
    ("INDIA/Maharashtra/Nagpur/NMC/2022", "Maharashtra – Nagpur – NMC – 2022"),
    ("INDIA/Maharashtra/PWD/PWD_SOR", "Maharashtra – PWD – PWD SOR"),
    ("INDIA/Bihar/Darbhanga-2025", "Bihar – Darbhanga-2025"),
    ("INDIA/A/B/C/D/E/F/G", "A – B – C – D – E – F – G"),
    # file directly in the country folder
    ("INDIA/MumbaiSOR", "MumbaiSOR"),
    ("INDIA/Mumbai_SOR", "Mumbai SOR"),
    # underscores become spaces everywhere
    ("INDIA/Tamil_Nadu/TNHD SOR", "Tamil Nadu – TNHD SOR"),
    ("INDIA/Dadra_and_Nagar_Haveli/X", "Dadra and Nagar Haveli – X"),
    ("INDIA/_Goa_/PWD", "Goa – PWD"),
    ("INDIA/Bihar/RCD_SOR_2025", "Bihar – RCD SOR 2025"),
    ("INDIA/delhi/cpwd", "delhi – cpwd"),  # case kept as stored
    # country is always dropped, whatever it is
    ("NEPAL/Bagmati/DoR Norms", "Bagmati – DoR Norms"),
    ("india/Bihar/RCD SOR 2025", "Bihar – RCD SOR 2025"),
    ("/Bihar/RCD SOR 2025", "Bihar – RCD SOR 2025"),
    ("INDIA_X/Bihar/RCD", "Bihar – RCD"),
    # empty or blank levels are skipped
    ("INDIA//RCD SOR 2025", "RCD SOR 2025"),
    ("INDIA/_/RCD SOR 2025", "RCD SOR 2025"),
    ("INDIA/ /RCD SOR 2025", "RCD SOR 2025"),
    ("INDIA/Bihar//RCD", "Bihar – RCD"),
    ("INDIA/Bihar/RCD/", "Bihar – RCD"),
    ("INDIA/ Bihar / RCD SOR 2025 ", "Bihar – RCD SOR 2025"),
    # odd characters pass through
    ("INDIA/Bihar/SOR (Rev. 2) & Addendum #3", "Bihar – SOR (Rev. 2) & Addendum #3"),
    ("INDIA/Bihar/SOR – 2025", "Bihar – SOR – 2025"),
    ("INDIA/Bihar/SOR.v2.final", "Bihar – SOR.v2.final"),
    ("भारत/बिहार/दर सूची", "बिहार – दर सूची"),
])
def test_builtin_labels(db_key, expected):
    assert label(_opt(db_key)) == expected


@pytest.mark.parametrize("db_key", [
    "", "INDIA", "Bihar RCD SOR 2025", "INDIA/", "INDIA//", "INDIA/_/ /",
])
def test_keys_with_nothing_after_the_country_keep_their_label(db_key):
    assert label(_opt(db_key, lbl="as listed")) == "as listed"


@pytest.mark.parametrize("db_key", [
    "custom::MyDB", "custom::a/b/c", "custom::Bihar/Extra/Things", "custom::My_DB", "custom::",
])
def test_custom_databases_keep_their_label(db_key):
    lbl = f"{db_key[len('custom::'):]}  (Custom)"
    assert label(_opt(db_key, region="Custom", lbl=lbl)) == lbl


@pytest.mark.parametrize("db_key, expected", [
    ("I/B/R", "B – R"),
    ("INDIA/x", "x"),
    ("INDIA/_x_", "x"),
    ("INDIA/1/2", "1 – 2"),
    ("INDIA/a/b/c", "a – b – c"),
    ("/a", "a"),
    ("INDIA/-", "-"),
])
def test_short_names(db_key, expected):
    assert label(_opt(db_key)) == expected


def test_long_file_name():
    name = "Schedule of Rates for Road and Bridge Works " * 12
    assert label(_opt(f"INDIA/Bihar/{name}")) == f"Bihar – {name.strip()}"


def test_long_region_name():
    region = "_".join(["Very_Long_Region"] * 30)
    assert label(_opt(f"INDIA/{region}/SOR")) == region.replace("_", " ") + " – SOR"


def test_deep_folder_nesting():
    levels = [f"Level_{i}" for i in range(60)]
    got = label(_opt("INDIA/" + "/".join(levels) + "/File_2025"))
    assert got == " – ".join(lv.replace("_", " ") for lv in levels) + " – File 2025"
    assert got.count(" – ") == 60


def test_long_missing_label():
    key = "INDIA/" + "/".join(["Maharashtra"] * 20) + "/" + "X" * 500
    assert missing(key) == " – ".join(["Maharashtra"] * 20) + " – " + "X" * 500 + NA


def test_label_does_not_modify_the_option():
    opt = _opt("INDIA/Madhya_Pradesh/MPPWD SOR 2025")
    before = dict(opt)
    label(opt)
    assert opt == before


def test_random_keys_follow_the_rule():
    rng = random.Random(1234)
    chars = string.ascii_letters + string.digits + " _-().&"
    for _ in range(5000):
        levels = ["".join(rng.choices(chars, k=rng.randint(0, 12)))
                  for _ in range(rng.randint(1, 7))]
        key = "/".join(levels)
        got = label(_opt(key))
        shown = [lv.replace("_", " ").strip() for lv in levels[1:]]
        shown = [s for s in shown if s]
        assert got == (" – ".join(shown) if shown else key), key
        assert "/" not in got or not shown, key
        assert "_" not in got or not shown, key


def test_every_shipped_database_gets_a_short_unique_label():
    opts = material_dialog._list_sor_options(None)
    builtin = [o for o in opts if o["region"] != "Custom"]
    assert builtin, "registry returned no databases"
    labels = [label(o) for o in builtin]
    assert len(set(labels)) == len(labels)
    for o, lbl in zip(builtin, labels):
        levels = o["db_key"].split("/")
        assert levels[0] not in lbl.split(" – ")
        assert lbl.endswith(levels[-1].replace("_", " ").strip())
        assert "/" not in lbl and "_" not in lbl


# ── label for a database missing from this version ──────────────────────────

@pytest.mark.parametrize("db_key, expected", [
    ("INDIA/Bihar/RCD SOR 2019", "Bihar – RCD SOR 2019"),
    ("INDIA/Madhya_Pradesh/Old SOR", "Madhya Pradesh – Old SOR"),
    ("INDIA/Maharashtra/Nagpur/NMC/2022", "Maharashtra – Nagpur – NMC – 2022"),
    ("INDIA/MumbaiSOR", "MumbaiSOR"),
    ("custom::MyDB", "MyDB  (Custom)"),
    ("custom::a/b/c", "a/b/c  (Custom)"),
    ("something odd", "something odd"),
])
def test_missing_labels(db_key, expected):
    assert missing(db_key) == expected + NA


# ── combo behaviour ─────────────────────────────────────────────────────────

SHIPPED = [
    _opt("INDIA/Bihar/RCD SOR 2025"),
    _opt("INDIA/Madhya_Pradesh/MPPWD SOR 2025"),
    _opt("INDIA/Karnataka/KPWD SOR 2023-24"),
    _opt("custom::MyDB", region="Custom", lbl="MyDB  (Custom)"),
]


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def page(app, monkeypatch):
    options = list(SHIPPED)
    monkeypatch.setattr(material_dialog, "_list_sor_options", lambda country: list(options))
    p = GeneralInfo()
    p._options = options  # tests may change the shipped list
    return p


def _items(cb):
    return [(cb.itemText(i), cb.itemData(i), cb.model().item(i).isEnabled())
            for i in range(cb.count())]


def _stored(page):
    return page.get_data_dict()["sor_database"]


def test_list_shows_labels_and_stores_keys(page):
    page._populate_sor_combo("India", "")
    assert _items(page.sor_database) == [
        ("Bihar – RCD SOR 2025", "INDIA/Bihar/RCD SOR 2025", True),
        ("Madhya Pradesh – MPPWD SOR 2025", "INDIA/Madhya_Pradesh/MPPWD SOR 2025", True),
        ("Karnataka – KPWD SOR 2023-24", "INDIA/Karnataka/KPWD SOR 2023-24", True),
        ("MyDB  (Custom)", "custom::MyDB", True),
        ("- No suggestions -", "", True),
    ]


@pytest.mark.parametrize("key", [o["db_key"] for o in SHIPPED])
def test_saved_key_is_selected_and_stored_unchanged(page, key):
    page._populate_sor_combo("India", key)
    assert _stored(page) == key
    assert page.sor_database.currentText() == label(next(o for o in SHIPPED if o["db_key"] == key))


def test_empty_key_selects_no_suggestions(page):
    page._populate_sor_combo("India", "")
    assert page.sor_database.currentText() == "- No suggestions -"
    assert _stored(page) == ""


def test_load_data_dict_round_trip(page):
    page.load_data_dict({"project_country": "India",
                         "sor_database": "INDIA/Madhya_Pradesh/MPPWD SOR 2025"})
    assert page.sor_database.currentText() == "Madhya Pradesh – MPPWD SOR 2025"
    assert _stored(page) == "INDIA/Madhya_Pradesh/MPPWD SOR 2025"


@pytest.mark.parametrize("key", ["INDIA/Bihar/RCD SOR 2019", "custom::Deleted"])
def test_missing_key_is_shown_disabled_and_kept(page, key):
    page._populate_sor_combo("India", key)
    cb = page.sor_database
    assert cb.currentIndex() == 0
    assert cb.currentText() == missing(key)
    assert cb.itemData(0) == key
    assert not cb.model().item(0).isEnabled()
    assert all(enabled for _, _, enabled in _items(cb)[1:])
    assert _stored(page) == key  # saving keeps the user's original choice


def test_missing_entry_is_skipped_by_arrow_keys(page):
    key = "INDIA/Bihar/RCD SOR 2019"
    page._populate_sor_combo("India", key)
    cb = page.sor_database
    QTest.keyClick(cb, Qt.Key_Down)
    assert _stored(page) == "INDIA/Bihar/RCD SOR 2025"
    QTest.keyClick(cb, Qt.Key_Up)  # disabled entry above: stays put
    assert _stored(page) == "INDIA/Bihar/RCD SOR 2025"
    QTest.keyClick(cb, Qt.Key_Home)
    assert _stored(page) == "INDIA/Bihar/RCD SOR 2025"


def test_missing_entry_is_skipped_by_type_ahead(page):
    page._populate_sor_combo("India", "INDIA/Bihar/RCD SOR 2019")
    cb = page.sor_database
    cb.setCurrentIndex(3)  # Karnataka
    QTest.keyClicks(cb, "b")  # the disabled "Bihar – RCD SOR 2019" also starts with b
    assert _stored(page) == "INDIA/Bihar/RCD SOR 2025"


def test_missing_entry_gone_after_reload_with_valid_key(page):
    page._populate_sor_combo("India", "INDIA/Bihar/RCD SOR 2019")
    page._populate_sor_combo("India", "INDIA/Bihar/RCD SOR 2025")
    assert all(enabled for _, _, enabled in _items(page.sor_database))
    assert page.sor_database.count() == len(SHIPPED) + 1


def test_missing_key_with_no_shipped_databases(page):
    page._options.clear()
    page._populate_sor_combo("India", "INDIA/Bihar/RCD SOR 2019")
    cb = page.sor_database
    assert not cb.isEnabled()
    assert cb.currentText() == missing("INDIA/Bihar/RCD SOR 2019")
    assert _stored(page) == "INDIA/Bihar/RCD SOR 2019"


def test_no_databases_disables_combo(page):
    page._options.clear()
    page._populate_sor_combo("India", "")
    assert not page.sor_database.isEnabled()
    assert _stored(page) == ""


# ── standard dropdown behaviour ─────────────────────────────────────────────

def test_combo_is_a_plain_dropdown(page):
    cb = page.sor_database
    assert not cb.isEditable()
    assert cb.lineEdit() is None


def test_click_opens_the_list_on_the_current_item(page):
    page._populate_sor_combo("India", "INDIA/Karnataka/KPWD SOR 2023-24")
    cb = page.sor_database
    cb.show()
    QTest.mouseClick(cb, Qt.LeftButton, pos=cb.rect().center())
    assert cb.view().isVisible()
    assert cb.view().currentIndex().row() == 2
    QTest.keyClick(cb.view(), Qt.Key_Escape)
    assert not cb.view().isVisible()
    assert _stored(page) == "INDIA/Karnataka/KPWD SOR 2023-24"
    cb.hide()


@pytest.mark.parametrize("row, key", [
    (0, "INDIA/Bihar/RCD SOR 2025"),
    (3, "custom::MyDB"),
    (4, ""),
])
def test_picking_from_the_open_list(page, row, key):
    page._populate_sor_combo("India", "INDIA/Karnataka/KPWD SOR 2023-24")
    cb = page.sor_database
    cb.show()
    cb.showPopup()
    view = cb.view()
    view.setCurrentIndex(cb.model().index(row, 0))
    QTest.keyClick(view, Qt.Key_Return)
    assert not view.isVisible()
    assert _stored(page) == key
    cb.hide()


@pytest.mark.parametrize("keys, key", [
    ("b", "INDIA/Bihar/RCD SOR 2025"),
    ("ma", "INDIA/Madhya_Pradesh/MPPWD SOR 2025"),
    ("ka", "INDIA/Karnataka/KPWD SOR 2023-24"),
    ("my", "custom::MyDB"),
])
def test_type_ahead_jumps_to_an_item(page, keys, key):
    page._populate_sor_combo("India", "")  # starts on "- No suggestions -", the last item
    cb = page.sor_database
    QTest.keyClicks(cb, keys)
    assert _stored(page) == key


def test_type_ahead_searches_forward_from_the_current_item(page):
    page._populate_sor_combo("India", "INDIA/Karnataka/KPWD SOR 2023-24")
    QTest.keyClicks(page.sor_database, "m")  # MyDB comes after Karnataka, Madhya before
    assert _stored(page) == "custom::MyDB"


def test_type_ahead_with_no_match_keeps_the_choice(page):
    page._populate_sor_combo("India", "INDIA/Karnataka/KPWD SOR 2023-24")
    QTest.keyClicks(page.sor_database, "zzz")
    assert _stored(page) == "INDIA/Karnataka/KPWD SOR 2023-24"


def test_arrow_keys_step_through_the_list(page):
    page._populate_sor_combo("India", "INDIA/Bihar/RCD SOR 2025")
    cb = page.sor_database
    seen = [_stored(page)]
    for _ in range(cb.count() + 2):  # past the end: stays on the last item
        QTest.keyClick(cb, Qt.Key_Down)
        seen.append(_stored(page))
    assert seen[:5] == [o["db_key"] for o in SHIPPED] + [""]
    assert seen[-1] == ""


LONG_KEY = "INDIA/Maharashtra/Nagpur/NMC/" + "Schedule of Rates " * 20 + "2022"
SHORT_KEY = "INDIA/x"


def test_short_and_long_names_in_the_combo(page):
    page._options.extend([_opt(LONG_KEY), _opt(SHORT_KEY)])
    for key in (LONG_KEY, SHORT_KEY):
        page._populate_sor_combo("India", key)
        assert page.sor_database.currentText() == label(_opt(key))
        assert _stored(page) == key


def test_clear_all_leaves_sor_database(page, monkeypatch):
    monkeypatch.setattr(gi, "confirm_clear_all", lambda _w: True)
    page._populate_sor_combo("India", "INDIA/Karnataka/KPWD SOR 2023-24")
    page.clear_all()
    assert _stored(page) == "INDIA/Karnataka/KPWD SOR 2023-24"
