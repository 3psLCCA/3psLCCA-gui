"""
gui/api/pages/general_info.py

Registers the "general_info" chunk with the API. Note: the component lives
under gui/components/global_info/, but the chunk name the engine actually
stores/reads it under (and the name this page is addressed by via the API)
is "general_info" - see GeneralInfo.__init__ and GeneralInfo.get_data().
"""

from three_ps_lcca_gui.gui.components.global_info.main import (
    GENERAL_FIELDS,
    GeneralInfo,
)

from ..registry import register_chunk

register_chunk(
    "general_info",
    page_name="General Information",
    widget_cls=GeneralInfo,
    field_defs=GENERAL_FIELDS,
)
