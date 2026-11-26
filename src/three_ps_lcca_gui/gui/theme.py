"""
gui/theme.py - Layout and typography design tokens.

Colours are no longer defined here. Use gui.themes.get_token() instead:

    from gui.themes import get_token

    color = get_token("primary")               # full opacity
    color = get_token("danger", "disabled")    # 38 % alpha

Migration reference - old constant → new get_token() call
----------------------------------------------------------
    PRIMARY           → get_token("primary")
    PRIMARY_HOVER     → get_token("primary", "hover")
    PRIMARY_ACTIVE    → get_token("primary", "pressed")
    DANGER            → get_token("danger")
    SUCCESS           → get_token("success")
    WARNING_COLOR     → get_token("warning")
    INFO              → get_token("info")
    MUTED             → get_token("text_disabled")
    PLACEHOLDER       → get_token("text_secondary")
    VALIDATION_ERROR  → get_token("danger")
    BORDER            → get_token("border")
    CARD_BG / WHITE   → get_token("base")
    BODY_BG           → get_token("window")
    BODY_COLOR        → get_token("text")
    SECONDARY         → get_token("text_secondary")
    SURFACE           → get_token("surface")
    SURFACE_ACTIVE    → get_token("surface_pressed")
    SIDEBAR_HOVER     → get_token("surface", "hover")
    SIDEBAR_SEL       → get_token("surface", "pressed")
"""

# ── Spacing (Bootstrap spacer multiples, in px) ────────────────────────────
# Base spacer = 4 px
SP1  =  4
SP2  =  8
SP3  = 12
SP4  = 16
SP5  = 20
SP6  = 24
SP8  = 32
SP10 = 40

# ── Border radius ──────────────────────────────────────────────────────────
RADIUS_SM =  4
RADIUS_MD =  6
RADIUS_LG =  8
RADIUS_XL = 12

# ── Button heights ─────────────────────────────────────────────────────────
BTN_SM = 28   # compact / icon-adjacent
BTN_MD = 36   # standard
BTN_LG = 40   # primary CTA

# ── Component heights ──────────────────────────────────────────────────────
INPUT_MIN_H    =  30   # single-line text field
TEXTAREA_H     = 100   # multi-line text field in a form
NOTES_H        = 150   # writing area of the Notes box (remarks editor)
HIST_CARD_H    =  44   # one compact row card in the History tab
CHART_MIN_H    = 400   # a results chart never gets shorter than this
CHART_MAX_H    = 500   # pie / bar charts on the results page
AGG_CHART_MAX_H = 420  # aggregate cost chart

# ── Typography ─────────────────────────────────────────────────────────────
FONT_FAMILY = "Ubuntu"

# Point sizes (Strict 4-Tier System across the entire software)
# 1 pt ≈ 1.33 px at 96 DPI
FS_DISP    = 18   # Tier 1 (~24px) - Page Titles, Display Headings, Hero Metrics
FS_SECTION = 14   # Tier 2 (~18px) - Section Headings, Primary Card Values
FS_MD      = 10   # Tier 3 (~13px) - Body Text, Buttons, Input Fields, Paragraphs
FS_SM      =  8   # Tier 4 (~11px) - Micro, Captions, Badges, Overlines, Currency, Hints

# Font weights (match QFont.Weight int values)
# Toned down for subtler hierarchy:
# - MEDIUM:   500 -> 450
# - SEMIBOLD: 600 -> 550
# - BOLD:     700 -> 600
FW_LIGHT    = 300
FW_NORMAL   = 400
FW_MEDIUM   = 450
FW_SEMIBOLD = 550
FW_BOLD     = 600

# Centralized weight tokens for QSS substitution
QSS_WEIGHTS = {
    "weight-medium":   str(FW_MEDIUM),
    "weight-semibold": str(FW_SEMIBOLD),
    "weight-bold":     str(FW_BOLD),
}

# Centralized font size tokens for QSS substitution
QSS_FONTS = {
    "font-size-disp":    f"{FS_DISP}pt",
    "font-size-section": f"{FS_SECTION}pt",
    "font-size-md":      f"{FS_MD}pt",
    "font-size-sm":      f"{FS_SM}pt",
}

