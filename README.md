# Duck Pond

See every AI agent working on this PC, live, at a glance, without reading logs.

A swimming pool in Blender. Every rubber duck is a Claude Code session; ducklings on tethers
are its sub-agents. Lane = working directory, hat = model, body colour = harness. Every duck
wears a **traffic light**: a lamp on a pole and a halo on the water in its state colour.
Teal = working, yellow = waiting for you (breathing; goes quiet after 10 minutes), red
flashing = blocked on a permission, dim grey = idle. Your prompts fall from the sky as amber orbs;
finished reports rise as gold ones. Every tool call pops a coloured **chip** naming it in a
word (`bash`, `edit`, `read`, `web`, `test`, `spawn`). Context compaction is a geyser. Errors
bring rain. The sun follows your clock; after dark the lido lights come on and the ducks glow.
The far deck is a **scoreboard**; each lane sign carries branches, state dots and a coin stack
for spend. Spec: [`SPEC.md`](SPEC.md), §15 for what changed in v0.2.

![overview](out/showcase_overview.png)

## Run it

Requires Blender 5.x (found automatically; installed here at
`C:\Program Files\Blender Foundation\Blender 5.2`).

**As an executable.** Build once, then double-click `dist\DuckPond.exe` (7.8 MB, no console
window). It carries the add-on inside, unpacks it to `%LOCALAPPDATA%\DuckPond\app-<version>`
on first run, finds Blender, and starts the pool. Copy it anywhere; only Blender needs to be
installed. The log of the last run is `%LOCALAPPDATA%\DuckPond\last-run.log`.

```bat
python dev\build_exe.py            # -> dist\DuckPond.exe (PyInstaller, one file, duck icon)

dist\DuckPond.exe                  # the pool in a maximised window (movable, minimisable), live sessions
dist\DuckPond.exe --fullscreen     # borderless fullscreen instead (Alt+F11 toggles back)
dist\DuckPond.exe --kiosk --sound  # second monitor: auto camera, tags on every duck, cues
dist\DuckPond.exe --dev            # normal Blender UI + sidebar
dist\DuckPond.exe --stub           # demo fixture (--both = demo + live)
dist\DuckPond.exe --blender "D:\Blender\blender.exe"   # if Blender is somewhere unusual
```

For an always-on second monitor, put a shortcut to `DuckPond.exe --kiosk` in `shell:startup`.

**From the repo** (same thing, via the batch files):

```bat
DuckPond.cmd                    # APP MODE: pool only, maximised window, live Claude Code sessions
DuckPond.cmd --kiosk --sound    # second monitor: + auto camera director, tags on every duck, sound
dev\launch.cmd                  # dev: live sessions with the normal Blender UI + sidebar
dev\launch.cmd --stub           # demo fixture (4 sessions, 5 sub-agents, 75 s loop)
dev\launch.cmd --both
```

Blender is the app. The window is a normal one: minimise, move, maximise and snap it like
any other. Ctrl+Space restores the Blender panels, Alt+F11 toggles borderless fullscreen,
Alt+F4 quits. For an always-on second monitor, put a shortcut to `DuckPond.cmd --kiosk` in
`shell:startup`. The **Duck Pond** tab in the sidebar (`N`) has every toggle, including a
clock override to preview the night lido.

| Key (viewport) | Action |
|---|---|
| hover | card for the duck / duckling / tether under the mouse |
| click | pin the card (full details in the sidebar) |
| `K` | name + status tags on **every** duck (kiosk) |
| `C` | director: auto camera that frames blocked ducks, questions, spawns, reports |
| `F` | follow the pinned duck |
| `Home` | overview camera |
| `L` | cycle lane cameras |
| `S` | sound cues on/off |
| `R` | toggle text redaction (on by default) |
| `P` | pause data (scene keeps animating) |

## Reading the pool

