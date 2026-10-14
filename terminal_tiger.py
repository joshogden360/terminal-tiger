#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "pillow>=9.1",
#   "numpy>=1.21",
#   "tomli>=1.1; python_version < '3.11'",
# ]
# ///
"""
terminal-tiger - photographic, animated ANSI portraits for your terminal.

Turns any photo into a half-block, 24-bit color portrait with an animated
reveal: the eyes ignite in the dark, a ripple of fire sweeps the face,
the eyes glint, and your title types itself out.

    uv run terminal_tiger.py                 # the tiger
    uv run terminal_tiger.py ~/me.jpg        # your own photo
    uv run terminal_tiger.py --help          # every knob

Built at Google for Startups - Los Angeles Tech Week 2026.
MIT License (code). Default image: see CREDITS.md.
https://github.com/joshogden360/terminal-tiger
"""
from __future__ import annotations

import argparse
import datetime as _dt
import getpass
import hashlib
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

__version__ = "0.2.0"
REPO = "https://github.com/joshogden360/terminal-tiger"
EVENT = "Built at Google for Startups - Los Angeles Tech Week 2026"

ESC = "\x1b"
HALF = chr(0x2580)  # upper half block: fg paints the top pixel, bg the bottom

# ----------------------------------------------------------------------------
# Presets & defaults
# ----------------------------------------------------------------------------

DEFAULTS = {
    "image": None,          # path or http(s) URL
    "crop": [0.0, 0.0, 1.0, 1.0],   # left, top, right, bottom as fractions
    "eyes": [],             # [[x, y], ...] fractions of the cropped image
    "title": "",
    "subtitle": "",         # supports {user} {host} {date} {time} {cwd}
    "accent": "#ff8c1e",    # color of the reveal flash and the title
    "title_color": None,    # defaults to accent
    "bg": "auto",           # your terminal background, for the vignette fade
                            # (auto = ask the terminal, else FALLBACK_BG)
    "vignette": 1.4,        # edge softness; 0 turns the vignette off
    "saturation": 1.15,
    "contrast": 1.0,
    "sharpen": 1.0,
    "width": 0,             # columns; 0 = fit the terminal
    "max_height": 0,        # rows; 0 = fit the terminal
    "reveal": "ripple",     # ripple | iris | scan | dissolve | none
    "duration": 1.6,        # seconds for the reveal wave to cross the image
    "speed": 1.0,           # tempo of the whole animation; 2 = twice as fast
    "mode": "auto",         # auto | true | direct | 256
    "credit": "",
}

PRESETS = {
    "tiger": {
        "image": "https://commons.wikimedia.org/wiki/Special:FilePath/"
                 "Bengal_Tiger_Portrait.jpg?width=1200",
        "crop": [0.08, 0.02, 0.64, 0.92],
        "eyes": [[0.39, 0.45], [0.64, 0.44]],
        "title": "tiger",
        "accent": "#ff8c1e",
        "credit": '"Bengal Tiger Portrait" by Shootsalot, CC BY-SA 4.0, via '
                  "Wikimedia Commons - https://commons.wikimedia.org/wiki/"
                  "File:Bengal_Tiger_Portrait.jpg",
    },
}

FALLBACK_BG = "#202124"
SHELLS = ("bash", "zsh", "fish")
REVEALS = ("ripple", "iris", "scan", "dissolve", "none")
MODES = ("auto", "true", "direct", "256")


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "terminal-tiger"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "terminal-tiger"


def load_config(path: Path | None = None) -> dict:
    path = path or (config_dir() / "config.toml")
    if not path.exists():
        return {}
    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:  # Python < 3.11
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            warn("config.toml found but tomli is not installed; ignoring it")
            return {}
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def resolve(source: str | None, cli: dict, conf: dict) -> dict:
    """DEFAULTS < built-in preset < [style] < [presets.NAME] < CLI flags."""
    user_presets = conf.get("presets", {}) or {}
    name = source or conf.get("preset") or "tiger"
    cfg = dict(DEFAULTS)
    if name in PRESETS or name in user_presets:
        cfg.update(PRESETS.get(name, {}))
        cfg.update(conf.get("style", {}) or {})
        cfg.update(user_presets.get(name, {}))
        cfg["name"] = name
    else:  # treat the source as an image path or URL
        cfg.update(conf.get("style", {}) or {})
        cfg["image"] = name
        cfg["name"] = Path(name).stem if "://" not in name else "image"
    cfg.update({k: v for k, v in cli.items() if v is not None})
    if not cfg.get("image"):
        raise SystemExit(f"terminal-tiger: preset '{name}' has no image")
    return cfg


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------

def warn(msg: str) -> None:
    sys.stderr.write(f"terminal-tiger: {msg}\n")


def hex_rgb(s: str) -> tuple:
    s = str(s).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", s):
        raise SystemExit(f"terminal-tiger: bad color '{s}', use #rrggbb")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def fill_template(text: str) -> str:
    now = _dt.datetime.now()
    try:
        user = getpass.getuser()
    except Exception:
        user = "you"
    cwd = os.getcwd().replace(str(Path.home()), "~", 1)
    return str(text).format_map(_Safe(
        user=user, host=socket.gethostname().split(".")[0],
        date=now.strftime("%a %b %d %Y"), time=now.strftime("%H:%M"),
        cwd=cwd, version=__version__))


