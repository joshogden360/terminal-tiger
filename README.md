<div align="center">

<img src="https://raw.githubusercontent.com/joshogden360/terminal-tiger/main/docs/demo.gif" alt="terminal-tiger: the eyes ignite, a ripple of fire sweeps the face, the title types itself out" width="560">

# terminal-tiger

**Photographic, animated portraits for your terminal and your AI coding agents.**
A tiger (or your dog, your logo, your face) that reveals itself when you open a
shell or start Claude Code, Codex or Gemini CLI.

[![CI](https://github.com/joshogden360/terminal-tiger/actions/workflows/ci.yml/badge.svg)](https://github.com/joshogden360/terminal-tiger/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-ff8c1e)](https://github.com/joshogden360/terminal-tiger/blob/main/LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3fa9ff)](https://github.com/joshogden360/terminal-tiger/blob/main/pyproject.toml)

**[Live playground](https://joshogden360.github.io/terminal-tiger/)** ·
[Quick start](#quick-start) · [AI agents](#in-claude-code-codex--gemini-cli) ·
[Make it yours](#make-it-yours) · [Share it](#share-it) · [How it works](#how-it-works)

*Built at Google for Startups · Los Angeles Tech Week 2026*

</div>

## Quick start

Try it without installing anything (needs [uv](https://docs.astral.sh/uv/)):

```sh
uv run https://raw.githubusercontent.com/joshogden360/terminal-tiger/main/terminal_tiger.py
```

Install it and set it up:

```sh
uv tool install git+https://github.com/joshogden360/terminal-tiger
tiger --install-shell --wrap
```

Open a new terminal to meet your tiger. It greets you once a day when a shell
opens. `--wrap` also plays it every time you start `claude`, `codex` or
`gemini`. Both live in one marked block in your `~/.zshrc`, `~/.bashrc` or fish
config (whichever shell you use). Delete the block to undo.

No uv? Use `pipx install git+https://github.com/joshogden360/terminal-tiger`.
The first run downloads the tiger photo into `~/.cache/terminal-tiger/`. After
that it works offline.

## In Claude Code, Codex & Gemini CLI

With `--wrap`, `claude` plays the reveal at double speed and then starts
Claude Code as usual. Ctrl-C skips straight to the agent.

- **Headless runs stay clean.** `claude -p`, `codex exec`, `gemini -p` and
  `--version` get no portrait. Neither do commands an agent runs itself,
  because they have no terminal attached.
- **IDE terminals too.** VS Code, Cursor and Antigravity load your shell, so
  their built-in terminals get the greeting and the launchers.
- **Any command.** `tiger --install-shell --wrap claude aider` wraps the
  commands you name instead.

Tune it with a `[greet]` table in your [config](#presets--config):

```toml
[greet]
preset = "cookie"     # which portrait to show (default: your default preset)
speed = 3             # animation tempo (default 2)
once_a_day = true     # only the first launch of each agent per day
```

### A pet for Codex

The Codex CLI can keep an animated pet beside its prompt. Make yours:

```sh
tiger --codex-pet             # or: tiger cookie --codex-pet
```

This writes `~/.codex/pets/tiger/`. Pick it in Codex's pet menu, or set
`pet = "custom:tiger"` under `[tui]` in `~/.codex/config.toml`. Its eyes burn
while Codex waits for you, the reveal ripple loops while it thinks, and it
turns gray when it's blocked. Codex draws pets in terminals with Kitty graphics
or Sixel (Ghostty, Kitty, WezTerm, iTerm2 3.6+, Windows Terminal), outside tmux.

## Make it yours

Any photo works. Front-facing, evenly lit, on a plain or dark background works best.

```sh
tiger ~/Pictures/cookie.jpg --title cookie
tiger https://example.com/logo.png --reveal iris --accent "#3fa9ff"
```

| Flag | What it does | Default |
| --- | --- | --- |
| `--crop L T R B` | Crop box, as fractions of the image | `0 0 1 1` |
| `--eyes X,Y X,Y` | Eye positions (fractions of the *cropped* image). The ripple starts here. | none |
| `--title TEXT` | Letter-spaced title, typed out after the reveal | `tiger` (tiger preset) |
| `--subtitle TEXT` | Dim line below. Tokens: `{user} {host} {date} {time} {cwd}` | none |
| `--accent #hex` | Color of the reveal flash and the title | `#ff8c1e` |
| `--title-color #hex` | Title color, if different from the accent | accent |
| `--bg #hex` | Your terminal background, so the vignette fades into it | asks your terminal |
| `--reveal STYLE` | `ripple` · `iris` · `scan` · `dissolve` · `none` | `ripple` |
| `--duration SEC` | How long the wave takes to cross the image | `1.6` |
| `--speed N` | Tempo of the whole animation (`2` = twice as fast) | `1` |
| `--vignette N` | Edge softness, `0` = off | `1.4` |
| `--saturation` `--contrast` `--sharpen` | Photo tuning | `1.15` `1` `1` |
| `--width` `--max-height` | Size in terminal cells | fit the terminal |
| `--mode` | `auto` · `true` (24-bit) · `direct` (old tmux) · `256` | `auto` |
| `--no-anim` | Draw instantly | |
| `--once-a-day` | Show at most once per day (for shell startup) | |

> **Finding the eyes:** open the image in any editor and read the pixel
> coordinates of each pupil. Subtract the crop's left/top edge, then divide by
> the crop's width/height. Or just guess, run it, and nudge. It takes about a minute.

### Presets & config

Save your look in `~/.config/terminal-tiger/config.toml` (see
[`examples/config.toml`](https://github.com/joshogden360/terminal-tiger/blob/main/examples/config.toml)):

```toml
preset = "cookie"            # what `tiger` shows with no arguments

[style]                      # applies to every preset
subtitle = "welcome back, {user}"

[presets.cookie]
image = "~/Pictures/cookie.jpg"
crop = [0.10, 0.00, 0.90, 0.85]
eyes = [[0.40, 0.42], [0.60, 0.42]]
title = "cookie"
accent = "#ffd166"
```

Settings are applied in this order, each overriding the last: built-in
defaults → built-in preset → `[style]` → `[presets.NAME]` → command-line flags.
Run `tiger --list` to see your presets.

## Share it

- **Your look, as a link.** Pick a reveal, accent and title in the
  [playground](https://joshogden360.github.io/terminal-tiger/), then press
  **Copy link**. Whoever opens it sees your version and gets the matching command.
- **Your preset.** A preset is a few lines of TOML, and `image` can be a URL,
  so one pasted into a gist or your dotfiles works on any machine.
- **A GIF.** [`tools/make_demo.py`](#record-your-own-demo) records the real CLI
  to a GIF, headless.
- **The showcase.** Made something great? Open a PR that adds it below.

### Showcase

<img src="https://raw.githubusercontent.com/joshogden360/terminal-tiger/main/docs/styles.png" alt="iris reveal in blue, scan reveal in green, dissolve reveal in 256-color mode" width="100%">

*Top row: mid-reveal. Bottom row: finished. Left to right: `--reveal iris --accent "#3fa9ff"`, `--reveal scan --accent "#7cff6b"`, `--mode 256 --reveal dissolve --accent "#ff4fd8"`.*

## How it works

The project started as a plain ASCII tiger that looked like static. These are
the changes that turned it into a portrait, roughly in order of impact:

1. **Half-block pixels.** Each character cell prints `▀` with a 24-bit
   *foreground* color (the top pixel) and a 24-bit *background* color (the
   bottom pixel). That gives two square-ish pixels per cell, full color, and
   no aspect-ratio squash. Brightness-ramp ASCII throws all that color away.
2. **Pick the right photo.** A dark background, a front-facing pose and both
   ears in frame mattered more than any code change.
3. **Contrast without changing the colors.** Plain `autocontrast` stretches the R, G
   and B channels separately, which turned brown fur red. `preserve_tone=True`
   stretches brightness only.
4. **A vignette** fades the edges into your terminal background, so the
   portrait floats instead of sitting in a rectangle. The background color
   comes from the terminal itself (an OSC 11 query), so it matches without setup.
5. **The tmux trap.** Google Cloud Shell runs inside **tmux 2.1**, which
   silently converts 24-bit color to 256 colors (truecolor passthrough arrived
   in tmux 2.2). `--mode direct` detects this and writes straight to the
   client's tty with `tmux display -p '#{client_tty}'`, skipping tmux entirely.
6. **A 256-color fallback that still looks good.** For terminals without
   truecolor, the image is Floyd–Steinberg dithered into the xterm-256
   palette with perceptual weights, so browns don't collapse into maroon.
7. **The reveal.** Every cell gets a start time from its distance to the eyes,
   plus a little noise, so the edge looks organic instead of a perfect circle.
   It fades up from black through a flash of the accent color. Only cells that
   change are redrawn, at roughly 30 fps. Cells are positioned with save/restore cursor and
   relative moves, so it draws *inline* under your prompt without clearing
   the screen.

### Terminal support

| Terminal | Mode picked by `auto` |
| --- | --- |
| iTerm2, WezTerm, Kitty, Ghostty, Alacritty, Windows Terminal, VS Code, Cursor, Antigravity, GNOME Terminal | `true` |
| tmux ≥ 2.2 with `set -as terminal-features ',*:RGB'` | `true` |
| tmux ≥ 2.2 without RGB enabled | `256` (add the line above to `~/.tmux.conf` for full color) |
| tmux < 2.2 (e.g. Google Cloud Shell) | `direct` |
| Apple Terminal, Linux console | `256` |

Output that is piped or redirected gets static lines with no cursor movement,
so `tiger > tiger.ans && cat tiger.ans` works.

## Record your own demo

`tools/make_demo.py` runs the real CLI inside a virtual terminal (a pty plus
[pyte](https://github.com/selectel/pyte)) and turns the byte stream into a
GIF. No screen recorder is needed, and it works headless:

```sh
uv run tools/make_demo.py docs/mine.gif --bg "#1d1f21" -- ~/me.jpg --title me --bg "#1d1f21"
```

## Development

```sh
uv run pytest            # tests: config, dithering, reveal timing, rendering, shell hooks, Codex pet
```

The CLI is a single, dependency-light file
([`terminal_tiger.py`](https://github.com/joshogden360/terminal-tiger/blob/main/terminal_tiger.py)) with inline
[PEP 723](https://peps.python.org/pep-0723/) metadata, and its source is
**ASCII-only** on purpose, so it can be pasted or typed into any terminal, even
through a browser. See [CONTRIBUTING.md](https://github.com/joshogden360/terminal-tiger/blob/main/CONTRIBUTING.md).

## Credits

- Built at **Google for Startups · Los Angeles Tech Week 2026** by
  [Josh Ogden](https://github.com/joshogden360).
- Default photo: [“Bengal Tiger Portrait”](https://commons.wikimedia.org/wiki/File:Bengal_Tiger_Portrait.jpg)
  by **Shootsalot**, licensed [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/),
  via Wikimedia Commons. The photo is **not** included in this repository. It is
  downloaded on first run.
- `docs/demo.gif`, `docs/demo.png`, `docs/styles.png`, `docs/og.png`, the pet
  preview and the cell data embedded in `docs/index.html` are renderings of
  that photo, and are shared under CC BY-SA 4.0. See [CREDITS.md](https://github.com/joshogden360/terminal-tiger/blob/main/CREDITS.md).
- Code: [MIT](https://github.com/joshogden360/terminal-tiger/blob/main/LICENSE).
