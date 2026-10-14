# Contributing

Thanks for wanting to make terminals prettier.

## Ground rules

- **One file.** The CLI lives in `terminal_tiger.py` and runs with
  `uv run terminal_tiger.py`. Keep it that way.
- **ASCII-only source.** Use `chr(0x2580)`, not the literal character. This
  lets people paste or type the script into any terminal, including browser
  terminals that drop non-ASCII input. A test enforces it.
- **Light dependencies.** Pillow and NumPy only (plus `tomli` on old Pythons).
- **Credit images.** Every preset that points at a photo needs a `credit`
  string with the author and license.

## Dev loop

```sh
uv run pytest                                     # tests
uv run terminal_tiger.py --reveal scan            # try it
uv run tools/make_demo.py /tmp/x.gif -- --no-anim # record it headless
```

## Ideas welcome

Start a thread in [Discussions → Ideas](https://github.com/joshogden360/terminal-tiger/discussions/categories/ideas), or pick one of these:

- New reveal styles (`plan_reveal` returns a start time per cell, so a new
  style is only a few lines)
- An idle animation after the reveal (a slow blink, breathing glow)
- Launchers or pets for more AI agents and terminals
- A `--gif` flag that records the reveal without a virtual terminal
- More presets made from CC0 or CC BY photos
- Windows console support
