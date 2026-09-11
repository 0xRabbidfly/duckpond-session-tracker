# Architecture

How a line appended to a transcript becomes a duck dipping its head. Read `SPEC.md` for
*what* the pool shows and why; this page is about how the code is shaped so you can change it.

## The pipeline

```
~/.claude/projects/**/*.jsonl ─┐
fixtures/demo.json ────────────┤  adapters (worker thread, read-only)
                               ▼
                       event dicts  {"type": "ToolCall", "session_id": ..., "at": ...}
                               ▼
                       Fleet.apply()  (model.py, pure Python)
                               │  updates Session / SubAgent state
                               │  appends Cue(kind, ids, payload, at)
                               ▼
                       Runtime.tick()  4 Hz Blender timer (runtime.py)
                               │  spawns / removes ducks, applies cues to fx + sound + director
                               ▼
                       frame handler  every redraw (runtime.py)
                               │  Motion.step → duck poses      (sim/motion.py)
                               │  FX.update   → chips, orbs, rain (scene/fx.py)
                               │  Sky.update  → sun, night, chop  (scene/sky.py)
                               │  Director    → camera springs    (sim/director.py)
                               ▼
                       gpu/blf draw handler → cards, tags, leader lines (ui/hover.py)
```

Two clocks matter. **Event time** (`at`) is when something happened in the transcript;
**wall time** is `time.time()` in Blender. Cues carry event time so a startup replay of an
old transcript does not fire a hundred splashes: a cue older than ten seconds updates state
but skips its effect.

## Layers and their rules

| Layer | Files | Imports bpy? | Rule |
|---|---|---|---|
| Adapters | `adapters/base.py`, `claude_code.py`, `stub.py` | no | Read files, emit event dicts. Never write to the source. |
| Model | `model.py`, `theme.py` | no | Pure reducer. Everything a test can assert on lives here. |
| Runtime | `runtime.py`, `addon.py` | yes | Owns the timer, the frame handler, the worker thread. The only place cues become side effects. |
| Scene | `scene/*.py` | yes | Builds and mutates objects. Every object is named `DP_*`. No policy, only geometry and colour. |
| Sim | `sim/motion.py`, `sim/director.py` | yes (Vector only) | Per-frame continuous motion. Everything must respect the smoothness contract. |
| UI | `ui/cards.py`, `ui/hover.py`, `ui/panel.py` | yes | `cards.py` is pure text assembly (testable); `hover.py` draws it. |
| Sound | `sound.py` | yes (`aud`) | Optional. Synthesized cues, no asset files. |

The pure layers are why `python tests/test_core.py` works without Blender. Keep new logic
in `model.py` when you can and let the scene read the result.

## Events

Adapters yield plain dicts. `Fleet.apply` dispatches on `type` to `_on_<Type>`; unknown
types are ignored so an adapter can be ahead of the model. Current types:

| Type | Carries | Effect |
|---|---|---|
| `SessionSeen` | session_id, harness, cwd, branch, model, title | create or refresh a Session |
| `SessionTitle` | title, source (prompt / ai / custom) | title precedence: custom > ai > first prompt |
| `ModelChanged` | model | hat |
| `StateChanged` | generating / tool_running / awaiting_user / idle / ended | body language, beacon; `done` + `report_up` cues when a turn finishes |
| `Prompt`, `Text` | redacted excerpts | last prompt / reply on the card; `prompt_drop` cue; turn counter |
| `Thinking` | on/off | head bubbles |
| `ToolCall` | tool name, summary, phase (start / done / denied), ok | chips, head dip, `tool_history`, denial handling, permission inference input |
| `Question` | the `AskUserQuestion` text | exact `awaiting_user` with the question quoted |
| `Queue` | +1 / -1 | letters on the tail |
| `Usage`, `CostState` | tokens, context %, USD, lines, per-model usage | waterline, coins, scoreboard, throughput history |
| `Compaction` | pre / post tokens | geyser, duck pops back up |
| `TurnDone` | duration | scoreboard |
| `PermissionMode`, `Effort` | strings | card; bypass mode disables permission inference |
| `Error` | message | red ring, rain contribution |
| `SubAgentSeen` | agent_id, type, description, model, parent_agent_id, spawn_depth, background | duckling + tether |
| `Packet` | direction (down / up), kind, text | packet on the tether |
| `SubAgentDone` | ok | tether goes thin, report packet |
| `SessionEnded` | | fade and remove |

`Fleet.housekeeping()` runs every tick and derives what the transcript does not say: idle
after silence, ended after longer silence, removal after the fade, and `awaiting_permission`
(a tool unanswered for more than 12 s, session not in bypass mode, mode known, tool category
not one that legitimately runs long: bash, test, agent, browser, mcp, web).

## Cues

A `Cue` is a one-shot event for the presentation layers: `spawn`, `despawn`, `tool_chip`,
`tool_done`, `denied`, `question`, `queued`, `prompt_drop`, `report_up`, `done`, `thought`,
`compaction`, `error`. `Runtime.tick` drains `fleet.cues` and fans each one out to `fx`,
`sound` and `director`. Adding a signal usually means: parser case → event → reducer → cue →
one effect in `fx.py` and one line in the README table.

## The motion contract

`sim/motion.py` keeps one `MotionState` per duck and duckling and advances it with
`Motion.step(dt)`. Everything that moves a duck is a term added to a yaw rate or a speed:

- lane centring and rope / wall avoidance (steering, never reflecting),
- separation from lane-mates,
- personality wander and curiosity,
- state body language (paddle, float, dip, hop, rock, head-shake),
- duckling orbit around the parent (or the parent duckling when nested).

The sum is clamped to `MAX_YAW` (150°/s) and the position integrates `speed * dt` exactly, so
`tests/headless_motion.py` can assert no snap, no saw, no jump, no slide for every frame.
The director camera in `sim/director.py` follows the same idea: a critically damped spring
on position and look-at, with a priority queue of things worth looking at.

## Blender specifics worth knowing

- Objects are found by name (`DP_Duck_<id>`, `DP_Duckling_<id>`, `DP_Board`, ...) so the
  pool survives a saved `.blend` and can be cleared with one prefix match.
- Colour is per-object (`obj.color`) and read by shared materials through an Object Info
  node, so thousands of state changes never touch material data.
- Text is FONT curves with a copy-rotation constraint to the camera (billboarding); the
  overlay text is `blf` in a draw handler. World labels hide when a kiosk tag covers them.
- The worker thread only reads files and parses JSON. Everything that touches `bpy` runs in
  the timer or the frame handler on the main thread.
- This Blender build has no FFMPEG output; `dev/render_showcase.py` writes a PNG sequence
  and encodes it with `ffmpeg` from PATH.

## Tests, and what each protects

| Test | Needs Blender | Protects |
|---|---|---|
| `tests/test_core.py` | no | reducer, redaction, title precedence, background sub-agent lifecycle, the real adapter on your own logs |
| `tests/test_signals.py` | no | every v0.2 signal: questions, denials, compaction, queue, cost, permission inference, throughput history |
| `tests/headless_motion.py` | yes | the smoothness contract |
| `tests/headless_smoke.py` | yes | the demo builds every object and colour it should; renders a still |
| `tests/headless_director.py` | yes | camera acceleration and turn bounds; sky continuity at startup |
