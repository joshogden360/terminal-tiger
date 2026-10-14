"""Smoke + unit tests. Run with: uv run --with pytest --with pillow --with numpy pytest"""
import io
import os
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import terminal_tiger as tt  # noqa: E402


@pytest.fixture
def photo(tmp_path):
    """A synthetic 'face': orange disc with two dark eyes on a dark background."""
    w, h = 240, 260
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), np.uint8) + 20
    face = ((xx - w / 2) / 100) ** 2 + ((yy - h / 2) / 115) ** 2 < 1
    img[face] = (230, 130, 40)
    for ex in (0.38, 0.62):
        eye = (xx - ex * w) ** 2 + (yy - 0.45 * h) ** 2 < 12 ** 2
        img[eye] = (250, 200, 60)
    p = tmp_path / "face.png"
    Image.fromarray(img).save(p)
    return p


def test_source_is_ascii_only():
    # keeps the script pasteable into any terminal (no exotic characters)
    src = Path(tt.__file__).read_bytes()
    assert all(b < 128 for b in src)


def test_hex_rgb():
    assert tt.hex_rgb("#ff8c1e") == (255, 140, 30)
    assert tt.hex_rgb("fff") == (255, 255, 255)
    with pytest.raises(SystemExit):
        tt.hex_rgb("not-a-color")


def test_resolve_precedence():
    conf = {"style": {"accent": "#111111"},
            "presets": {"tiger": {"title": "rawr"}, "cookie": {"image": "c.jpg"}}}
    cfg = tt.resolve(None, {"accent": None, "bg": "#000000"}, conf)
    assert cfg["name"] == "tiger"
    assert cfg["accent"] == "#111111"          # [style] beats built-in
    assert cfg["title"] == "rawr"              # [presets.tiger] beats [style]
    assert cfg["bg"] == "#000000"              # CLI beats everything
    assert tt.resolve("cookie", {}, conf)["image"] == "c.jpg"
    assert tt.resolve("/x/dog.png", {}, {})["image"] == "/x/dog.png"


def test_template_keeps_unknown_tokens():
    out = tt.fill_template("hi {user} {nope}")
    assert "{nope}" in out and "{user}" not in out


def test_palette_and_dither():
    px = np.random.default_rng(0).random((6, 5, 3)) * 255
    q = tt.dither256(px)
    assert q.shape == (6, 5) and q.min() >= 16 and q.max() <= 255
    assert tt.nearest256([[255, 0, 0]])[0] == 196


@pytest.mark.parametrize("reveal", ["ripple", "iris", "scan", "dissolve"])
def test_plan_reveal(reveal):
    rows, cols = 10, 16
    live = np.ones((rows, cols), bool)
    t0, fade, glow, eye = tt.plan_reveal(reveal, rows, cols, live, [(5, 9), (11, 9)], 1.0)
    assert t0.shape == (rows, cols) and (t0 > 0).all()
    assert (eye.any()) == (reveal == "ripple")
    if reveal == "ripple":  # eyes ignite before the rest of the face
        assert t0[eye].max() < t0[~eye].min()


def test_shade_endpoints():
    c = np.array([[100.0, 50.0, 25.0]])
    acc = np.array([255.0, 140.0, 30.0])
    assert (tt.shade_cells(c, np.array([0.0]), np.array([0.5]), acc) == 0).all()
    assert (tt.shade_cells(c, np.array([1.0]), np.array([0.5]), acc) == c.astype(int)).all()


@pytest.mark.parametrize("mode", ["true", "256"])
def test_render_piped(photo, mode, monkeypatch, capsys):
    monkeypatch.setenv("COLUMNS", "60")
    monkeypatch.setenv("LINES", "30")
    cfg = tt.resolve(str(photo), {"mode": mode, "title": "test", "subtitle": "hi {user}"}, {})
    tt.render(cfg, animate=False, out_is_tty=False)
    out = capsys.readouterr().out
    assert tt.HALF in out
    assert ("38;2;" in out) == (mode == "true")
    assert ("38;5;" in out) == (mode == "256")
    assert "T  E  S  T" in out
    assert len(out.splitlines()) <= 30


def test_shell_snippets_and_install(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(tt.Path, "home", classmethod(lambda cls: tmp_path))
    for sh in ("bash", "zsh", "fish"):
        snip = tt.shell_snippet(sh)
        assert tt.MARK in snip and "--once-a-day" in snip
        tt.rc_file(sh).parent.mkdir(parents=True, exist_ok=True)
        tt.rc_file(sh).write_text("export KEEP=me\n")
        tt.install_shell(sh)
        tt.install_shell(sh)  # idempotent
        assert tt.rc_file(sh).read_text().count(tt.MARK) == 1
        tt.install_shell(sh, tt.AGENTS)  # re-running with --wrap updates the block
        text = tt.rc_file(sh).read_text()
        assert text.count(tt.MARK) == 1 and text.startswith("export KEEP=me\n")
        assert all(f"--greet {cmd}" in text for cmd in tt.AGENTS)
    with pytest.raises(SystemExit):
        tt.shell_snippet("zsh", ["rm -rf /"])


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_wrapper_runs_the_real_command(tmp_path, shell):
    """The launcher greets, then runs the real command with the same args."""
    import shutil
    import subprocess
    if not shutil.which(shell):
        pytest.skip(f"{shell} not installed")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, line in (("terminal-tiger", "echo TIGER \"$@\""), ("claude", "echo CLAUDE \"$@\"")):
        (bin_dir / name).write_text(f"#!/bin/sh\n{line}\n")
        (bin_dir / name).chmod(0o755)
    rc = tmp_path / "rc"
    rc.write_text(tt.shell_snippet(shell, ["claude"]))
    script = f'source "{rc}"; claude -c "fix the bug"'
    out = subprocess.run([shell, "-i", "-c", script], capture_output=True, text=True,
                         env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)},
                         stdin=subprocess.DEVNULL).stdout.splitlines()
    assert out == ["TIGER --once-a-day", "TIGER --greet claude -c fix the bug",
                   "CLAUDE -c fix the bug"]