| You see | It means |
|---|---|
| duck paddling, wake behind it | generating; a stronger wake = more tokens/sec |
| small bubbles rising from the head | thinking (the last streamed block was a thinking block) |
| head dipped, bubbles at the bill | running a tool; bubble colour = tool kind (dark = bash) |
| chip beside the duck: `bash` `edit` `read` `web` `test` `spawn` … | that tool call, just now |
| `tests pass` / `tests FAIL` chip + green/red ring | a test run finished |
| amber orb falling onto the duck, splash | you sent a prompt |
| gold orb rising, gold ring, little hop | the turn finished; the report is up |
| steady teal lamp and halo | working (generating or running a tool) |
| yellow lamp and halo, breathing | waiting for you (`asking you` chip = a question; the card quotes it) |
| yellow lamp and halo, dim and still | waiting for more than 10 minutes: quiet, not urgent |
| red lamp and halo, flashing; impatient rocking | blocked on a permission prompt (inferred from a tool unanswered > 12 s outside bypass mode) |
| dim grey halo | idle |
| `denied` chip, red ring, head-shake | you rejected its tool call |
| amber letters stacked on the tail | prompts you typed that are queued behind this turn |
| duck sitting low, life ring at 95 % | context window filling up |
| geyser + `compacted` chip, duck pops up | context compaction |
| nose down, sitting a little lower | idle |
| duckling on a thick lit tether | sub-agent working; thin dull = finished / idle |
| duckling far out on a thin leash | background sub-agent (outlives the parent's turn) |
| duckling orbiting another duckling | nested sub-agent (spawn depth 2) |
| choppy water | fleet-wide token throughput is high |
| rain | errors in the last two minutes |
| dark water, lido lamps, glowing ducks | it is after 20:30 on your clock |

Numbers live on the deck, on purpose. The scoreboard shows `N WORKING · N WAITING · N
BLOCKED · N IDLE`, spend, tok/min, lines added/removed, sub-agents, the clock, and a
30-minute bar chart of output tokens per minute. Each lane sign shows the folder, its
branches, session count, spend, one state-coloured dot per session and a coin per dollar.

Glance / hover / click: the duck and its beacon are the glance; the card (state-coloured
bar, context meter, the question or denial in colour, what it is doing now, what you said,
what it said, sub-agents, queue, permission mode, tool mix of the last 10 minutes) is the
hover; the sidebar (all of that plus spend per model, sub-agent list, packets, last tools)
is the click. Packet text rides a tether only for the hovered or pinned session.

## Data

The Claude Code adapter tails `~/.claude/projects` on a worker thread and never writes
there. Beyond sessions, sub-agents, tool calls, prompts, responses, usage and cost it now
reads: thinking blocks, `AskUserQuestion` (exact "asking you"), tool denials
(`toolDenialKind`), queued prompts (`queue-operation`), compaction boundaries, turn
durations, `cost-state` (lines added/removed, per-model usage), permission mode, effort,
`is_error` on tool results, and sub-agent `.meta.json` (`parentAgentId`, `spawnDepth`,
`run_in_background`). Session states other than questions and denials are inferred from
the transcript tail and marked so on the card.

## Contract and tests

Motion is continuous by contract: a heading never changes faster than 150°/s, walls and
ropes are avoided by steering (never by reflecting), a duck whose lane moved paddles back
instead of sliding, ducks in a lane steer apart, lanes keep their order and linger 3 min.
Personality (cruising speed, wander, bob, curiosity) lives inside that contract. The
director camera is a critically damped spring on position and look-at.

```bat
python tests\test_core.py                                  # reducer, redaction, adapter on real logs
python tests\test_signals.py                               # questions, denials, compaction, queue, cost, inference
blender -b --python tests\headless_motion.py               # the smoothness contract (no snaps, no sawing, no sliding)
blender -b --python tests\headless_smoke.py                # builds the demo, checks every visual, renders out\smoke_eevee.png
blender -b --python tests\headless_director.py             # camera + world continuity under a busy fleet
blender -b --python dev\render_showcase.py                 # out\showcase_*.png + out\showcase_clip.mp4
blender --python dev\gui_shot.py -- --kiosk --out out\gui_tags.png   # real GUI overlay screenshot
```

## Not built yet

- Replay mode on the timeline, Codex and VS Code adapters (stub-only ducks), GIF export.
- Exact states need a hook feed; today `awaiting_permission` is inferred from timing.
- Remote / cloud sessions do not write local logs and are not shown.

## Layout

```
duck_pond/
  model.py           fleet state + event reducer (signals, cues with timestamps)
  theme.py           harness colours, model → hat, state colours, tool categories, redaction
  adapters/          claude_code.py (tail follower), stub.py (fixture replay), base.py
  scene/             pool, duck (beacon, mail, glow), tether, ripples, fx (chips, orbs, geyser, rain),
                     deck (scoreboard, lane signs, coins), sky (clock sun, night, chop, rain)
  sim/motion.py      per-frame motion: contract, personality, separation, body language
  sim/director.py    auto camera (priorities + critically damped springs)
  sound.py           optional aud cues
  ui/                cards (glance/hover/click text), hover (gpu/blf card + tags), panel
  runtime.py         timer (data, 4 Hz) + frame handler (motion, fx, sky, director)
  addon.py           Blender registration, preferences, operators, toggles
fixtures/demo.json   scripted demo: fan-out, nested + background agents, question, denial, compaction
dev/                 launch.py|cmd, render_showcase.py, gui_shot.py
tests/               core, signals, headless motion / smoke / director
```
