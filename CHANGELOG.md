# Changelog

All notable changes to Duck Pond are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may change behaviour).

## [Unreleased]

### Added
- Open-source scaffolding: MIT licence, contributing guide, code of conduct, security
  policy, architecture guide, issue and pull request templates, GitHub Actions CI (ruff and
  pure tests on every push; headless Blender tests when the add-on changes).
- `DUCKPOND_BLENDER` is honoured by `DuckPond.cmd` and `dev\launch.cmd`, which fall back to
  the default install folder and then to `blender` on PATH.
- `python dev\build_exe.py --launch` rebuilds the executable, refreshes every copy and
  relaunches the pool in kiosk mode with sound.
- Usage ledger (`duck_pond/ledger.py`, `duck_pond/pricing.py`): every reply's tokens priced at
  API list rates (≈$), read from all transcripts on disk at startup and followed live. Spend no
  longer drops when ducks leave the pool or when Duck Pond restarts.
- Scoreboard range picker: `min` `hour` `day` `week` `month` tabs (click, or `T`; also in the
  sidebar). The board shows the picked range's spend, output tokens and sessions, the month so
  far on a fixed line, and ≈$ bars for the range with their peak.

### Changed
- App and kiosk mode no longer look *through* the pool camera: the viewport copies it every
  frame, so the pool fills the window with no dashed camera frame or darkened border.
- Clicking a duck, duckling or tether pins its card and tag until a click lands elsewhere in
  the pool. The click casts where it lands, so a swimming duck no longer slips out from under
  it; clicking the pinned duck again keeps it pinned, and sidebar clicks never unpin.
- App and kiosk mode: an on-screen key (top right, `H` or the sidebar toggles it) explains halo
  colour = state, body colour = tool and hat = model.
- Headless runs (`claude -p` / Agent SDK, `entrypoint: sdk-cli`, e.g. scheduled jobs that start
  in `C:\Windows\System32`) send their report up and leave when their turn ends, instead of
  sitting in the pool as "waiting for you" for 30 minutes.
- States read at a glance: working is teal whether writing or running a tool (the chip names the
  tool); waiting is a saturated yellow; idle ducks have no lamp or halo and turn grey and
  see-through. The halo glows less, so the default AgX view no longer washes its colour to cream.
- Duck names and branch flags sit on dark badges (white text over the white deck was
  unreadable); names are half the size (0.2 m) and cut at 24 characters; ducks are 15 % smaller.
- Lane signs are one screen-aligned plate per lane: folder name on top, branch · sessions · ≈$
  under it, session dots below, coins beside it. The separate floating folder name, which
  covered the details, is gone.
- A reply written as several transcript lines is counted once. `tok/min`, session token counts
  and the sparkline were inflated before.
- Lane signs show the folder's ≈$ this month; hover cards show the session's ≈$ (sub-agents
  included) beside the recorded `cost-state` total; the card footer shows ≈$ today.
- Lint clean under ruff (`E F W I B UP`); typing annotations modernised to PEP 585/604.
- README screenshots live in `docs/media/` so they render on GitHub.

## [0.2.0] - 2026-09-10

The reimagining. The pool stayed; almost everything on it changed. See `SPEC.md` §15.

### Added
- Traffic light per duck: a lamp on a pole and a halo on the water in the state colour.
  Teal working, yellow waiting (breathing; quiet after 10 minutes), red flashing blocked,
  grey idle. `awaiting_permission` is inferred from a tool unanswered for more than 12 s
  outside bypass mode.
- Tool calls as chips (`bash`, `edit`, `read`, `web`, `test`, `spawn`, ...); `tests pass` /
  `tests FAIL` with a green or red ring; `denied` with a head-shake; `asking you` for
  `AskUserQuestion`.
- Prompts fall from the sky as amber orbs; finished turns rise as gold ones. Queued prompts
  stack as letters on the tail. Compaction is a geyser. Errors bring rain. Thinking blocks
  bubble from the head.
- World: the sun follows the clock, the lido lights come on after dark and ducks glow;
  choppy water when fleet-wide token throughput is high.
- Deck: a scoreboard (working / waiting / blocked / idle, spend, tok/min, lines, sub-agents,
  30-minute token bar chart) and lane signs with branches, state dots and a coin per dollar.
- Sub-agents: nested (depth 2) ducklings orbit their parent duckling; background agents
  swim far out on a thin leash; tether style follows the sub-agent state.
- Overlay: glance (duck + beacon), hover (card with state bar, context meter, question or
  denial, current tool, last prompt and reply, tool mix), click (sidebar). Kiosk tags on
  every duck with de-overlap stacking and leader lines. Keys `K C F Home L S R P`.
- Director camera: critically damped springs with priorities blocked > question > spawn >
  compaction > error > done > prompt. Optional sound cues (`--sound`).
- Adapter reads thinking, `AskUserQuestion`, `toolDenialKind`, `queue-operation`, compaction
  boundaries, turn durations, `cost-state`, permission mode, effort, `is_error`, and
  sub-agent `.meta.json` (`parentAgentId`, `spawnDepth`, `run_in_background`).
- Personality per duck (cruising speed, wander, bob, curiosity) and lane separation,
  both as yaw-rate terms inside the smoothness contract.
- `DuckPond.exe`: a one-file Windows launcher that finds Blender, unpacks the add-on to
  `%LOCALAPPDATA%\DuckPond` and starts the pool. Flags `--fullscreen`, `--kiosk`, `--sound`,
  `--dev`, `--stub`, `--both`, `--blender <path>`.
- Tests: `tests/test_signals.py`, `tests/headless_director.py`; extended `headless_smoke.py`.
  `dev/render_showcase.py` renders stills and a clip; `dev/gui_shot.py` screenshots the GUI.

### Changed
- App mode opens in a normal maximised window (movable, minimisable); borderless
  fullscreen is opt-in with `--fullscreen`.
- Packet text rides a tether only for the hovered or pinned session.

### Removed
- The permanent "?" / "!" bubble above each duck, replaced by the traffic light.

## [0.1.0] - 2026-09-09

First draft: pool, lanes, animated water, ducks with hats, ducklings on tethers with
packets, Claude Code adapter tailing `~/.claude/projects`, hover card and sidebar,
`tests/headless_motion.py` smoothness contract.
