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

# ── Typography ─────────────────────────────────────────────────────────────
FONT_FAMILY = "Ubuntu"

# Point sizes  (≈px at 96 dpi: 1 pt ≈ 1.33 px)
# Dashboard 8-tier scale reference:
#   Tier 8 floor      FS_XS   ~9 px   | Tier 7 reference  FS_SM   ~11 px
#   Tier 6 body       FS_MD   ~13 px  | Tier 5 card title FS_LG   ~15 px
#   Tier 4 section    FS_SECTION ~18px| Tier 3 page title FS_DISP ~24 px
#   Tier 2 primary    FS_XL   ~20 px  | Tier 1 hero       FS_DISP_LG ~29 px
FS_XS      =  7   # badge pill, tertiary hint             (Tier 8 ~9 px)
FS_SM      =  8   # caption, overline label, sort buttons (Tier 7 ~11 px)
FS_BASE    =  9   # body text, standard buttons
FS_MD      = 10   # sidebar row name, body copy           (Tier 6 ~13 px)
FS_LG      = 11   # grid card title / data label          (Tier 5 ~15 px)
FS_SECTION = 14   # outputs section heading               (Tier 4 ~18 px)
FS_SUBHEAD = 16   # content-area section heading, group divider
FS_XL      = 15   # logo / brand mark, secondary KPI      (Tier 2 ~20 px)
FS_DISP    = 18   # page title "Results"                  (Tier 3 ~24 px)
FS_DISP_LG = 22 # prominent card values
FS_DISP_XL = 32 # extra large dashboard highlights

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


