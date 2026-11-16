DEV_MODE         = False
FLUSH_MODE       = True
ATTACH_LOGGER    = False
ALLOW_TEX        = False
COMPARISON_MODE  = True
LOCAL_API_ENABLED = True
AUTO_OPEN_FIRST_PROJECT = True  # dev only: open the first Home project on launch

if DEV_MODE == False:
    AUTO_OPEN_FIRST_PROJECT = False
