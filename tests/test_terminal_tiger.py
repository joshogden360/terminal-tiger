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
        tt.install_shell(sh)
        tt.install_shell(sh)  # idempotent
        assert tt.rc_file(sh).read_text().count(tt.MARK) == 1


def test_cli_list_and_credits(capsys):
    assert tt.main(["--list"]) == 0
    assert "tiger" in capsys.readouterr().out
    assert tt.main(["--credits"]) == 0
    out = capsys.readouterr().out
    assert "Los Angeles Tech Week 2026" in out and "CC BY-SA 4.0" in out
