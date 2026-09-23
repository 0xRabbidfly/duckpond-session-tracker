# Contributing to Duck Pond

Thanks for looking. Duck Pond is small and opinionated, so this page is mostly about the
opinions. The rules that matter are in **bold**.

## The one rule

**Every kept idea must be visible in Blender.** If a change cannot be seen on the pool, in
the card, or on the deck, it is a spec note, not a feature. When you propose something, say
where a viewer standing across the room would notice it.

The second rule follows from the data source. Duck Pond tails `~/.claude/projects` (and any
other harness log a future adapter reads). **It never writes there.** Not a lock file, not a
cache, not a marker. Read-only, always.

## Setting up

You need Blender 4.2 or newer (5.2 LTS is what the maintainer runs), Python 3.11+ on your
PATH for the pure tests, and Git.

```bat
git clone https://github.com/0xRabbidfly/duckpond-session-tracker.git
cd duckpond-session-tracker
pip install -r requirements-dev.txt          # ruff, pyinstaller, pillow: tooling only
dev\launch.cmd --stub                        # Blender UI + demo fixture
```

Set `DUCKPOND_BLENDER` to the full path of `blender.exe` if Blender is not in the default
install folder or on your PATH. On macOS or Linux, run `blender --python dev/launch.py -- --stub`
directly; the batch files and `DuckPond.exe` are Windows conveniences (see "Portability" below).

The demo fixture `fixtures/demo.json` plays four sessions and five sub-agents through every
signal the pool knows (fan-out, nested and background agents, a question, a denial, a
compaction, an error) in 75 seconds. Most work can be done against it without a live agent.

## Running the tests

```bat
ruff check .                                             # lint, configured in pyproject.toml
python tests\test_core.py                                # reducer, redaction, adapter on real logs
python tests\test_signals.py                             # questions, denials, compaction, queue, cost, inference
python tests\test_herdr.py                               # picking a Herdr pane from a session id
python tests\test_cli_version.py                         # yours vs the published CLI version
python tests\test_mosaic.py                              # per-project spend per hour, and its labels
blender -b --python tests\headless_motion.py             # the smoothness contract
blender -b --python tests\headless_smoke.py              # builds the demo, checks every visual, renders a still
blender -b --python tests\headless_director.py           # camera + sky continuity under a busy fleet
```

The pure tests run in plain Python because `duck_pond.model`, `duck_pond.theme` and
`duck_pond.adapters` import without `bpy`. Keep it that way: anything new that needs Blender
goes under `scene/`, `sim/`, `ui/` or `runtime.py`.

The GitHub Actions workflows are off: both are `workflow_dispatch` only, so nothing runs on
a push or a pull request and the checks above are the ones that count. Run them locally
before you push. To turn the runner back on, put the `push:` and `pull_request:` triggers
back in `.github/workflows/ci.yml` and `.github/workflows/blender.yml`.

## The smoothness contract

`tests/headless_motion.py` is the contract every motion change must keep. For every frame of
every duck:

- heading changes by at most 150°/s (no snaps, no flips),
- the turn rate never saws (no sign reversal with both legs above 1°),
- position never jumps (second difference bounded by what turning at top speed allows),
- displacement equals commanded speed times dt (no sliding without paddling),
- walls and ropes are avoided by steering, never by reflecting,
- a duck whose lane moved paddles back instead of teleporting.

Personality, separation, body language and the director camera all live *inside* this
contract as yaw-rate and speed terms. If you need a duck to do something new, express it as
a smooth term, run the motion test, and only then look at it in the viewport.

## What a good change looks like

- **A signal.** Find the transcript line that carries it (paste a redacted sample in the
  PR), add a parser case in `adapters/claude_code.py`, an event handler in `model.py`, a
  test in `tests/test_signals.py`, a cue, and the thing that makes it visible. Update the
  "Reading the pool" table in `README.md`.
- **Body language.** Add the term in `sim/motion.py`, keep `headless_motion.py` green, add a
  check to `headless_smoke.py` if it has an object or colour you can assert on, and render
  a still or clip into `out/` to show it.
- **A new harness.** Implement the `Adapter` class from `adapters/base.py` (its `poll`
  returns event dicts, see `docs/ARCHITECTURE.md`), give it a colour in `theme.py`, and add
  a fixture. Ducks of unknown harness already swim in open water, so start there.
- **A fix.** A failing test first if you can; the pool has been jittery before and the
  tests are how it stopped.

Small pull requests are easier to review than big ones. If you are planning something
large (a replay mode, a new adapter), open an issue first so we can agree on the shape.

## Style

- `ruff check .` must pass. Formatting is not enforced by a tool; match the file you are in
  (4 spaces, 120 columns, double quotes, f-strings).
- Type hints on public functions. Docstrings say *why*, comments say what is not obvious.
- Names in the scene are prefixed `DP_` so a pool can be found and cleared in any `.blend`.
- No new runtime dependencies. Blender's bundled Python is all there is. The pure core must
  stay standard library.
- Colours go through `theme.py`; state colours especially (`STATE_COLORS`) are shared by
  the lamp, the halo, the card, the tags and the deck dots, on purpose.
- Anything that shows user text (prompts, responses, paths) goes through `theme.redact`
  and respects the redaction toggle.

## Commits and pull requests

- One topic per pull request. Imperative subject line under 72 characters; the body says
  why and how to see it.
- Fill in the pull request template. The "How to see it" section is not optional.
- Add a line under **Unreleased** in `CHANGELOG.md` for anything a user would notice.
- Screenshots and short clips are welcome and make review much faster. `dev/render_showcase.py`
  and `dev/gui_shot.py` produce them.

## Portability

Duck Pond is developed on Windows. The add-on itself is plain `bpy` and should run wherever
Blender runs; `DuckPond.exe`, `DuckPond.cmd`, `dev/launch.cmd` and the sound cues are the
Windows-shaped parts. Reports (and fixes) from macOS and Linux are very welcome. The
`launcher/` folder is the place for a `.command` or `.desktop` equivalent.

## Where to ask

Open an issue. There is a template for bugs and one for ideas; blank issues are fine too.
Be kind: see `CODE_OF_CONDUCT.md`.
