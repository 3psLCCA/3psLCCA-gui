DEV_MODE         = True
FLUSH_MODE       = True
ATTACH_LOGGER    = False
ALLOW_TEX        = False
COMPARISON_MODE  = True
AUTO_OPEN_FIRST_PROJECT = True  # dev only: open the first Home project on launch
LOG_DATA_UPDATES = True  # dev only: print Construction Works saves, and when/why Material Emissions and Recycling rebuild (and how long)

if DEV_MODE == False:
    AUTO_OPEN_FIRST_PROJECT = False
    LOG_DATA_UPDATES = False