# Centralized radius tokens for QSS substitution
QSS_RADII = {
    "radius-sm": f"{RADIUS_SM}px",
    "radius-md": f"{RADIUS_MD}px",
    "radius-lg": f"{RADIUS_LG}px",
    "radius-xl": f"{RADIUS_XL}px",
}

# Centralized component height tokens for QSS substitution
QSS_HEIGHTS = {
    "notes-h": f"{NOTES_H}px",
}

# Centralized button height tokens for QSS substitution
QSS_BUTTONS = {
    "btn-sm": f"{BTN_SM}px",
    "btn-md": f"{BTN_MD}px",
    "btn-lg": f"{BTN_LG}px",
}

# ── Table column minimum widths ────────────────────────────────────────────
# Each column type gets its own floor, because a rate, a unit and a material
# name need very different widths. Each floor is a character count times
# CHAR_W_AVG, in px; it is the content width, COL_PAD_X goes on each side.
#
# Samples come from a pass over all five bundled SORs (3,512 items):
# Bihar RCD 2025, Karnataka KPWD 2023-24, MP PWD 2025, Maharashtra PWD SSR
# 2022-23, Rajasthan RUIDP ISOR 2023. Lengths are in characters.
#
#   field               avg   median  p90   max   longest word p90 / max
#   name                54.5   54      79   178   14 / 27
#   component           14.8   14      21    35   14 / 19
#   unit                 2.7    3       4    18    4 / 10
#   src_id               8.1    6      14    20   14 / 20
#   rate_src            22.4   23      25    27   11 / 11
#   carbon_emission      4.0    4       4     6    -
#   carbon unit (den)    8.0    8       8    12    -
#   conversion_factor    4.3    4       6     9    -
#   carbon source        3.6    3       3    19    3 / 18
#
#   rate value: min 0.67, median 6,036, avg 23,171, p90 60,714,
#               p99 3,03,022, max 16,00,000
#
# Text wraps between words, so a text floor only has to fit a few words, not
# the whole value. Numbers never wrap, so a number floor fits the largest
# value shown with Indian grouping and 2 decimals. Column titles can still
# widen a column past its floor.
COL_PAD_X  = SP3  # left / right space inside a cell
# Average character width of Ubuntu at FS_MD, measured on real SOR text:
# "Cement Concrete M25 Grade" 168px / 25 ch, "Super Structure" 91 / 15,
# "16,00,000.00" 72 / 12 - all 6-7 px per character.
CHAR_W_AVG = 7  # px

COL_W_NAME        = 25 * CHAR_W_AVG   # median name wraps to ~2 lines
COL_W_COMPONENT   = 15 * CHAR_W_AVG   # p90 longest word; the longest sheet name
COL_W_UNIT        =  9 * CHAR_W_AVG   # p90 is 4; long units wrap
COL_W_SRC_ID      = 12 * CHAR_W_AVG   # near p90 (14); longer ids are rare
COL_W_RATE_SRC    = 13 * CHAR_W_AVG   # wraps by word; longest word 11
COL_W_RATE        = 12 * CHAR_W_AVG   # "16,00,000.00", the largest rate in any SOR
COL_W_CARBON      =  6 * CHAR_W_AVG   # max length of an emission factor
COL_W_CARBON_UNIT = 12 * CHAR_W_AVG   # "kgCO2e/m2-mm", the longest carbon unit
COL_W_FACTOR      =  9 * CHAR_W_AVG   # the longest conversion factor
COL_W_CARBON_SRC  = 11 * CHAR_W_AVG   # wraps by word; most are 3 ("ICE")
# Not in the SORs: quantity x rate totals reach crores, "12,34,56,789.00"
COL_W_AMOUNT      = 15 * CHAR_W_AVG
COL_W_QUANTITY    = 12 * CHAR_W_AVG   # the other half of quantity x rate
COL_W_PERCENT     =  6 * CHAR_W_AVG   # "100.00"
COL_W_NOTE        = 15 * CHAR_W_AVG   # wraps by word, like a component
COL_W_DATETIME    = 16 * CHAR_W_AVG   # "20-11-2026 14:30"
COL_W_WPI         =  9 * CHAR_W_AVG   # "131.4000", a WPI ratio at 4 decimals