def test_parse_osc_color():
    assert tt.parse_osc_color(b"\x1b]11;rgb:5a5a/5a5a/5a5a\x1b\\\x1b[?62;22c") == "#5a5a5a"
    assert tt.parse_osc_color(b"\x1b]11;rgb:ff/80/00\x07") == "#ff8000"
    assert tt.parse_osc_color(b"\x1b[?1;2c") is None  # answered DA1 only


@pytest.mark.skipif(os.name != "posix", reason="needs a pty")
@pytest.mark.parametrize("answers, expected", [
    ({b"\x1b]11;?": b"\x1b]11;rgb:1d1d/1f1f/2121\x1b\\", b"\x1b[c": b"\x1b[?62;22c"}, "#1d1f21"),
    ({b"\x1b[c": b"\x1b[?1;2c"}, "None"),  # no OSC 11 support
    ({}, "None"),                          # answers nothing: times out
])
def test_query_background_in_a_pty(answers, expected):
    """Play the terminal: answer the queries the CLI writes, like a real one would."""
    import pty
    import select
    import subprocess
    import time
    m, s = pty.openpty()
    code = "import terminal_tiger as tt; print(tt.query_background())"
    p = subprocess.Popen([sys.executable, "-c", code], stdin=s, stdout=s, stderr=s,
                         cwd=Path(tt.__file__).parent)
    os.close(s)
    out, seen, start = b"", b"", time.time()
    while time.time() - start < 10:
        if not select.select([m], [], [], 0.05)[0]:
            if p.poll() is not None:
                break
            continue
        try:
            chunk = os.read(m, 1024)
        except OSError:
            break
        if not chunk:  # macOS: EOF once the child exits
            break
        seen += chunk
        for query, reply in answers.items():
            if query in seen:
                os.write(m, reply)
                seen = seen.replace(query, b"")
        out += chunk
    p.wait()
    assert time.time() - start < 2
    # the printed result follows the (unanswered) query bytes on the same line
    assert out.decode(errors="replace").strip().endswith(expected)


def test_wants_greeting():
    assert tt.wants_greeting("claude", [])
    assert tt.wants_greeting("claude", ["-c"])
    assert tt.wants_greeting("claude", ["fix the bug"])
    assert tt.wants_greeting("codex", ["resume"])
    assert tt.wants_greeting("codex", ["-p", "work"])  # codex -p is --profile
    assert not tt.wants_greeting("claude", ["-p", "hi"])
    assert not tt.wants_greeting("codex", ["exec", "hi"])
    assert not tt.wants_greeting("gemini", ["--prompt", "hi"])
    assert not tt.wants_greeting("anything", ["--version"])


def test_greet_stays_quiet_without_a_terminal(capsys):
    # under pytest stdin/stdout are not a tty, like an agent running a command
    assert tt.main(["--greet", "claude", "--", "-x"]) == 0
    assert capsys.readouterr().out == ""


def test_codex_pet(photo, tmp_path):
    import json
    cfg = tt.resolve(str(photo), {"eyes": [[0.38, 0.45], [0.62, 0.45]], "title": "face"}, {})
    out = tt.write_codex_pet(cfg, home=tmp_path)
    assert out == tmp_path / "pets" / "face"
    manifest = json.loads((out / "pet.json").read_text())
    assert manifest["displayName"] == "Face"
    fw, fh = tt.PET_FRAME
    cols, rows = tt.PET_GRID
    assert manifest["frame"] == {"width": fw, "height": fh, "columns": cols, "rows": rows}
    sheet = Image.open(out / manifest["spritesheetPath"]).convert("RGBA")
    assert sheet.size == (fw * cols, fh * rows)  # Codex rejects any other size
    alpha = np.asarray(sheet)[..., 3]
    recipes = tt.pet_rows()
    assert len(recipes) == rows
    for r in range(rows):
        for c in range(cols):
            cell = alpha[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw]
            assert (cell.max() > 0) == (c < len(recipes[r]))  # every used frame drawn
            assert cell[0, 0] == 0  # corners fade out to transparent


def test_cli_list_and_credits(capsys):
    assert tt.main(["--list"]) == 0
    assert "tiger" in capsys.readouterr().out
    assert tt.main(["--credits"]) == 0
    out = capsys.readouterr().out
    assert "Los Angeles Tech Week 2026" in out and "CC BY-SA 4.0" in out
