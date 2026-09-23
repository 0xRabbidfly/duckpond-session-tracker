# Changelog

All notable changes to Duck Pond are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may change behaviour).

## [Unreleased]

### Added
- **The deck mosaic.** One row per project, one tile per hour, brightness for spend, set into
  the near paving -- the largest piece of the frame that had nothing in it. The board says
  what the whole fleet spent in the last day; this says which folder spent it and when, which
  is the question you have when you come back and the number is bigger than you left it. An
  overnight run reads as a bright band at 03:00 in one row and nothing in the others. Rows run
  in the lane signs' own order, so a row is the lane above it, and the range follows the
  board's, so `T` cycles both. What it says is a pure value (`cards.heat_model`) with the
  painting separate (`scene/mosaic.py`), and `ledger.cwd_bars` is the new query behind it.
- **A banner plane.** Every two and a half minutes a propeller plane crosses the sky towing
  a banner: the published Claude Code version on the top row, the one you are running
  underneath, and `UPDATE` when you are behind. Yours comes from `claude --version`, the
  published one from the npm registry over plain HTTP -- no npm install required -- both on
  a worker thread, refreshed every three hours. The plate sizes itself to the rows, because
  a version string is not a fixed width. No reading, no flypast (`duck_pond/cli_version.py`,
  `duck_pond/scene/plane.py`).