def fetch(src: str) -> Path:
    """Return a local path for src, downloading (once) into the cache."""
    if not re.match(r"https?://", src):
        return Path(src).expanduser()
    d = cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    out = d / (hashlib.sha1(src.encode()).hexdigest()[:16] + ".img")
    if not out.exists():
        tmp = out.with_suffix(".part")
        req = urllib.request.Request(src, headers={
            "User-Agent": f"terminal-tiger/{__version__} (+{REPO})"})
        with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as fh:
            shutil.copyfileobj(r, fh)
        tmp.replace(out)
    return out


# ----------------------------------------------------------------------------
# Terminal capability detection
# ----------------------------------------------------------------------------

def _tmux(*args: str) -> str:
    return subprocess.run(["tmux", *args], capture_output=True, text=True,
                          timeout=3).stdout.strip()


def tmux_version():
    try:
        m = re.search(r"(\d+)\.(\d+)", _tmux("-V"))
        return (int(m.group(1)), int(m.group(2))) if m else None
    except Exception:
        return None


def parse_osc_color(reply: bytes):
    """'#rrggbb' from a terminal's OSC 11 reply (rgb:RRRR/GGGG/BBBB), else None."""
    m = re.search(rb"\]11;rgba?:([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})", reply)
    if not m:
        return None
    return "#" + "".join(f"{int(h, 16) * 255 // (16 ** len(h) - 1):02x}" for h in m.groups())


def query_background(timeout: float = 0.25):
    """Ask the terminal for its background color (OSC 11), or None.

    A device-attributes query (DA1) goes out right behind it. Every terminal
    answers DA1, so its reply marks the end: no waiting out the timeout on
    terminals that ignore OSC 11, and no late reply leaking into your prompt.
    """
    if os.name != "posix" or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    import select
    import termios
    import tty
    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
    except termios.error:
        return None
    reply = b""
    try:
        tty.setcbreak(fd)
        sys.stdout.flush()
        os.write(sys.stdout.fileno(), b"\x1b]11;?\x1b\\\x1b[c")
        end = time.time() + timeout
        while not re.search(rb"\x1b\[\?[0-9;]*c", reply):
            left = end - time.time()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                break
            reply += os.read(fd, 1024)
    except OSError:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return parse_osc_color(reply)


def detect_shell():
    name = Path(os.environ.get("SHELL", "")).name
    return name if name in SHELLS else None


def detect_mode() -> str:
    if os.environ.get("TMUX"):
        v = tmux_version()
        if v is not None and v < (2, 2):
            # tmux < 2.2 cannot pass 24-bit color: paint the outer tty directly
            return "direct"
        try:
            info = _tmux("info")
        except Exception:
            info = ""
        if re.search(r"\b(Tc|RGB): \(flag\) true", info):
            return "true"
        return "256"
    colorterm = os.environ.get("COLORTERM", "").lower()
    if colorterm in ("truecolor", "24bit"):
        return "true"
    if os.environ.get("TERM", "") in ("linux", "dumb"):
        return "256"
    if os.environ.get("TERM_PROGRAM") == "Apple_Terminal":
        return "256"
    return "true"


# ----------------------------------------------------------------------------
# Image pipeline
# ----------------------------------------------------------------------------

def load_photo(cfg: dict):
    """The cropped, tone-corrected photo as a PIL RGB image."""
    from PIL import Image, ImageEnhance, ImageOps

    im = Image.open(fetch(cfg["image"]))
    im = ImageOps.exif_transpose(im).convert("RGB")
    W, H = im.size
    l, t, r, b = [float(v) for v in cfg["crop"]]
    im = im.crop((int(l * W), int(t * H), int(r * W), int(b * H)))
    im = ImageOps.autocontrast(im, cutoff=1, preserve_tone=True)
    if float(cfg["contrast"]) != 1.0:
        im = ImageEnhance.Contrast(im).enhance(float(cfg["contrast"]))
    return ImageEnhance.Color(im).enhance(float(cfg["saturation"]))


def vignette_mask(h: int, w: int, vig: float):
    """1 in the middle, fading to 0 toward the edges; all ones when vig is 0."""
    import numpy as np
    if vig <= 0:
        return np.ones((h, w))
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.sqrt(((xx - w / 2 + 0.5) / (w / 2)) ** 2 + ((yy - h / 2 + 0.5) / (h / 2)) ** 2)
    return np.clip((1.12 - d) / (0.3 * vig), 0, 1)


def prepare(cfg: dict, term_cols: int, term_rows: int, title_lines: int):
    """Return (px, mask, rows, cols): px is float (rows*2, cols, 3)."""
    import numpy as np
    from PIL import Image, ImageFilter

    resample = getattr(Image, "Resampling", Image).LANCZOS
    im = load_photo(cfg)
    w, h = im.size
    max_cols = max(8, term_cols - 2)
    cols = min(int(cfg["width"]) or max_cols, max_cols)
    max_rows = max(4, term_rows - 2 - title_lines)
    if int(cfg["max_height"]):
        max_rows = min(max_rows, int(cfg["max_height"]))
    rows = max(1, round(h / w * cols / 2))
    if rows > max_rows:
        rows = max_rows
        cols = max(1, round(rows * 2 * w / h))

    im = im.resize((cols, rows * 2), resample)
    if float(cfg["sharpen"]) > 0:
        im = im.filter(ImageFilter.UnsharpMask(1.2, int(70 * float(cfg["sharpen"])), 3))
    px = np.asarray(im, dtype=float)
    mask = vignette_mask(rows * 2, cols, float(cfg["vignette"]))
    bg = np.array(hex_rgb(cfg["bg"]), dtype=float)
    px = px * mask[..., None] + bg * (1 - mask[..., None])
    return px, mask, rows, cols


