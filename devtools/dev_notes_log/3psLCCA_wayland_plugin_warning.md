# 3psLCCA — "Could not find the Qt platform plugin wayland" warning

**Status: cosmetic, not a bug.** This is unrelated to the segfault covered in
`3psLCCA_fontconfig_segfault_fix.md`. That crash is fixed; this is a separate,
harmless console message that can optionally be silenced.

**Symptom:**
```
qt.qpa.plugin: Could not find the Qt platform plugin "wayland" in ""
```
printed every time `threePSLCCA` is launched on this machine, with no other
visible effect — the app still opens and runs normally.

---

## 1. What's actually happening

Qt picks a "platform plugin" at startup to talk to the windowing system —
`xcb` for X11, `wayland` for native Wayland, `windows` on Windows, `cocoa` on
macOS, plus a few headless ones (`offscreen`, `minimal`, `eglfs`...). If
`QT_QPA_PLATFORM` isn't set explicitly, Qt **auto-detects** which one to try
first based on the session environment (e.g. it prefers `wayland` when
`WAYLAND_DISPLAY`/`XDG_SESSION_TYPE=wayland` is set).

This machine's installed Qt only ships these platform plugins:
```
libqeglfs.so  libqlinuxfb.so  libqminimalegl.so  libqminimal.so
libqoffscreen.so  libqvkkhrdisplay.so  libqvnc.so  libqxcb.so
```
There's no `libqwayland*.so` at all — this particular Qt build (from
conda-forge) simply doesn't include the Wayland plugin. Building/bundling it
requires extra system Wayland client libraries that conda-forge's PySide6
recipe doesn't link against, so it's commonly left out. (The official Qt
Company wheels on PyPI *do* usually bundle a Wayland plugin — this is
specific to where this particular Qt build came from, not a property of
PySide6 in general.)

So at startup, on this session:
1. `XDG_SESSION_TYPE=wayland` → Qt tries the `wayland` plugin first.
2. Not found → prints the warning.
3. Qt falls through its platform list and lands on `xcb`, which **is**
   present.
4. Ubuntu (and most Linux desktops) run **XWayland** alongside the native
   Wayland compositor for exactly this kind of backward compatibility, so
   `DISPLAY=:0` is also set. The `xcb` plugin connects through XWayland and
   the app renders normally.

The warning is just Qt being verbose about step 2 before step 3/4 quietly
succeed.

---

## 2. Behavior across platforms

| Platform / session | Plugin Qt tries first | Result |
|---|---|---|
| Linux, Wayland session, XWayland present (this machine, most distros today) | `wayland` → not found, warning printed | Falls back to `xcb` via XWayland → **works**, just noisy |
| Linux, X11 session (`XDG_SESSION_TYPE=x11`) | `xcb` directly | **Works**, no warning at all — `wayland` is never attempted |
| Linux, Wayland session with **no** XWayland installed/enabled (rare today; some minimal/embedded or future "Wayland-only" distro configs) | `wayland` → not found, warning printed | `xcb` also fails (no `DISPLAY`) → app **fails to start** — this is the one case that needs the real long-term fix in §4 |
| Windows | `windows` (native, always bundled) | No such plugin-selection step happens — this warning is **impossible** on Windows |
| macOS | `cocoa` (native, always bundled) | Same — this warning is **impossible** on macOS |

In other words: this warning can only ever appear on Linux, and on every
Linux setup actually tested here it's harmless. It would only become a real
failure on a Linux session that is Wayland-only with no XWayland — not the
case on this machine.

---

## 3. Optional fix: silence it (Linux only, safe everywhere else)

Force Qt straight to `xcb`, skipping the `wayland` lookup (and its warning)
entirely:
```bash
QT_QPA_PLATFORM=xcb /home/renu/threePSLCCA/bin/threePSLCCA
```

To make this the default without requiring the env var every time, add a
guard in `three_ps_lcca_gui/gui/main.py`, **before** the `PySide6` import,
that only acts on Linux and only if the user hasn't already set a preference:
```python
import platform, os
if platform.system() == "Linux" and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "xcb"
```
This is safe across platforms by construction:
- **Windows/macOS:** the `platform.system() == "Linux"` check skips it
  entirely — zero effect, zero risk.
- **Linux + X11:** no-op in practice, `xcb` was already going to be chosen.
- **Linux + Wayland + XWayland (this machine):** skips straight to `xcb`,
  warning disappears, identical rendering result as today.
- **Linux + Wayland, no XWayland:** would still fail to start — forcing
  `xcb` doesn't fix that case, it just fails slightly faster/differently.
  See §4 if that environment needs to be supported.
- Respects an explicit override: if `QT_QPA_PLATFORM` is already set in the
  environment (e.g. someone testing with `QT_QPA_PLATFORM=offscreen` for
  CI), this code does nothing, since it only sets it when absent.

This is purely cosmetic — it does not change what was actually happening at
runtime, just skips the doomed `wayland` attempt before falling back.

---

## 4. If true Wayland-only support is ever needed

Forcing `xcb` everywhere (§3) only works because XWayland is present. If
this app needs to run on a session with **no XWayland at all**, `xcb` isn't
a fallback option, and the real fix is to get a Qt build that actually
includes the `wayland` platform plugin (`libqwaylandcompositor`, `libqwayland-egl`,
etc.), e.g. by switching this dependency to the official PySide6 wheel from
PyPI (built by The Qt Company, which generally bundles Wayland support) for
the Linux build of this app, instead of conda-forge's `pyside6` package —
similar in spirit to the `fontconfig` version pin in the other document:
pin the actual package/build that's known to behave correctly, rather than
patching around a gap in whichever build happened to get installed. This is
**not currently necessary** — flagged here only so it's clear what the next
step would be if a fully Wayland-native target environment comes up later.

---

## Appendix: commands used to confirm this

```bash
# Which platform plugins does this Qt build actually ship?
ls /home/renu/threePSLCCA/lib/qt6/plugins/platforms/

# Session details that drive Qt's auto-detection
echo "XDG_SESSION_TYPE=$XDG_SESSION_TYPE WAYLAND_DISPLAY=$WAYLAND_DISPLAY DISPLAY=$DISPLAY"

# Confirm the app runs fine even with the warning present (no QT_QPA_PLATFORM set)
PYTHONFAULTHANDLER=1 timeout 8 /home/renu/threePSLCCA/bin/threePSLCCA
# exit 124 (timeout killed a still-running process) = healthy, warning is harmless

# Confirm forcing xcb silences the warning with no behavior change
QT_QPA_PLATFORM=xcb PYTHONFAULTHANDLER=1 timeout 8 /home/renu/threePSLCCA/bin/threePSLCCA
```
