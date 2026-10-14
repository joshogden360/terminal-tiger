#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow>=9.1", "numpy>=1.21", "pyte>=0.8"]
# ///
"""
Record terminal-tiger in a virtual terminal and save the reveal as a GIF/PNG.

Runs the real CLI inside a pseudo-terminal, timestamps every byte it writes,
replays the stream through the pyte terminal emulator and rasterizes frames.
No screen recorder needed, and it works headless (CI, servers, Cloud Shell).

    uv run tools/make_demo.py docs/demo.gif -- tiger --title tiger
    uv run tools/make_demo.py docs/me.gif --cols 100 --rows 50 -- ~/me.jpg
"""
from __future__ import annotations

import argparse
import os
import pty
import select
import struct
import subprocess
import sys
import time
from pathlib import Path

import fcntl
import termios

HERE = Path(__file__).resolve().parent
CLI = HERE.parent / "terminal_tiger.py"
HALF = chr(0x2580)


def record(cmd, cols, rows, env_extra=None, timeout=30.0):
    """Run cmd in a pty of the given size; return [(t, bytes), ...]."""
    pid, fd = pty.fork()
    if pid == 0:  # child
        env = dict(os.environ, COLORTERM="truecolor", TERM="xterm-256color",
                   COLUMNS=str(cols), LINES=str(rows))
        env.pop("TMUX", None)
        env.update(env_extra or {})
        os.execvpe(cmd[0], cmd, env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    chunks, start = [], time.time()
    while time.time() - start < timeout:
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            chunks.append((time.time() - start, data))
        else:
            done, _ = os.waitpid(pid, os.WNOHANG)
            if done:
                break
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
    return chunks


def _rgb(color, default):
    if color in (None, "default"):
        return default
    if isinstance(color, str) and len(color) == 6:
        try:
            return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    named = {"black": (0, 0, 0), "red": (205, 49, 49), "green": (13, 188, 121),
             "yellow": (229, 229, 16), "blue": (36, 114, 200), "magenta": (188, 63, 188),
             "cyan": (17, 168, 205), "white": (229, 229, 229)}
    return named.get(str(color), default)


def rasterize(screen, cw, ch, bg, fg, font):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (screen.columns * cw, screen.lines * ch), bg)
    draw = ImageDraw.Draw(img)
    for y in range(screen.lines):
        line = screen.buffer[y]
        for x in range(screen.columns):
            c = line[x]
            f = _rgb(c.fg, fg)
            b = _rgb(c.bg, bg)
            if c.reverse:
                f, b = b, f
            x0, y0 = x * cw, y * ch
            if c.data == HALF:
                draw.rectangle([x0, y0, x0 + cw - 1, y0 + ch // 2 - 1], fill=f)
                draw.rectangle([x0, y0 + ch // 2, x0 + cw - 1, y0 + ch - 1], fill=b)
            else:
                if b != bg:
                    draw.rectangle([x0, y0, x0 + cw - 1, y0 + ch - 1], fill=b)
                if c.data.strip():
                    draw.text((x0, y0 + 1), c.data, fill=f, font=font)
    return img


def main(argv=None):
    import pyte
    from PIL import ImageFont

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", help="output .gif (a .png of the last frame is saved too)")
    ap.add_argument("--cols", type=int, default=114)
    ap.add_argument("--rows", type=int, default=58)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--scale", type=float, default=1.0, help="resize output")
    ap.add_argument("--hold", type=float, default=2.5, help="seconds to hold the last frame")
    ap.add_argument("--bg", default="#202124")
    ap.add_argument("--cell", default="8x16", help="cell size in pixels, WxH (H even)")
    argv = list(sys.argv[1:] if argv is None else argv)
    cli_args = []
    if "--" in argv:  # everything after -- goes to terminal-tiger
        cut = argv.index("--")
        argv, cli_args = argv[:cut], argv[cut + 1:]
    a = ap.parse_args(argv)

    bg = tuple(int(a.bg.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    fg = (220, 220, 220)
    cw, ch = (int(v) for v in a.cell.lower().split("x"))
    try:
        font = ImageFont.truetype("DejaVuSansMono-Bold.ttf", max(6, ch - 3))
    except OSError:
        font = ImageFont.load_default()

    cmd = [sys.executable, str(CLI), *cli_args]
    chunks = record(cmd, a.cols, a.rows)
    if not chunks:
        sys.exit("make_demo: the CLI produced no output")

    screen = pyte.Screen(a.cols, a.rows)
    stream = pyte.ByteStream(screen)
    frames, durations = [], []
    step = 1.0 / a.fps
    t_end = chunks[-1][0]
    i, t = 0, 0.0
    while t <= t_end + step:
        while i < len(chunks) and chunks[i][0] <= t:
            stream.feed(chunks[i][1])
            i += 1
        frames.append(rasterize(screen, cw, ch, bg, fg, font))
        durations.append(int(step * 1000))
        t += step
    durations[-1] = int(a.hold * 1000)

    # trim identical leading frames (python start-up time)
    while len(frames) > 2 and frames[0].tobytes() == frames[1].tobytes():
        frames.pop(0)
        durations.pop(0)

    # crop every frame to the union of what was drawn (plus a margin)
    import numpy as np
    union = np.zeros((frames[0].height, frames[0].width), bool)
    for f in frames:
        union |= (np.asarray(f, dtype=int) - np.array(bg)).any(-1)
    if union.any():
        ys, xs = np.where(union)
        m = 16
        box = (max(0, xs.min() - m), max(0, ys.min() - m),
               min(frames[0].width, xs.max() + m + 1), min(frames[0].height, ys.max() + m + 1))
        frames = [f.crop(box) for f in frames]

    if a.scale != 1.0:
        from PIL import Image
        size = (int(frames[0].width * a.scale), int(frames[0].height * a.scale))
        frames = [f.resize(size, Image.NEAREST) for f in frames]

    # one shared palette for every frame: smaller files, no palette flicker
    from PIL import Image
    pal = frames[-1].quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    frames = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[-1].convert("RGB").save(out.with_suffix(".png"))
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations,
                   loop=0, optimize=True, disposal=1)
    print(f"wrote {out} ({len(frames)} frames) and {out.with_suffix('.png')}")


if __name__ == "__main__":
    main()
