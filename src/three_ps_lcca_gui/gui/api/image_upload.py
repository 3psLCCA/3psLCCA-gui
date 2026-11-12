"""
gui/api/image_upload.py

Lets a POST payload set an "upload_img" field (e.g. agency_logo) with a plain
http(s) image URL instead of requiring the caller to already have base64
bytes on hand. Downloads the URL to a temp file and reuses the exact same
image_file_to_base64() pipeline the GUI's own upload_img widget uses (same
compression preset, same output format), so there's no divergence between
what a user uploads by hand and what the API accepts.

Also validates raw (non-URL) base64 values the same way: the GUI's own
Browse button only ever writes base64 that already passed through
image_file_to_base64(), but an API caller can send any string directly, so
it gets the same Pillow-backed "is this actually a decodable image"
check - a caller can no longer smuggle in arbitrary garbage/binary data
through a field the GUI would only ever populate with a real image.

Format is restricted to JPEG/PNG (_ALLOWED_IMAGE_FORMATS) for both the URL
and raw-base64 paths - upload_img is currently only used for the report
cover-page organisation logo, so GIF and anything else Pillow can decode
but that isn't a sensible print-logo format is rejected.

URL fetching is locked down (a token holder could otherwise use the app
to reach things only this machine can reach):
  - only http/https, and only to PUBLIC addresses - loopback, private
    LAN, link-local (incl. cloud metadata 169.254.169.254), multicast and
    reserved ranges are refused. The check runs at connect time on the
    exact IP being connected to, so a DNS answer that flips between check
    and fetch (rebinding) can't slip past it;
  - redirects are not followed (a public URL could bounce to a private one);
  - system proxy settings are ignored (the proxy would do the connecting);
  - errors are generic - no echo of the underlying socket/HTTP error, which
    would otherwise tell the caller which internal ports are open.
Decoded images are also capped at _MAX_PIXELS so a tiny, highly
compressed file can't expand into gigabytes of RAM.

Runs entirely on the calling (Flask worker) thread - it's plain network I/O
and PIL processing, no Qt/engine access, so it belongs before the request
ever reaches ApiBridge.
"""

import base64
import binascii
import http.client
import io
import ipaddress
import os
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image, UnidentifiedImageError

from three_ps_lcca_gui.gui.components.utils.form_builder.image_utils import image_file_to_base64

from .registry import CHUNK_PAGE_MAP

_MAX_DOWNLOAD_BYTES = 15 * 1024 * 1024  # 15 MB - generous ceiling for a logo image
_ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG"}  # Pillow's own `.format` names
_MAX_PIXELS = 40_000_000  # ~ 8000 x 5000 - far beyond any sensible logo
_FETCH_TIMEOUT_S = 15


class _BlockedAddress(ValueError):
    """The URL points at an address this app refuses to fetch from."""


class _FetchFailed(ValueError):
    """Download failed - deliberately carries no detail about why."""


def _looks_like_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _open_image(fp) -> Image.Image:
    """Image.open, but Pillow's own bomb guard (DecompressionBombError,
    raised at ~179 MP before our smaller _MAX_PIXELS check can run) is
    turned into the same ValueError every caller already handles - it is
    not a ValueError/OSError subclass, so it would otherwise escape as an
    unhandled exception."""
    try:
        return Image.open(fp)
    except Image.DecompressionBombError:
        raise ValueError(f"image is too large - the limit is {_MAX_PIXELS:,} pixels")


def _assert_sane_size(img: Image.Image) -> None:
    w, h = img.size
    if w <= 0 or h <= 0 or w * h > _MAX_PIXELS:
        raise ValueError(f"image is {w}x{h} pixels - the limit is {_MAX_PIXELS:,} pixels")


def _assert_allowed_format(img: Image.Image) -> None:
    if img.format not in _ALLOWED_IMAGE_FORMATS:
        raise ValueError(
            f"unsupported image format {img.format!r} - only "
            f"{'/'.join(sorted(_ALLOWED_IMAGE_FORMATS))} logos are accepted"
        )


def _validate_base64_image(value: str) -> None:
    """Raises binascii.Error/ValueError/PIL errors if `value` isn't valid
    base64, doesn't decode to a real, fully-readable image, or isn't one of
    _ALLOWED_IMAGE_FORMATS. Deliberately does not re-encode/compress the
    result (unlike the URL path) - a caller supplying already-correct base64
    shouldn't have it silently rewritten; this only rejects what wasn't an
    acceptable image to begin with."""
    data = base64.b64decode(value, validate=True)
    if not data:
        raise ValueError("decoded to zero bytes")
    with _open_image(io.BytesIO(data)) as img:
        _assert_allowed_format(img)
        _assert_sane_size(img)
        img.verify()