# xterm-256 color cube + grayscale ramp (indices 16..255)
def _palette():
    import numpy as np
    lv = [0, 95, 135, 175, 215, 255]
    cube = [(r, g, b) for r in lv for g in lv for b in lv]
    gray = [(8 + 10 * i,) * 3 for i in range(24)]
    return np.array(cube + gray, dtype=float)


_WEIGHTS = (2.0, 4.0, 1.0)  # rough perceptual weighting (eye loves green)


def nearest256(rgb):
    import numpy as np
    pal = _palette()
    rgb = np.asarray(rgb, dtype=float).reshape(-1, 3)
    d = (((rgb[:, None, :] - pal[None]) ** 2) * np.array(_WEIGHTS)).sum(-1)
    return 16 + d.argmin(1)


def dither256(px):
    """Perceptual Floyd-Steinberg dither into the xterm-256 palette."""
    import numpy as np
    pal = _palette()
    wt = np.array(_WEIGHTS)
    img = px.astype(float).copy()
    h, w, _ = img.shape
    out = np.zeros((h, w), dtype=int)
    for y in range(h):
        for x in range(w):
            c = np.clip(img[y, x], 0, 255)
            k = int((((pal - c) ** 2) * wt).sum(1).argmin())
            out[y, x] = 16 + k
            e = (c - pal[k]) * 0.8
            if x + 1 < w:
                img[y, x + 1] += e * 7 / 16
            if y + 1 < h:
                if x > 0:
                    img[y + 1, x - 1] += e * 3 / 16
                img[y + 1, x] += e * 5 / 16
                if x + 1 < w:
                    img[y + 1, x + 1] += e / 16
    return out


# ----------------------------------------------------------------------------
# Canvas: where and how cells get painted
# ----------------------------------------------------------------------------

class Canvas:
    """Paints cells at (row, col) offsets inside a reserved block of lines.

    inline (true / 256): reserves space under the prompt and uses
        save/restore cursor + relative moves, so nothing is cleared.
    direct: for tmux < 2.2, clears the pane and writes 24-bit color straight
        to the client tty, bypassing tmux's 256-color downgrade.
    """

    def __init__(self, mode: str, height: int):
        self.mode = mode
        self.height = height
        if mode == "direct":
            sys.stdout.write(f"{ESC}[2J{ESC}[H")
            sys.stdout.flush()
            time.sleep(0.25)
            self.top = int(_tmux("display", "-p", "#{pane_top}") or 0)
            self.left = int(_tmux("display", "-p", "#{pane_left}") or 0)
            self.out = open(_tmux("display", "-p", "#{client_tty}"), "w")
        else:
            self.out = sys.stdout
            self.out.write("\n" * height + (f"{ESC}[{height}A" if height else "")
                           + "\r" + f"{ESC}7")
        self.out.write(f"{ESC}[?25l")
        self.out.flush()

    def goto(self, r: int, c: int) -> str:
        if self.mode == "direct":
            return f"{ESC}[{self.top + r + 2};{self.left + c + 1}H"
        s = f"{ESC}8"
        if r:
            s += f"{ESC}[{r}B"
        if c:
            s += f"{ESC}[{c}C"
        return s

    def write(self, s: str) -> None:
        self.out.write(s)
        self.out.flush()

    def close(self) -> None:
        if self.mode == "direct":
            self.out.write(f"{ESC}[?25h{ESC}[{self.top + 1};{self.left + 1}H")
            self.out.flush()
            self.out.close()
            sys.stdout.write("\n" * (self.height + 2))
        else:
            self.out.write(self.goto(self.height, 0) + f"{ESC}[?25h")
        sys.stdout.flush()


def cell_codes(mode: str, top, bot) -> list:
    """Escape codes for N cells. true: top/bot are (N,3) RGB; 256: (N,) idx."""
    if mode == "256":
        return [f"{ESC}[38;5;{int(a)}m{ESC}[48;5;{int(b)}m{HALF}"
                for a, b in zip(top, bot)]
    return [f"{ESC}[38;2;{a[0]};{a[1]};{a[2]}m{ESC}[48;2;{b[0]};{b[1]};{b[2]}m{HALF}"
            for a, b in zip(top, bot)]


def paint(canvas: Canvas, c0: int, idx, codes) -> None:
    buf, last_r, last_c = [], -9, -9
    for (r, c), code in zip(idx, codes):
        if not (r == last_r and c == last_c + 1):
            buf.append(canvas.goto(int(r), c0 + int(c)))
        buf.append(code)
        last_r, last_c = r, c
    if buf:
        canvas.write("".join(buf) + f"{ESC}[0m")


# ----------------------------------------------------------------------------
# Reveal choreography (pure functions, shared with tools/make_demo.py)
# ----------------------------------------------------------------------------

