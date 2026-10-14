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

__version__ = "0.1.0"
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
    "bg": "#202124",        # your terminal background, for the vignette fade
    "vignette": 1.4,        # edge softness; 0 turns the vignette off
    "saturation": 1.15,
    "contrast": 1.0,
    "sharpen": 1.0,
    "width": 0,             # columns; 0 = fit the terminal
    "max_height": 0,        # rows; 0 = fit the terminal
    "reveal": "ripple",     # ripple | iris | scan | dissolve | none
    "duration": 1.6,        # seconds for the reveal wave to cross the image
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

def prepare(cfg: dict, term_cols: int, term_rows: int, title_lines: int):
    """Return (px, mask, rows, cols): px is float (rows*2, cols, 3)."""
    import numpy as np
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    resample = getattr(Image, "Resampling", Image).LANCZOS
    im = Image.open(fetch(cfg["image"]))
    im = ImageOps.exif_transpose(im).convert("RGB")
    W, H = im.size
    l, t, r, b = [float(v) for v in cfg["crop"]]
    im = im.crop((int(l * W), int(t * H), int(r * W), int(b * H)))
    im = ImageOps.autocontrast(im, cutoff=1, preserve_tone=True)
    if float(cfg["contrast"]) != 1.0:
        im = ImageEnhance.Contrast(im).enhance(float(cfg["contrast"]))
    im = ImageEnhance.Color(im).enhance(float(cfg["saturation"]))

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

    vig = float(cfg["vignette"])
    if vig > 0:
        yy, xx = np.mgrid[0:rows * 2, 0:cols]
        d = np.sqrt(((xx - cols / 2 + 0.5) / (cols / 2)) ** 2
                    + ((yy - rows + 0.5) / rows) ** 2)
        mask = np.clip((1.12 - d) / (0.3 * vig), 0, 1)
    else:
        mask = np.ones((rows * 2, cols))
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
                t = time.time() - start
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
                    time.sleep(1 / 30)
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
                    time.sleep(0.045)
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


def shell_snippet(shell: str) -> str:
    if shell == "fish":
        body = ("if status is-interactive; and type -q terminal-tiger\n"
                "    terminal-tiger --once-a-day\nend")
    else:
        body = ('if [[ $- == *i* ]] && command -v terminal-tiger >/dev/null 2>&1; then\n'
                "  terminal-tiger --once-a-day\nfi")
    return f"{MARK}\n{body}\n{MARK_END}\n"


def rc_file(shell: str) -> Path:
    home = Path.home()
    return {"bash": home / ".bashrc", "zsh": home / ".zshrc",
            "fish": home / ".config" / "fish" / "config.fish"}[shell]


def install_shell(shell: str) -> None:
    rc = rc_file(shell)
    rc.parent.mkdir(parents=True, exist_ok=True)
    text = rc.read_text() if rc.exists() else ""
    if MARK in text:
        print(f"terminal-tiger is already in {rc}")
        return
    with open(rc, "a") as fh:
        fh.write(("\n" if text and not text.endswith("\n") else "") + "\n" + shell_snippet(shell))
    print(f"Added terminal-tiger to {rc}. Open a new terminal to meet your tiger.")


def shown_today() -> bool:
    stamp = cache_dir() / "last-shown"
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
# CLI
# ----------------------------------------------------------------------------

def _pair(s: str):
    try:
        x, y = s.split(",")
        return [float(x), float(y)]
    except ValueError:
        raise argparse.ArgumentTypeError("use X,Y fractions, e.g. 0.39,0.45")


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
    g.add_argument("--bg", help="your terminal background color, #rrggbb")
    g.add_argument("--vignette", type=float, help="edge softness, 0 = off (default 1.4)")
    g.add_argument("--saturation", type=float)
    g.add_argument("--contrast", type=float)
    g.add_argument("--sharpen", type=float, help="0 = off, 1 = default")
    g = p.add_argument_group("animation")
    g.add_argument("--reveal", choices=REVEALS, help="reveal style (default ripple)")
    g.add_argument("--duration", type=float, help="seconds for the reveal wave")
    g.add_argument("--no-anim", action="store_true", help="draw instantly")
    g.add_argument("--seed", type=int, default=7, help=argparse.SUPPRESS)
    g = p.add_argument_group("terminal")
    g.add_argument("--mode", choices=MODES, help="color mode (default auto)")
    g.add_argument("--once-a-day", action="store_true", dest="once",
                   help="only show once per day (for shell startup)")
    g = p.add_argument_group("setup")
    g.add_argument("--list", action="store_true", help="list presets")
    g.add_argument("--credits", action="store_true", help="show credits and image licenses")
    g.add_argument("--shell", choices=("bash", "zsh", "fish"),
                   help="print the shell-startup snippet")
    g.add_argument("--install-shell", choices=("bash", "zsh", "fish"), dest="install",
                   help="add the startup snippet to your shell rc file")
    g.add_argument("--version", action="version", version=f"terminal-tiger {__version__}")
    return p


CLI_KEYS = ("crop", "eyes", "width", "max_height", "title", "subtitle", "accent",
            "title_color", "bg", "vignette", "saturation", "contrast", "sharpen",
            "reveal", "duration", "mode")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    conf = load_config()

    if args.shell:
        print(shell_snippet(args.shell), end="")
        return 0
    if args.install:
        install_shell(args.install)
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
