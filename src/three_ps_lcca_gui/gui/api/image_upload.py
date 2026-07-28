"""
gui/api/image_upload.py

Lets a POST payload set an "upload_img" field (e.g. agency_logo) with a plain
http(s) image URL instead of requiring the caller to already have base64
bytes on hand. Downloads the URL to a temp file and reuses the exact same
image_file_to_base64() pipeline the GUI's own upload_img widget uses (same
compression preset, same output format), so there's no divergence between
what a user uploads by hand and what the API accepts.

Runs entirely on the calling (Flask worker) thread - it's plain network I/O
and PIL processing, no Qt/engine access, so it belongs before the request
ever reaches ApiBridge.
"""

import os
import tempfile
import urllib.request

from three_ps_lcca_gui.gui.components.utils.form_builder.image_utils import image_file_to_base64

from .registry import CHUNK_PAGE_MAP

_MAX_DOWNLOAD_BYTES = 15 * 1024 * 1024  # 15 MB - generous ceiling for a logo image


def _looks_like_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def resolve_image_urls(chunk: str, payload: dict) -> tuple[dict, list[str]]:
    """For every "upload_img" field in `payload` whose value is an http(s)
    URL, downloads it and replaces the value with the base64-encoded,
    preset-compressed image - exactly what the field would contain if a user
    had used the GUI's own Browse button. Values that aren't URLs (already
    base64, or absent) are left untouched.

    Returns (payload_with_images_resolved, errors). `errors` holds one entry
    per field that failed to download/decode - the caller should treat any
    entry here as a full request failure (nothing partially applied), same
    as a schema validation error."""
    entry = CHUNK_PAGE_MAP.get(chunk)
    if entry is None or entry["field_defs"] is None:
        return payload, []

    field_defs = {fd.key: fd for fd in entry["field_defs"] if hasattr(fd, "field_type")}
    payload = dict(payload)
    errors: list[str] = []

    for key, value in list(payload.items()):
        fd = field_defs.get(key)
        if fd is None or fd.field_type != "upload_img":
            continue
        if not isinstance(value, str) or not _looks_like_url(value):
            continue  # already base64 (or the wrong type - schema validation catches that)

        try:
            payload[key] = _download_and_encode(value, fd.options or "default")
        except Exception as e:
            errors.append(f"'{key}': failed to fetch/convert image from {value!r} - {e}")

    return payload, errors


def _download_and_encode(url: str, preset) -> str:
    tmp_path = None
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = resp.read(_MAX_DOWNLOAD_BYTES + 1)
        if len(data) > _MAX_DOWNLOAD_BYTES:
            raise ValueError(f"image exceeds {_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB limit")

        suffix = os.path.splitext(url.split("?")[0])[1][:10] or ".img"
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(data)

        return image_file_to_base64(tmp_path, preset)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