def resolve_image_urls(chunk: str, payload: dict) -> tuple[dict, list[str]]:
    """For every "upload_img" field in `payload`: an http(s) URL is
    downloaded and replaced with the base64-encoded, preset-compressed image
    - exactly what the field would contain if a user had used the GUI's own
    Browse button. Any other non-empty string is checked as base64-encoded
    image data (decodable + a real, readable JPEG/PNG) but left as-is if
    valid - only genuinely invalid/wrong-format data is rejected. An empty
    string clears the field. Absent/non-string values are left untouched
    (schema validation catches the wrong type).

    Returns (payload_with_images_resolved, errors). `errors` holds one entry
    per field that failed to download/decode/validate - the caller should
    treat any entry here as a full request failure (nothing partially
    applied), same as a schema validation error."""
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
        if not isinstance(value, str):
            continue  # wrong type - schema validation catches that
        if value == "":
            continue  # empty string clears the image - same as the GUI's Clear button

        if _looks_like_url(value):
            try:
                payload[key] = _download_and_encode(value, fd.options or "default")
            except _BlockedAddress as e:
                errors.append(f"'{key}': {e}")
            except _FetchFailed:
                errors.append(
                    f"'{key}': could not download the image - the URL must be a "
                    f"publicly reachable http(s) address that returns the image "
                    f"directly (no redirects)"
                )
            except (ValueError, UnidentifiedImageError, OSError) as e:
                # Our own format/size checks, or Pillow failing to read what
                # did download - safe to report, it's about the image itself.
                msg = str(e) if type(e) is ValueError else "downloaded data is not a readable JPEG/PNG image"
                errors.append(f"'{key}': {msg}")
            except Exception:
                errors.append(f"'{key}': could not process the image")
            continue

        try:
            _validate_base64_image(value)
        except (binascii.Error, ValueError, UnidentifiedImageError, OSError) as e:
            errors.append(f"'{key}': not valid base64 image data - {e}")

    return payload, errors


def _check_public_ip(ip_str: str) -> None:
    ip = ipaddress.ip_address(ip_str.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if not ip.is_global or ip.is_multicast:
        raise _BlockedAddress(
            "image URLs must point to a public internet address - local, "
            "private-network and reserved addresses are not allowed"
        )


def _connect_public(host: str, port: int, timeout) -> socket.socket:
    """Resolve `host`, refuse if ANY answer is non-public, then connect to
    the exact address that was checked."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise _FetchFailed()
    if not infos:
        raise _FetchFailed()
    for info in infos:
        _check_public_ip(info[4][0])
    family, socktype, proto, _, addr = infos[0]
    sock = socket.socket(family, socktype, proto)
    try:
        sock.settimeout(timeout)
        sock.connect(addr)
    except OSError:
        sock.close()
        raise _FetchFailed()
    return sock


class _PublicHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = _connect_public(self.host, self.port, self.timeout)


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        sock = _connect_public(self.host, self.port, self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PublicHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PublicHTTPConnection, req)


class _PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PublicHTTPSConnection, req, context=self._context)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise _FetchFailed()


def _build_opener() -> urllib.request.OpenerDirector:
    # Assembled by hand rather than build_opener(): that one silently adds
    # ProxyHandler (env/system proxies), FTPHandler, FileHandler, DataHandler
    # and a redirect follower - none of which may be used here.
    opener = urllib.request.OpenerDirector()
    for handler in (
        _PublicHTTPHandler(),
        _PublicHTTPSHandler(),
        _NoRedirect(),
        urllib.request.HTTPErrorProcessor(),
        urllib.request.UnknownHandler(),
    ):
        opener.add_handler(handler)
    return opener


def _fetch(url: str) -> bytes:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise _FetchFailed()
    try:
        with _build_opener().open(url, timeout=_FETCH_TIMEOUT_S) as resp:
            return resp.read(_MAX_DOWNLOAD_BYTES + 1)
    except (_BlockedAddress, _FetchFailed):
        raise
    except urllib.error.URLError as e:
        # do_open() wraps connect() errors in URLError - unwrap ours.
        if isinstance(e.reason, (_BlockedAddress, _FetchFailed)):
            raise e.reason
        raise _FetchFailed()
    except Exception:
        raise _FetchFailed()


def _download_and_encode(url: str, preset) -> str:
    tmp_path = None
    try:
        data = _fetch(url)
        if len(data) > _MAX_DOWNLOAD_BYTES:
            raise ValueError(f"image exceeds {_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB limit")

        suffix = os.path.splitext(url.split("?")[0])[1][:10] or ".img"
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(data)

        with _open_image(tmp_path) as img:
            _assert_allowed_format(img)
            _assert_sane_size(img)

        return image_file_to_base64(tmp_path, preset)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