def plan_reveal(reveal: str, rows: int, cols: int, live, eyes, duration: float, seed: int = 7):
    """Per-cell start time, fade length, flash strength and eye mask.

    ripple   - eyes ignite first, then a wave spreads outward from them
    iris     - a wave opens from the focus point (eyes, or the center)
    scan     - a ragged curtain sweeps top to bottom
    dissolve - cells appear in random order
    """
    import numpy as np
    rng = np.random.default_rng(seed)
    gy, gx = np.mgrid[0:rows, 0:cols]
    py_, px_ = gy * 2 + 1.0, gx + 0.5
    if eyes:
        fx = sum(e[0] for e in eyes) / len(eyes)
        fy = sum(e[1] for e in eyes) / len(eyes)
    else:
        fx, fy = cols / 2, float(rows)
    if reveal in ("ripple", "iris"):
        d = np.hypot(px_ - fx, py_ - fy)
    elif reveal == "scan":
        d = gy + rng.random((rows, cols)) * 2.5
    else:  # dissolve
        d = rng.random((rows, cols))
    d = d / max(1e-6, float(d[live].max()) if live.any() else 1.0)
    jitter = 0.0 if reveal == "dissolve" else rng.random((rows, cols)) * 0.12
    lead = 1.1 if (reveal == "ripple" and eyes) else 0.15
    t0 = lead + (d + jitter) * duration
    eye = np.zeros((rows, cols), bool)
    if reveal == "ripple":
        for ex, ey in eyes:
            eye |= np.hypot(px_ - ex, py_ - ey) < cols * 0.05
        t0[eye] = 0.2 + rng.random(int(eye.sum())) * 0.3
    fade = np.where(eye, 0.9, 0.45)
    glow = np.where(eye, 0.9, 0.5)
    return t0, fade, glow, eye


def shade_cells(c, p, g, accent):
    """Color of cells at progress p in [0,1]: fade up from black with a
    flash of the accent color that peaks halfway through."""
    import numpy as np
    e = (p * p * (3 - 2 * p))[..., None]
    bump = (np.sin(np.pi * p) * g)[..., None]
    return np.clip(c * e + accent * bump, 0, 255).astype(int)


# ----------------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------------