- **Click a duck, get its terminal**: with [Herdr](https://herdr.dev) running, clicking a duck
  focuses the pane running that session and raises the window Herdr is showing in. The join is
  on the Claude session id, which `herdr agent list` reports per pane and the duck is named
  for, so it never matches on a terminal title. On a worker thread, silent when Herdr is not
  installed, and off in the sidebar (`duck_pond/herdr.py`).
  Raising the window takes three tries: `SetForegroundWindow` alone, then the same with
  the foreground thread's input queue attached, then a topmost flip, which needs no
  permission at all. Windows refuses the first outright when it decides another app owns
  your attention, and it says so in a return code rather than an exception, so the first
  cut of this failed in silence.
- **Sangria jugs**: two jugs on the far deck fill with your Anthropic 5-hour and 7-day usage,
  with the percentage and reset time on a label above each. Read from `claude -p /usage` on a
  worker thread every 15 minutes (`duck_pond/usage_limits.py`), with `--no-session-persistence`
  so the reading does not itself appear in the pool as a duck. Off, and the interval, in the
  sidebar; a headless run never starts it, so no test or render spends a token.
- **Watchdog**: a timer that re-arms playback, the data timer, the frame handler and the
  adapter worker when any of them stops. Playback had stopped on its own (waking from sleep),
  which froze the pond on a stale frame for 26 minutes while the data side kept running.
- **Context ring**: every duck wears one at all times, coloured green → yellow → orange →
  magenta as its context window fills. It replaced a life ring that only appeared at 95 %.
- **Pool toys**: a flamingo float, a rubber ring, two beach balls, a noodle and two lily pads
  drifting at the edges. They carry no data, which is the point.
- **Grass and a tiled deck**: the deck is dark grey paving, and a procedural lawn runs ninety
  metres past it. The scene used to stop at the paving, and a window wider than the render
  showed the world background past it as flat grey bands.
- `tests/test_herdr.py`, `tests/test_usage.py` and `tests/headless_watchdog.py`; `test_ledger.py` and `test_usage.py`
  added to the CI matrix.

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
- **The context ring is banded, not blended, and a full duck's ring has holes in it.** Four
  bands with the numbers on the key: green to 20 %, yellow to 50 %, red to 80 %, and above
  that a black ring, punctured -- the ring has stopped floating. A gradient gave every duck
  its own shade of the same story; what you want from across the room is which band it is
  in, and a band is a thing the key can put a number on (it now reads `to 20 %`, `to 50 %`,
  `to 80 %`, `to 100 %`). The card's context meter follows the same bands, so it can no
  longer disagree with the duck it describes. The red is deeper than the halo's, which is a
  different sentence: the halo lies on the water and says "blocked", the ring is worn on the
  neck and says "nearly out of room".
- The bottom-left corner no longer shows `DIRECTOR`. The auto camera is on by default in
  kiosk mode, so it was a permanent box in the corner naming an internal setting rather than
  warning about anything. `PAUSED` and `REDACTION OFF` stay, because those two do mean the
  pond is not telling you the whole truth.
- **The mosaic's hours are squeezed to 72 % of their width** and the slate pulled in with
  them, so the panel keeps its left edge and gives back the middle of the frame. The
  columns were wider than an hour of spend needs to be read, and the panel ran from the
  left margin all the way to the key with nothing between them.
- **The banner plane flies at 1.8 units a second instead of 3.2**, which is a 29-second
  crossing rather than a 17-second one. The reading time was never the crossing: the board
  across the top of the screen owns the middle of the sky band the banner flies through, so
  what you get is one clear window on the way in and one on the way out. Measured, they were
  2.2 seconds each, which is not long enough to read two version numbers; they are 4.0 now.
- The deck mosaic sits at the very front of the paving, so its foot lands on the same line as
  the on-screen key's and the two read as one band across the bottom of the frame.
- **The sky and the water are written only when their numbers move.** Both are set through
  shader node values, each of which walks a node tree to find the node it writes, and both
  were written on every frame -- the sun moves 0.2° a minute. The frame handler's own cost
  goes from 4.9 ms to 2.8 ms on a five-duck pool, which is a third of a 60 fps budget
  handed back. Nothing looks different: the guards are tighter than anything either can show.
- The banner plane's tow line is three times longer and its banner a quarter smaller. The
  board across the top of the screen covers the whole sky band in the middle of the frame,
  so a short rig vanished behind it whole; a long one keeps the banner clear while the
  plane is behind, and the other way round.
- The two usage plates and everything written on them are 30% smaller, and sit closer
  together.
- The Claude mark above them no longer turns. Its arms reach out and draw back in, in a
  wave running round the burst, which is what the mark does when it is thinking -- and a
  pulse survives being small, where a slow rotation just looks like a wobble. Each arm is
  its own object now, so its length is its scale. It is a deep clay that goes unlit by day,
  reading as a dark shape against a bright sky, and lights from within at night, reading as
  a glowing one against a dark sky: one colour, both skies, no plate behind it.
- The pool-wide totals no longer sit in the bottom-left corner. They are on the board at the
  top of the screen already, and a second copy under the hover card only ever got read as
  belonging to the duck the card was about. What is left there is `PAUSED`, `REDACTION OFF`
  and `DIRECTOR`, which are warnings and have to be visible somewhere.
- All seven README screenshots re-rendered. They were made before the android, the
  noodles and the horizon existed, and the overview was still captioned as showing a
  scoreboard on the far deck, which moved onto the screen two releases ago. The hover
  card shot now catches a duck with a question open, which is what its caption always
  claimed. All from `fixtures/demo.json` with sample usage figures, so no screenshot
  carries a real path, project name or usage reading.
- The bather sits propped on both hands, planted on the deck out beside her hips, and
  leans back a few degrees onto them all the time. Her arms used to fold in behind her
  back -- the left hand at y +0.255, the right swinging round to almost her centreline --
  so from the front she had no arms at all. Both arms are now the same arm: the right one
  is still a separate object so it can wave, but its joints are the left one's carried
  into its own frame, so the two match at rest. The raise sweeps the hand forward through
  straight-out rather than backward, and eases slower to hold the same per-frame budget
  over a longer swing.
- The on-screen key is a row shorter: `H hides this key` moved off a line of its own into
  the empty bottom-left corner, level with the last hat.
- **The board moved to the screen.** All of it -- status row, range tabs, both spend lines,
  the sparkline and the footer -- is drawn across the top in screen space, last of everything.
  As geometry on the far deck a duck's name tag would park on top of it, and the far half was
  read at an angle. What it says is now a plain value (`cards.board_model`) with the drawing
  separate, so it can be tested without reading text off mesh objects.
- **The camera no longer roams.** It frames the duck you pinned and rests on the overview
  otherwise; it never picks a subject of its own.
- **Lane signs** are scaled by their distance to the camera, so every lane's sign is the same
  size on screen, and the text is much larger. The far lane's sign used to render a third
  smaller, which was the difference between reading its detail line and not.
- The on-screen key is a horizontal strip along the bottom-right, hats are drawn as their own
  silhouettes rather than colour swatches, the state rows lost their explainers, and VS Code is
  violet -- it had sat one step from Claude Code's terracotta and read as the same swatch.
- The tally under the hover card is labelled `WHOLE POOL`, under a divider, and no longer
  double-counts a blocked duck as waiting.
- Name tags are smaller and see-through, so a tag sits over the water rather than replacing it.
- `DuckPond.exe` runs Blender unbuffered and `dev/launch.py` line-buffers its output, so
  `%LOCALAPPDATA%\DuckPond\last-run.log` can be read while the run is still going.

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

### Fixed
- **Every duck that left the pool left its name behind.** Deleting an object does not delete
  its mesh or its text curve; those stay in the file as orphans, and nothing was purging
  them after startup. Each duck carries three text curves (its name, that name's outline,
  the branch flag), each lane sign two and each packet one. Measured on the demo fixture
  with ducks coming and going: 96 curve datablocks in six minutes, all of them orphans.
  `pool.remove_object` now takes an object's data with it when nothing else points at it,
  and the same six minutes leave 12 -- the ones the living ducks are using.
- **The mosaic drew one range's tiles at another range's width.** The tile mesh was cached
  under one name, so whichever range was built first set the width for every range after
  it: the minute view drew 24-column tiles in 60 columns, each more than twice its own
  step, and an hour of spend ran into its neighbours as one smear. The width is part of the
  cache key now, and the gap between tiles gives way when the columns get too close for it.
- **A session you came back to lost its hat, and with it its context colour.** Leave a
  session alone long enough and housekeeping ends it and drops it; the next line it writes
  rebuilds it from `SessionSeen`, which carried no model. `ModelChanged` only fires on a
  change, and the adapter's parser had not forgotten the model, so it never said it again:
  the duck wore the unknown-model hat for the rest of its life and was measured against the
  200K default window, which pinned a 1M session 70 % full at `full`. `SessionSeen` now
  carries what the parser already knows (model and last context reading), every `Usage`
  event adopts its model when the agent has none, and a sub-agent that reports its own model
  after inheriting its parent's gets its window recomputed with it.
- Procedural meshes took their neighbour's material at every primitive boundary. The
  builder tagged each new primitive as `faces[n:]` after building it, and bmesh gives no
  promise that a new face lands at the end of the array: on a cone followed by a sphere,
  19 faces of 254 came out wrong. It now tracks which faces existed before, by identity.
  Every `DP_*` object was affected; it showed up as a forearm rendering in the colour of
  the hand beside it, and shins in the colour of their ankle joints.
- **Context was pinned at 100 % on nearly every duck.** Opus was mapped to a 200K window; it
  has had 1M since 4.6, so a session a quarter full read as about to overflow. Across the
  transcripts on this machine that was 8,339 replies of 18,972 clamped to full. Matching is
  version-aware now, because a family name alone cannot tell Opus 4.5 (200K) from Opus 4.6
  (1M), and a date stamp is not a version.

### Removed
- Coin stacks beside the lane signs. The month's spend is already on the sign in figures, and
  the stacks were what the signs had to stay clear of.

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