def render(cfg: dict, animate: bool = True, out_is_tty: bool = True, seed: int = 7) -> None:
    import numpy as np

    tc, tl = shutil.get_terminal_size((100, 40))
    title = str(cfg.get("title") or "")
    subtitle = fill_template(cfg.get("subtitle") or "")
    title_lines = (1 if title else 0) + (1 if subtitle else 0)

    if str(cfg["bg"]).lower() == "auto":
        cfg = {**cfg, "bg": (query_background() if out_is_tty else None) or FALLBACK_BG}
    mode = cfg["mode"] if cfg["mode"] != "auto" else detect_mode()
    if mode == "direct" and not os.environ.get("TMUX"):
        mode = "true"

    px, mask, rows, cols = prepare(cfg, tc, tl, title_lines)
    final = np.clip(px, 0, 255)
    top_rgb, bot_rgb = final[0::2], final[1::2]
    live = ~((mask[0::2] <= 0) & (mask[1::2] <= 0))
    c0 = max(0, (tc - cols) // 2)

    if mode == "256":
        q = dither256(final)
        fin_top, fin_bot = q[0::2], q[1::2]
    else:
        fin_top, fin_bot = top_rgb.astype(int), bot_rgb.astype(int)

    accent = np.array(hex_rgb(cfg["accent"]), dtype=float)
    tcolor = hex_rgb(cfg.get("title_color") or cfg["accent"])
    if mode == "256":
        title_sgr = f"{ESC}[1;38;5;{int(nearest256([tcolor])[0])}m"
    else:
        title_sgr = f"{ESC}[1;38;2;{tcolor[0]};{tcolor[1]};{tcolor[2]}m"
    title_txt = "  ".join(title.upper()) if title else ""

    # Not a terminal (piped / redirected): emit plain static lines.
    if not out_is_tty:
        for r in range(rows):
            cells = np.argwhere(np.ones(cols, bool))[:, 0]
            codes = cell_codes(mode, fin_top[r][cells], fin_bot[r][cells])
            line = "".join(f"{ESC}[0m " if not live[r, c] else codes[i]
                           for i, c in enumerate(cells))
            sys.stdout.write(" " * c0 + line + f"{ESC}[0m\n")
        if title_txt:
            sys.stdout.write(" " * max(0, (tc - len(title_txt)) // 2)
                             + title_sgr + title_txt + f"{ESC}[0m\n")
        if subtitle:
            sys.stdout.write(" " * max(0, (tc - len(subtitle)) // 2) + subtitle + "\n")
        return

    canvas = Canvas(mode, rows + title_lines)
    reveal = cfg["reveal"] if animate else "none"
    speed = max(0.1, float(cfg.get("speed") or 1.0))
    eyes = [(float(x) * cols, float(y) * rows * 2) for x, y in (cfg.get("eyes") or [])]
    eye = np.zeros((rows, cols), bool)

    def final_codes(ix):
        return cell_codes(mode, fin_top[ix[:, 0], ix[:, 1]], fin_bot[ix[:, 0], ix[:, 1]])

    try:
        if reveal == "none":
            for r in range(rows):
                ix = np.argwhere(live[r:r + 1]) + [r, 0]
                paint(canvas, c0, ix, final_codes(ix))
        else:
            t0, fade, glow, eye = plan_reveal(reveal, rows, cols, live, eyes,
                                              float(cfg["duration"]), seed)
            steps = 6
            state = np.zeros((rows, cols), int)
            t_end = float(t0[live].max() + fade.max()) if live.any() else 0.0

            def shade(c, p, g):
                return shade_cells(c, p, g, accent)

            start = time.time()
            while True:
                t = (time.time() - start) * speed
                qn = np.round(np.clip((t - t0) / fade, 0, 1) * steps).astype(int)
                ch = np.argwhere((qn != state) & live)
                if len(ch):
                    r_, c_ = ch[:, 0], ch[:, 1]
                    p = qn[r_, c_] / steps
                    g = glow[r_, c_]
                    a = shade(top_rgb[r_, c_], p, g)
                    b = shade(bot_rgb[r_, c_], p, g)
                    if mode == "256":
                        a, b = nearest256(a), nearest256(b)
                        done = p >= 1
                        a[done] = fin_top[r_[done], c_[done]]
                        b[done] = fin_bot[r_[done], c_[done]]
                    paint(canvas, c0, ch, cell_codes(mode, a, b))
                    state[r_, c_] = qn[r_, c_]
                if t > t_end:
                    break
                time.sleep(1 / 30)

            # a glint in the eyes
            ei = np.argwhere(eye & live)
            if len(ei):
                for k in range(1, 21):
                    g = 0.6 * math.sin(math.pi * k / 20)
                    a = np.clip(top_rgb[ei[:, 0], ei[:, 1]] * (1 + g) + accent * g * 0.35, 0, 255).astype(int)
                    b = np.clip(bot_rgb[ei[:, 0], ei[:, 1]] * (1 + g) + accent * g * 0.35, 0, 255).astype(int)
                    if mode == "256":
                        a, b = nearest256(a), nearest256(b)
                    paint(canvas, c0, ei, cell_codes(mode, a, b))
                    time.sleep(1 / 30 / speed)
                paint(canvas, c0, ei, final_codes(ei))
    except KeyboardInterrupt:  # Ctrl-C skips straight to the finished portrait
        ix = np.argwhere(live)
        paint(canvas, c0, ix, final_codes(ix))
        animate = False

    try:
        row = rows
        if title_txt:
            x0 = max(0, (tc - len(title_txt)) // 2)
            color = title_sgr
            if animate:
                for i in range(1, len(title_txt) + 1):
                    canvas.write(canvas.goto(row, x0) + color + title_txt[:i] + f"{ESC}[0m")
                    time.sleep(0.045 / speed)
            else:
                canvas.write(canvas.goto(row, x0) + color + title_txt + f"{ESC}[0m")
            row += 1
        if subtitle:
            x0 = max(0, (tc - len(subtitle)) // 2)
            canvas.write(canvas.goto(row, x0) + f"{ESC}[2m" + subtitle + f"{ESC}[0m")
    finally:
        canvas.close()


# ----------------------------------------------------------------------------
# Shell integration
# ----------------------------------------------------------------------------

MARK = "# >>> terminal-tiger >>>"
MARK_END = "# <<< terminal-tiger <<<"


AGENTS = ("claude", "codex", "gemini")

# Arguments that run an agent CLI headless: there is no TUI to greet, and the
# output may be read by a script, so the portrait stays out of the way.
HEADLESS_FLAGS = {"-h", "--help", "-v", "-V", "--version"}
HEADLESS = {
    "claude": ({"-p", "--print"},
               {"agents", "auth", "auto-mode", "doctor", "gateway", "install", "mcp",
                "plugin", "project", "setup-token", "ultrareview", "update"}),
    "codex": (set(),
              {"exec", "e", "review", "login", "logout", "mcp", "plugin", "mcp-server",
               "app-server", "remote-control", "app", "completion", "update", "doctor",
               "sandbox", "debug", "apply", "a", "archive", "unarchive", "cloud",
               "exec-server", "features", "help"}),
    "gemini": ({"-p", "--prompt"},
               {"mcp", "extensions", "extension", "skills", "skill", "hooks", "hook",
                "gemma"}),
}


def shell_snippet(shell: str, wrap=()) -> str:
    """The rc-file block: a once-a-day greeting, plus a launcher function for
    each command in `wrap` that shows the portrait before the command starts."""
    for cmd in wrap:
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", cmd):
            raise SystemExit(f"terminal-tiger: can't wrap '{cmd}'")
    if shell == "fish":
        lines = ["if status is-interactive; and type -q terminal-tiger",
                 "    terminal-tiger --once-a-day"]
        for cmd in wrap:
            lines += [f"    function {cmd} --wraps {cmd}",
                      f"        terminal-tiger --greet {cmd} $argv",
                      f"        command {cmd} $argv",
                      "    end"]
        lines.append("end")
    else:
        lines = ['if [[ $- == *i* ]] && command -v terminal-tiger >/dev/null 2>&1; then',
                 "  terminal-tiger --once-a-day"]
        # `function NAME {` rather than `NAME() {` so an alias can't break it
        lines += [f'  function {cmd} {{ terminal-tiger --greet {cmd} "$@"; command {cmd} "$@"; }}'
                  for cmd in wrap]
        lines.append("fi")
    return MARK + "\n" + "\n".join(lines) + "\n" + MARK_END + "\n"


def rc_file(shell: str) -> Path:
    home = Path.home()
    return {"bash": home / ".bashrc", "zsh": home / ".zshrc",
            "fish": home / ".config" / "fish" / "config.fish"}[shell]


def install_shell(shell: str, wrap=()) -> None:
    rc = rc_file(shell)
    rc.parent.mkdir(parents=True, exist_ok=True)
    text = rc.read_text() if rc.exists() else ""
    block = shell_snippet(shell, wrap)
    start = text.find(MARK)
    end = text.find(MARK_END, start)
    if start >= 0 and end >= 0:  # replace the existing block in place
        end += len(MARK_END) + (text[end + len(MARK_END):].startswith("\n"))
        if text[start:end] == block:
            print(f"terminal-tiger is already in {rc}")
            return
        rc.write_text(text[:start] + block + text[end:])
        print(f"Updated terminal-tiger in {rc}. Open a new terminal to see it.")
        return
    with open(rc, "a") as fh:
        fh.write(("\n" if text and not text.endswith("\n") else "") + "\n" + block)
    print(f"Added terminal-tiger to {rc}. Open a new terminal to meet your tiger.")
    if wrap:
        print("Launching " + ", ".join(wrap) + " from a new terminal shows it too.")


def wants_greeting(cmd: str, args) -> bool:
    """False when an agent CLI is being run headless (`claude -p`, `codex exec`)."""
    flags, subcommands = HEADLESS.get(cmd, (set(), set()))
    if any(a in flags or a in HEADLESS_FLAGS for a in args):
        return False
    return not (args and args[0] in subcommands)


def greet(argv, conf: dict | None = None) -> int:
    """Show the portrait before an agent CLI starts its TUI (see --wrap).
    Always exits 0 and never raises, so it can't stop the agent launching."""
    cmd, rest = (os.path.basename(argv[0]), argv[1:]) if argv else ("", [])
    if not (sys.stdin.isatty() and sys.stdout.isatty()) or not wants_greeting(cmd, rest):
        return 0
    try:
        conf = load_config() if conf is None else conf
        opts = dict(conf.get("greet") or {})
        if opts.pop("once_a_day", False) and shown_today("greeted-" + cmd):
            return 0
        _, term_rows = shutil.get_terminal_size((100, 40))
        cli = {"speed": 2.0, "max_height": max(8, term_rows // 2)}
        cli.update({k: v for k, v in opts.items() if k in DEFAULTS})
        render(resolve(opts.get("preset"), cli, conf))
    except KeyboardInterrupt:
        pass
    except (Exception, SystemExit) as e:
        warn(f"skipped the greeting ({e})")
    return 0


def shown_today(name: str = "last-shown") -> bool:
    stamp = cache_dir() / name
    today = _dt.date.today().isoformat()
    try:
        if stamp.read_text().strip() == today:
            return True
    except OSError:
        pass
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(today)
    except OSError:
        pass
    return False


# ----------------------------------------------------------------------------
# Codex CLI pet: the portrait as an animated sprite in the Codex TUI
# ----------------------------------------------------------------------------

# Codex reads pets from $CODEX_HOME/pets/NAME/pet.json + a spritesheet that must
# be exactly 8 x 9 frames of 192 x 208 px. Each row is one animation, in the
# order Codex expects when pet.json lists no animations of its own.
PET_FRAME = (192, 208)
PET_GRID = (8, 9)


def pet_rows() -> list:
    """Frame recipes (keyword args for pet_frame), one list per spritesheet row."""
    breath = [0.0, 0.5, 0.8, 0.6, 0.3, 0.0]
    return [
        # 0 idle: a slow breath, the eyes glint near the end
        [dict(scale=1 + 0.015 * b, glow=g) for b, g in zip(breath, [0, 0, 0, .3, .6, .1])],
        # 1 running-right, 2 running-left: a ring of fire leaves the eyes
        [dict(ring=k / 7, glow=.4, dx=2) for k in range(8)],
        [dict(ring=k / 7, glow=.4, dx=-2) for k in range(8)],
        # 3 waving: a head tilt
        [dict(angle=a) for a in (-5, 0, 5, 0)],
        # 4 jumping: a hop
        [dict(dy=-d) for d in (0, 8, 12, 8, 0)],
        # 5 failed ("Blocked"): drained of color, head down
        [dict(sat=.2, gain=.6 + .05 * (k % 2), dy=3) for k in range(8)],
        # 6 waiting ("Needs input"): the eyes burn brighter and brighter
        [dict(glow=g) for g in (.2, .5, .9, 1.2, .9, .5)],
        # 7 running ("Thinking"): the reveal ripple, looping
        [dict(ring=k / 5, glow=.5) for k in range(6)],
        # 8 review ("Ready"): a shine sweeps across the face
        [dict(shine=k / 5, glow=.3) for k in range(6)],
    ]


def pet_base(cfg: dict):
    """(rgb, alpha, eyes): the photo covering one frame, its vignette as alpha,
    and the eye positions in frame pixels."""
    import numpy as np
    from PIL import Image

    fw, fh = PET_FRAME
    im = load_photo(cfg)
    w, h = im.size
    s = max(fw / w, fh / h)
    nw, nh = max(fw, round(w * s)), max(fh, round(h * s))
    im = im.resize((nw, nh), getattr(Image, "Resampling", Image).LANCZOS)
    ox, oy = (nw - fw) // 2, (nh - fh) // 2
    rgb = np.asarray(im.crop((ox, oy, ox + fw, oy + fh)), dtype=float)
    alpha = vignette_mask(fh, fw, float(cfg["vignette"]))
    eyes = [(float(x) * nw - ox, float(y) * nh - oy) for x, y in (cfg.get("eyes") or [])]
    return rgb, alpha, eyes


def pet_frame(rgb, alpha, eyes, accent, glow=0.0, ring=None, shine=None,
              sat=1.0, gain=1.0, scale=1.0, angle=0.0, dx=0, dy=0):
    """One RGBA frame: the portrait lit with the accent color, then moved."""
    import numpy as np
    from PIL import Image

    fh, fw = alpha.shape
    yy, xx = np.mgrid[0:fh, 0:fw]
    c = rgb
    if sat != 1.0:
        gray = c.mean(-1, keepdims=True)
        c = gray + (c - gray) * sat
    light = np.zeros((fh, fw))
    for ex, ey in eyes:
        light += glow * np.exp(-((xx - ex) ** 2 + (yy - ey) ** 2) / (2 * 7.0 ** 2))
    if ring is not None:
        fx, fy = (np.mean(eyes, axis=0) if eyes else (fw / 2, fh / 2))
        radius = 8 + ring * 0.75 * math.hypot(fw, fh)
        light += 0.7 * (1 - ring) * np.exp(-((np.hypot(xx - fx, yy - fy) - radius) / 10) ** 2)
    if shine is not None:
        u = (xx + yy) / float(fw + fh) * 1.4 - 0.2
        light += 0.5 * np.exp(-((u - shine) / 0.06) ** 2)
    c = np.clip(c * gain + np.array(accent, float) * light[..., None], 0, 255)
    im = Image.fromarray(np.dstack([c, alpha * 255]).astype(np.uint8), "RGBA")

    bicubic = getattr(Image, "Resampling", Image).BICUBIC
    if angle:
        im = im.rotate(angle, resample=bicubic, center=(fw / 2, fh * 0.7))
    if scale != 1.0:
        sw, sh = round(fw * scale), round(fh * scale)
        big = im.resize((sw, sh), bicubic)
        im = Image.new("RGBA", (fw, fh))
        im.paste(big, ((fw - sw) // 2, (fh - sh) // 2))
    if dx or dy:
        moved = Image.new("RGBA", (fw, fh))
        moved.paste(im, (dx, dy))
        im = moved
    return im


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def write_codex_pet(cfg: dict, home: Path | None = None) -> Path:
    """Write pets/NAME/{pet.json, spritesheet} into the Codex home; return the dir."""
    import json
    from PIL import Image, features

    fw, fh = PET_FRAME
    rgb, alpha, eyes = pet_base(cfg)
    accent = hex_rgb(cfg["accent"])
    sheet = Image.new("RGBA", (fw * PET_GRID[0], fh * PET_GRID[1]))
    for r, row in enumerate(pet_rows()):
        for c, recipe in enumerate(row):
            sheet.paste(pet_frame(rgb, alpha, eyes, accent, **recipe), (c * fw, r * fh))

    name = re.sub(r"[^a-z0-9_-]+", "-", str(cfg["name"]).lower()).strip("-") or "pet"
    out = (home or codex_home()) / "pets" / name
    out.mkdir(parents=True, exist_ok=True)
    if features.check("webp"):  # what Codex's own pets use
        sheet_file = "spritesheet.webp"
        sheet.save(out / sheet_file, quality=90)
    else:
        sheet_file = "spritesheet.png"
        sheet.save(out / sheet_file)
    title = str(cfg.get("title") or name)
    manifest = {
        "id": name,
        "displayName": title[:1].upper() + title[1:],
        "description": f"{title} - made with terminal-tiger",
        "spritesheetPath": sheet_file,
        "frame": {"width": fw, "height": fh, "columns": PET_GRID[0], "rows": PET_GRID[1]},
    }
    (out / "pet.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return out


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def _pair(s: str):
    try:
        x, y = s.split(",")
        return [float(x), float(y)]
    except ValueError:
        raise argparse.ArgumentTypeError("use X,Y fractions, e.g. 0.39,0.45")


def _shell(s: str) -> str:
    if s not in SHELLS + ("auto",):
        raise argparse.ArgumentTypeError(f"use one of: {', '.join(SHELLS)}")
    return s


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="terminal-tiger",
        description="Photographic, animated ANSI portraits for your terminal.",
        epilog=f"{EVENT}. {REPO}")
    p.add_argument("source", nargs="?", help="preset name, image path, or image URL (default: tiger)")
    g = p.add_argument_group("framing")
    g.add_argument("--crop", type=float, nargs=4, metavar=("L", "T", "R", "B"),
                   help="crop box as fractions of the image")
    g.add_argument("--eyes", type=_pair, nargs="+", metavar="X,Y",
                   help="eye positions (fractions of the cropped image) for the ripple")
    g.add_argument("--width", type=int, help="width in columns (default: fit)")
    g.add_argument("--max-height", type=int, dest="max_height", help="max rows")
    g = p.add_argument_group("style")
    g.add_argument("--title", help="title under the portrait ('' for none)")
    g.add_argument("--subtitle", help="dim line under the title; {user} {host} {date} {time} {cwd}")
    g.add_argument("--accent", help="reveal flash + title color, #rrggbb")
    g.add_argument("--title-color", dest="title_color", help="title color, #rrggbb")
    g.add_argument("--bg", help="your terminal background color, #rrggbb "
                                "(default: ask the terminal)")
    g.add_argument("--vignette", type=float, help="edge softness, 0 = off (default 1.4)")
    g.add_argument("--saturation", type=float)
    g.add_argument("--contrast", type=float)
    g.add_argument("--sharpen", type=float, help="0 = off, 1 = default")
    g = p.add_argument_group("animation")
    g.add_argument("--reveal", choices=REVEALS, help="reveal style (default ripple)")
    g.add_argument("--duration", type=float, help="seconds for the reveal wave")
    g.add_argument("--speed", type=float, help="animation tempo, 2 = twice as fast (default 1)")
    g.add_argument("--no-anim", action="store_true", help="draw instantly")
    g.add_argument("--seed", type=int, default=7, help=argparse.SUPPRESS)
    g = p.add_argument_group("terminal")
    g.add_argument("--mode", choices=MODES, help="color mode (default auto)")
    g.add_argument("--once-a-day", action="store_true", dest="once",
                   help="only show once per day (for shell startup)")
    g = p.add_argument_group("setup")
    g.add_argument("--list", action="store_true", help="list presets")
    g.add_argument("--credits", action="store_true", help="show credits and image licenses")
    g.add_argument("--shell", choices=SHELLS,
                   help="print the shell-startup snippet")
    g.add_argument("--install-shell", nargs="?", const="auto", type=_shell, metavar="SHELL",
                   dest="install",
                   help="add the startup snippet to your shell rc file "
                        "(default: the shell you use now)")
    g.add_argument("--wrap", nargs="*", metavar="CMD",
                   help="with --shell/--install-shell: also show the portrait when these "
                        f"commands start (default: {' '.join(AGENTS)})")
    g.add_argument("--greet", nargs=argparse.REMAINDER, metavar="CMD",
                   help="show the portrait before CMD's TUI starts, unless CMD is "
                        "running headless (used by --wrap)")
    g.add_argument("--codex-pet", action="store_true", dest="codex_pet",
                   help="save the portrait as an animated pet for the Codex CLI")
    g.add_argument("--version", action="version", version=f"terminal-tiger {__version__}")
    return p


CLI_KEYS = ("crop", "eyes", "width", "max_height", "title", "subtitle", "accent",
            "title_color", "bg", "vignette", "saturation", "contrast", "sharpen",
            "reveal", "duration", "speed", "mode")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["--greet"]:  # pass the wrapped command's args through untouched
        return greet(argv[1:])
    args = build_parser().parse_args(argv)
    conf = load_config()
    wrap = () if args.wrap is None else (args.wrap or AGENTS)

    if args.greet is not None:
        return greet(args.greet, conf)
    if args.shell:
        print(shell_snippet(args.shell, wrap), end="")
        return 0
    if args.install:
        shell = detect_shell() if args.install == "auto" else args.install
        if not shell:
            warn("couldn't tell which shell you use; add bash, zsh or fish")
            return 2
        install_shell(shell, wrap)
        return 0
    if args.list:
        names = list(PRESETS) + [n for n in (conf.get("presets") or {}) if n not in PRESETS]
        default = conf.get("preset") or "tiger"
        for n in names:
            pr = {**PRESETS.get(n, {}), **(conf.get("presets", {}) or {}).get(n, {})}
            star = "*" if n == default else " "
            print(f"{star} {n:<14} {pr.get('image', '')}")
        return 0
    if args.credits:
        print(f"terminal-tiger {__version__} - {EVENT}\n{REPO}\n")
        for n, pr in PRESETS.items():
            if pr.get("credit"):
                print(f"[{n}] {pr['credit']}")
        return 0

    if args.once and (not sys.stdout.isatty() or shown_today()):
        return 0

    cli = {k: getattr(args, k) for k in CLI_KEYS}
    cfg = resolve(args.source, cli, conf)
    try:
        if args.codex_pet:
            out = write_codex_pet(cfg)
            print(f"Saved a Codex pet to {out}\n"
                  f"Turn it on: pick it in Codex's pet menu, or add this to "
                  f"{codex_home() / 'config.toml'}:\n\n"
                  f'  [tui]\n  pet = "custom:{out.name}"\n\n'
                  "Pets show in terminals with Kitty graphics or Sixel (Ghostty, Kitty, "
                  "WezTerm, iTerm2 3.6+, Windows Terminal), outside tmux.")
            return 0
        render(cfg, animate=not args.no_anim, out_is_tty=sys.stdout.isatty(), seed=args.seed)
    except FileNotFoundError as e:
        warn(f"image not found: {e.filename}")
        return 1
    except OSError as e:
        warn(f"could not load image ({e}). Check your connection or pass a local path.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
