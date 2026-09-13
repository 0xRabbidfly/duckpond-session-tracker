# Duck Pond — a live 3D view of your agent fleet

**Status:** v0.2 (reimagined, built) · 2026-09-10 · owner: Nuno Borges · §15 records what changed from v0.1 and why
**Runtime:** Blender 5.2 LTS add-on (Python), live mode + replay mode

## 1. One-liner

A swimming pool rendered in Blender. Every rubber duck on the water is a running agent
session. Sub-agents are ducklings tethered to their parent; the tether hums and carries
visible message packets. Duck colour = harness, hat = model. Hover a duck and a card
tells you who it is and what it is doing. Idle ducks float. Thinking ducks paddle.

## 2. Metaphor map

| Real thing | In the pool |
|---|---|
| Agent session (one CLI / IDE chat) | Duck |
| Sub-agent spawned by a session | Duckling, ~45 % of parent size, tethered |
| Harness (Claude Code, Codex, VS Code Copilot…) | Duck body colour |
| Model the session runs on | Hat |
| Prompt sent parent → sub-agent | Warm packet travelling down the tether |
| Response sub-agent → parent | Cool packet travelling up the tether |
| Tokens/sec across the link | Tether vibration amplitude + frequency |
| Session is generating (thinking / streaming) | Duck paddles: moves, turns, leaves a wake; tether sways |
| Session waiting for the user | Duck floats still, head turns to the camera, "?" bubble |
| Tool call in flight | Duck dips its head under water; surfaces when the result lands |
| Context window filling up | Duck sits lower in the water (waterline rises up the body) |
| Session ended | Duck drifts to the pool edge, fades over 2 min, is removed |
| API error / retry | Duck wobbles hard once, red ripple ring |
| Working directory / repo | Pool lane (lane ropes with floats). Ducks in the same lane share a checkout |
| Git branch | Small flag on the duck's tail; text = branch name |

## 3. Scope

**MVP (v0.1)**
- Pool, lanes, animated water surface, ducks, hats, ducklings, tethers, packets.
- Claude Code adapter (live, from local session logs). Other harnesses via a static JSON stub.
- Hover card + sidebar panel. Live mode with a 4 Hz poll.

**v0.2**
- Replay mode: load any past session onto Blender's timeline and scrub it.
- Codex and VS Code Copilot adapters.
- Camera presets, "follow this duck", screenshot/GIF export of a time range.

**Out of scope**
- Controlling sessions from the pool (send prompts, kill). Read-only, always.
- Multi-machine fleets. One machine, one pool. (A pool-per-machine merge is a later idea.)

## 4. The scene

### 4.1 Pool
- Rectangular, 25 m × 12 m, 1.5 m deep, tiled walls (procedural tile shader), one ladder,
  two starting blocks purely for charm. Poolside deck 2 m wide.
- **Lanes** run along the long axis. One lane per distinct working directory that has at
  least one live duck. Lane width adapts: `12 m / lane_count`, min 1.5 m. A floating
  lane-rope with alternating red/white floats separates lanes. A small deck sign at the
  end of each lane shows the folder's last path segment (`AI-HUB-Portal`).
- Ducks with no working directory (unknown harness) swim in a shared "open water" lane
  at the far end.

### 4.2 Water (must be visibly alive at all times)
- Surface is a subdivided plane (256 × 128) driven by a procedural shader: two layered
  noise normal maps scrolling in different directions for ambient ripple, plus a shallow
  displacement so the silhouette of ducks visibly bobs.
- **Interaction ripples:** every duck emits concentric ripple rings through a Dynamic
  Paint "waves" canvas on the surface, with ducks as brushes. A paddling duck leaves a
  V-shaped wake; a still duck emits a faint ring every ~3 s so the water never looks
  frozen. Head-dip (tool call) emits one larger ring. Error emits a red-tinted ring (the
  shader reads a per-duck colour attribute written by the add-on).
- Caustics on the pool floor: light texture with a scrolling noise, cheap.
- Renderer: EEVEE Next for the live viewport (target 60 fps on an integrated GPU with
  ≤ 50 ducks). Cycles is allowed only for stills/recordings.

### 4.3 Lighting & camera
- One sun (late afternoon, ~35° elevation, warm) + sky world for reflections.
- Default camera: elevated three-quarter view covering the whole pool. Hotkeys jump to:
  overview, lane-by-lane, follow-duck (orbits the pinned duck).

## 5. Ducks

### 5.1 Geometry
- One base duck mesh (~2 k tris), classic rubber-duck silhouette, 0.6 m long for a
  session, 0.27 m for a duckling. Shared mesh data; each instance is its own object with
  custom properties (`dp_session_id`, `dp_harness`, `dp_model`, …) so the picker can read
  them back.
- Bill and eyes are always orange/black regardless of body colour, for recognisability.

### 5.2 Body colour = harness

| Harness | Colour | Hex | Why |
|---|---|---|---|
| Claude Code CLI | Claude clay/brown | `#D97757` | Anthropic brand terracotta |
| Codex CLI | White with black bill | `#F5F5F5` | OpenAI's black-and-white identity |
| VS Code (Copilot Chat / agent mode) | VS Code blue | `#007ACC` | VS Code brand |
| Gemini CLI | Google blue-violet | `#4E7CFF` | placeholder |
| Unknown / stub | Concrete grey | `#9E9E9E` | fallback |

The map is a JSON table in the add-on prefs, editable without code changes.

### 5.3 Hat = model

Hats are separate meshes parented to an empty at the duck's head, so hats can be swapped
when a session switches model mid-flight (Claude Code allows this).

| Model family | Hat | Notes |
|---|---|---|
| Fable | Wizard hat, deep purple with stars | storyteller |
| Opus | Black top hat | grand opera |
| Sonnet | Red beret | poet |
| Haiku | Straw kasa | Japanese conical hat |
| Astra | Silver crown with one star on top | as requested; config-driven, see open questions |
| GPT-5 / o-series (Codex) | Green baseball cap | OpenAI green `#10A37F` |
| Gemini | Blue propeller cap | |
| Unknown model | Folded newspaper boat hat | says "we have no idea" politely |

Model id → family is matched by substring (`claude-fable-5-1` → Fable, `claude-opus-*` →
Opus). Unmatched ids get the newspaper hat and are logged once so the table can grow.

### 5.4 Motion & state (the "is it thinking?" signal)

The duck's behaviour is a small state machine driven by the adapter.

| State | Motion | Extras |
|---|---|---|
| `generating` | Paddles: forward speed 0.3–0.6 m/s, gentle heading noise, stays inside its lane. Body bobs ±2 cm at 1.2 Hz with a slight roll. Wake ripples on. | Tether sways with the motion |
| `tool_running` | Slows to a stop, head dips 15° under the surface, bubbles rise. | One large ripple ring on dip and on surface |
| `awaiting_user` | Drifts to a stop, bob amplitude halves, head yaws toward camera every ~8 s. | "?" speech-bubble sprite above the hat, slow blink |
| `awaiting_permission` | As above but the bubble shows a lock glyph | Distinct from awaiting_user so you spot blocked sessions |
| `idle` (no event for > 90 s and not awaiting) | Floats, ambient ripple only. | Tail flag droops |
| `ended` | Slow drift to nearest wall, alpha fades over 120 s, then object removed. | |
| `error` | One hard wobble (roll 25°, 0.5 s), red ripple ring. Returns to previous state. | |

**Context fill:** the duck's Z offset is `-0.12 m × (context_used / context_window)`,
so a session at 90 % context is visibly sitting low in the water. A duck at ≥ 95 % gets a
tiny life-ring around its neck. (This is deliberately a bit alarming.)

**Paddling only when generating** is the key rule from the brief: motion means thought.
A still duck is either waiting on you or idle. You should be able to glance at the pool
and count how many sessions are actually working.

## 6. Ducklings and tethers

### 6.1 Ducklings
- Spawned when the adapter sees a new sub-agent for a session. Appear by surfacing from
  under the parent (0.6 s pop-up with a splash ring), then swim to an orbit slot 0.8–1.2 m
  from the parent. Up to 8 orbit slots evenly spaced; the 9th onwards stacks at 1.6 m.
- Same colour as the parent (a Claude Code sub-agent is still Claude Code), own hat if
  the sub-agent's model differs from the parent's (e.g. a Haiku Explore agent under a
  Fable session).
- Same state machine as §5.4. Ducklings paddle in a small circle around their slot while
  generating; they do not leave the parent's lane. When the parent paddles, the whole
  formation moves with it and the tethers trail and sway behind.
- On completion: the duckling swims back into the parent and submerges (0.8 s) while the
  tether retracts. On sub-agent error: red ring, then the same exit.

### 6.2 Tether
- A Bezier curve object from the parent's tail to the duckling's chest, bevelled to a
  1.5 cm rope, sagging under gravity (mid-point Z = −0.15 m), floating on the surface
  where it dips below.
- **Vibration:** a Displace modifier on the curve driven by a noise texture whose
  `strength` and `scale` are set every tick from the link throughput:
  `amplitude = clamp(tokens_per_sec / 200, 0.005, 0.06)` m,
  `frequency = clamp(1 + events_per_sec × 3, 1, 12)` Hz.
  Silent link → rope hangs still. Busy link → rope buzzes visibly.
- Rope colour: parent's body colour at 60 % value, with an emissive pulse each time a
  packet is emitted.

### 6.3 Packets (visible prompts and responses)
- Each message between parent and sub-agent becomes a **packet**: a 6 cm glowing sphere
  travelling along the tether via a `Follow Path` constraint, 1.5 s traverse time.
  - Parent → duckling (prompt, tool result forwarded): warm amber `#FFB347`.
  - Duckling → parent (response, final report): cool cyan `#5EEAD4`.
  - Sub-agent's own tool calls (which never cross the tether) are shown as bubbles rising
    from the duckling, not as packets.
- A text label (Blender text object, billboarded to camera, scaled so it is legible at
  the overview zoom) rides 8 cm above the packet: first 80 characters of the message,
  ellipsised. Labels are hidden when > 6 packets are in flight on one tether so the
  scene does not become a wall of text; the hover card still lists them.
- Packets that arrive fade into the receiving duck with a small emissive flash on the
  duck's chest.

## 7. Interaction

### 7.1 Hover card (primary)
- A modal operator installs a `SpaceView3D` draw handler and listens to `MOUSEMOVE`.
  Each move ray-casts from the mouse into the scene (`view3d_utils` + `scene.ray_cast`)
  against duck and duckling objects only (a collection filter). Hit → card drawn with
  `gpu` + `blf` in the top-right of the viewport, anchored to the duck with a thin leader
  line. Debounced to 60 ms.
- Card contents, in this order:

  ```
  ● Claude Code · Fable 5.1                    generating · 4 m 12 s
  session 9d8e617a · AI-HUB-Portal · master
  turns 23   tokens 148k in / 21k out   context 64 %   cost $4.12
  tool: Bash — "winget install --id BlenderFoundation.Blender…"
  last prompt: "create a spec for a 3d modeling view of a swimming pool…"
  sub-agents: 2 running · 3 done
  ```
- Hovering a duckling shows the same card for the sub-agent plus its parent's id and its
  agent type / description (e.g. `Explore · "find where sessions are logged"`).
- Hovering a tether shows the last 5 packets with direction arrows and timestamps.

### 7.2 Click to pin, sidebar panel (secondary)
- Left-click a duck, duckling or tether pins its card and name tag to it: they track it as it
  swims, whatever the mouse hovers next, until a click lands anywhere else in the pool (water,
  deck, sky). Clicking another duck moves the pin. Clicks on the sidebar never unpin.
- An N-panel tab **Duck Pond** shows the pinned session in full: complete message
  list (latest 50, expandable), all sub-agents, per-model token/cost table, and buttons:
  *Follow with camera*, *Open transcript file*, *Copy session id*.
- Panel header: pool totals (ducks, ducklings, active, waiting, tokens/min).

### 7.3 Keyboard
- `Space` pause/resume live updates (scene keeps animating, data freezes).
- `F` follow pinned duck. `Home` overview camera. `L` cycle lanes.
- `T` cycle the scoreboard range (`min` `hour` `day` `week` `month`); clicking a tab on the board
  does the same (§16).
- `R` toggle redaction (see §11).

## 8. Data sources

All adapters emit the same normalised event stream (§8.4). The pool never reads harness
files directly.

### 8.1 Claude Code (verified against this machine, 2026-09-10)
- Root: `~/.claude/projects/<cwd-slug>/`. One `<session-id>.jsonl` per session plus a
  `<session-id>/subagents/agent-<agentId>.jsonl` (+ `.meta.json`) per sub-agent, and
  `<session-id>/tool-results/`.
- Session-level lines carry `cwd`, `gitBranch`, `version`, `timestamp`, `sessionId`.
  Assistant lines carry `message.model` (e.g. `claude-fable-5-1`), `requestId`, `effort`,
  and `message.usage` for token counts. `cost-state` lines give `totalCostUSD` and
  `modelUsage`. Sub-agent lines are flagged `isSidechain: true` with `agentId` and
  `attributionAgent` / `attributionSkill`.
- **Liveness:** a session is *live* if its JSONL was modified in the last 10 min **and**
  the last event is not a session-end marker. *Generating* = an `assistant` line with a
  `requestId` and no subsequent `user` line yet. *Tool running* = a `tool_use` block with
  no matching `tool_result` yet. *Awaiting user* = the last line is a completed assistant
  turn. *Awaiting permission* = a permission request line without a response.
  These are heuristics from the log; the add-on tags them `inferred` in the card. If a
  hook-based feed is configured (Claude Code hooks can POST session events), the adapter
  prefers it and marks states `exact`.
- Tail-follows files by byte offset; never re-reads whole transcripts in live mode.

### 8.2 Codex CLI (not installed here; adapter from the public layout)
- `~/.codex/sessions/**/*.jsonl` rollouts. Model from the session header, cwd from the
  first turn. No native sub-agent concept in current Codex; the duck simply has no
  ducklings unless a future version adds them.

### 8.3 VS Code Copilot Chat
- `%APPDATA%/Code/User/workspaceStorage/<hash>/chatSessions/*.json` plus `workspace.json`
  for the folder path. Agent-mode tool calls map to `tool_running`. Model id is in each
  request's metadata. Sub-agents: none today.

### 8.4 Normalised event model

```
SessionSeen   {session_id, harness, model, cwd, branch, started_at}
StateChanged  {session_id, agent_id?, state, at, confidence: exact|inferred}
ModelChanged  {session_id, agent_id?, model}
Usage         {session_id, agent_id?, tokens_in, tokens_out, context_used, context_window, cost_usd}
SubAgentSeen  {session_id, agent_id, model, description, at}
SubAgentDone  {session_id, agent_id, at, ok: bool}
Packet        {session_id, agent_id, direction: down|up, kind: prompt|response|tool_result, text, at}
ToolCall      {session_id, agent_id?, name, summary, at, done: bool}
Error         {session_id, agent_id?, message, at}
SessionEnded  {session_id, at}
```

Adapters run in a background thread and push into a queue; the Blender main thread
drains the queue on a timer (Blender's API is not thread-safe).

## 9. Architecture (Blender add-on)

```
duck_pond/
  __init__.py          register/unregister, prefs (colour + hat tables, poll rate, paths)
  model.py             Fleet, Session, SubAgent, Link dataclasses; event reducer
  adapters/
    base.py            Adapter protocol, tail-follower utility
    claude_code.py
    codex.py
    vscode_copilot.py
    stub.py            reads a JSON fixture; used for demos and tests
  scene/
    pool.py            builds pool, lanes, water, lights, camera presets
    duck.py            instances, colour, hat swap, waterline offset
    tether.py          curve, displace driver, packet spawner
    assets.blend       duck, duckling, 8 hats, ladder, lane float
  sim/
    motion.py          state machine → per-tick transform updates, lane containment
    ripples.py         dynamic paint brush toggling, ring emission
  ui/
    hover.py           modal operator, ray-cast, gpu/blf card
    panel.py           N-panel
    keymap.py
  runtime.py           bpy.app.timers tick at 4 Hz (data) and per-frame handler (motion)
  replay.py            maps a transcript's wall-clock to frames; drives the same reducer
```

- **Live mode:** `bpy.app.timers` drains adapter events at 4 Hz; a `frame_change_post`
  handler moves ducks every frame while the viewport plays. Playback runs continuously
  in live mode so the water and bobbing never stop.
- **Replay mode:** the reducer is fed events in timestamp order mapped to the timeline
  (1 real second = 24 frames by default, adjustable). Scrubbing rebuilds the fleet state
  from a keyframe snapshot cache every 500 frames so seeking is instant.
- Everything the add-on creates lives in a `DuckPond` collection; *Reset pool* deletes
  the collection and rebuilds from assets. Nothing else in the .blend is touched.

## 10. Performance budget

| Metric | Target |
|---|---|
| Ducks / ducklings on screen | 50 / 200 |
| Viewport fps (EEVEE Next, laptop iGPU) | ≥ 30, ≥ 60 with ≤ 20 ducks |
| Data tick cost | ≤ 8 ms per tick at 4 Hz |
| Memory | ≤ 1.5 GB total Blender RSS with 50 sessions and 1 000 packets/hour |
| Startup (assets load + pool build) | ≤ 3 s |

Packets are pooled (200 pre-made spheres recycled), text labels are pooled (50), tethers
share one material with per-object colour attributes.

## 11. Privacy & safety

- Prompt and response text can contain secrets. **Redaction is ON by default:** labels
  and cards show text after masking anything matching common secret patterns (bearer
  tokens, `sk-…`, connection strings, JWTs, 32+ hex runs) and truncating to 80 chars.
  `R` toggles it; the state is shown in the panel header in red when off.
- Read-only. The add-on never writes to any harness directory, never opens sockets
  except a local hook receiver bound to `127.0.0.1` when enabled.
- Recording export strips the hover card unless the user ticks "include cards".

## 12. Acceptance criteria (MVP)

1. Start Blender with two Claude Code sessions running on this machine; within 5 s two
   clay-coloured ducks with wizard hats appear in the `AI-HUB-Portal` lane, tail flags
   read the branch.
2. Ask one session to spawn an Explore sub-agent: a duckling surfaces beside it within
   one poll interval, a tether appears, an amber packet travels down it with the prompt
   excerpt, then cyan packets return. The tether visibly vibrates while the sub-agent
   streams and hangs still when it finishes. The duckling then merges back.
3. The generating duck paddles and leaves a wake; the duck waiting for input floats
   still with a "?" bubble. The water surface shows continuous ambient ripples around
   both.
4. Hovering the paddling duck shows the card with harness, model, session id, cwd,
   branch, state, elapsed, tokens, context %, current tool, last prompt excerpt.
5. Running a tool from a session dips the duck's head and emits a ripple ring.
6. Ending a session drifts its duck to the wall and removes it within 2 min.
7. Stub adapter can show one Codex (white) and one VS Code (blue) duck with distinct hats.
8. 20 ducks + 40 ducklings hold ≥ 30 fps in the viewport on the development laptop.

## 13. Milestones

| # | Deliverable | Est. |
|---|---|---|
| M1 | Pool + water + lanes + static ducks from a JSON stub, hat/colour tables | 2 d |
| M2 | Claude Code adapter (live tail), state machine, paddling/idle motion, ripples | 3 d |
| M3 | Ducklings, tethers, vibration driver, packets with labels | 3 d |
| M4 | Hover card, pin, N-panel, keymap, redaction | 2 d |
| M5 | Replay mode on the timeline, snapshot cache | 2 d |
| M6 | Codex + VS Code adapters, camera presets, GIF export | 2 d |

## 14. Open questions

1. **Model → hat for "Astra".** Not a model id I can resolve today; it is in the table
   because you asked for it. Confirm which id substring should map to it.
2. **Exact vs inferred state.** Log-tailing infers "generating" from the last line. A
   Claude Code hook (`Stop`, `PreToolUse`, `PostToolUse`, `Notification`) posting to a
   local receiver gives exact states. Worth doing in M2 if hooks are already configured.
3. **Lane = cwd or lane = repo?** Two sessions on the same checkout share a lane either
   way; worktrees of one repo would be separate lanes under "cwd". Recommend cwd for MVP.
4. **Remote / cloud sessions** (Claude Code web, remote control) do not write local
   logs. Out of scope unless a session-list API is available.
5. **Sound.** A quiet paddling loop and a soft "bloop" per packet would be delightful and
   also annoying. Off by default if built at all.


## 15. v0.2 — the reimagining (built 2026-09-10)

The one thing that had to survive: *see every agent on this PC working, live, at a glance,
and understand what each is doing without reading logs.* Everything below is visible in
Blender and covered by a test. The pool stayed; almost everything on it changed.

### 15.1 What the logs really say (and v0.1 ignored)
Verified on this machine's `~/.claude/projects`: `thinking` blocks (5 k), `AskUserQuestion`
tool calls (exact "asking you"), `toolDenialKind` (`user-rejected` / `permission-rule`),
`queue-operation` (prompts typed while the agent worked), `system/compact_boundary` (context
compaction with pre/post tokens), `system/turn_duration`, `cost-state` (lines added/removed,
tool time, per-model usage incl. thinking tokens), `permission-mode`, `effort`, `is_error`
on tool results, sub-agent `.meta.json` with `parentAgentId` / `spawnDepth` (nested agents),
and `run_in_background` launches. The adapter now emits all of them
(`Thinking`, `Question` via `ToolCall`, `PermissionMode`, `Queue`, `CostState`, `Compaction`,
`TurnDone`, `Effort`; `ToolCall.done` carries `ok` and `denied`; `SubAgentSeen` carries
`background`, `parent_agent_id`, `spawn_depth`).

### 15.2 The axis of the world
You are the sky; tools are under the water; peers are on the surface.
- **Prompt** → an amber orb falls from the sky onto the duck and splashes.
- **Report** (end of turn) → a gold orb rises out of the duck to the sky, gold ring, small hop.
- **Tool** → head dips (kept) and a **chip** pops beside the duck naming the tool in a word
  and a colour: `bash` (pale, dark bubbles), `edit` (green), `read` (blue), `web` (violet),
  `test` (orange; then `tests pass` in green or `tests FAIL` in red with a ring), `spawn`
  (gold), `ask`, `browser`, `mcp`. Categories: `theme.tool_category`.
- **Question** → beacon (below) + `asking you` chip; the card shows the question verbatim.
- **Denial** → red ring, `denied` / `blocked by rule` chip, a head-shake; the duck then waits.
- **Compaction** → a geyser of bubbles, a `compacted` chip, and the duck pops back up.
- **Queued prompt** → an amber letter stacks on the duck's tail (`+1 queued` chip).
- **Thinking** → small bubbles drift up from the head while the last block was a thinking block.

### 15.3 State, legible from across the room
- **Traffic light**: every duck carries a lamp on a pole and a halo ring on the water, both
  in the state colour. Steady teal = working. Yellow, breathing = waiting for you; after ten
  minutes it goes quiet (dim, still) so only fresh waits ask for attention; a pending
  question keeps pulsing. Red, flashing, with red rings spreading = blocked on a permission
  (inferred: a non-Bash tool unanswered > 12 s in a session that is not in bypass mode).
  Dim grey = idle. The v0.1 "?" / "!" glyphs are gone: a glyph looked the same whatever the
  duck was doing, and the question was "is it working or waiting?"
- Body language: generating paddles (kept); tool dips head; idle droops nose-down and sits
  lower; blocked rocks impatiently; error wobbles (kept); finished hops; compaction pops.
- **Personality** per duck (stable hash of the id): cruising speed 0.8–1.0 of the max,
  wander gain, bob rate, curiosity toward the camera. All inside the smoothness contract.
- **Separation**: ducks in a lane steer apart (yaw-rate term + slow drift), so names never pile.

### 15.4 World and deck
- **Clock**: the sun follows the PC clock; after 20:30 the lido lights come on, the water
  darkens, and the ducks glow (an emission attribute), so night shifts stay readable.
- **Weather**: water chop follows fleet output tokens/sec; rain falls when errors pile up.
- **Scoreboard** on the far deck: `N WORKING · N WAITING · N BLOCKED · N IDLE`, range tabs,
  spend for the picked range and for the month so far, and ≈$ bars as real geometry (§16
  replaced v0.2's live-session spend and 30-minute token sparkline).
- **Lane signs**: folder (kept), plus branch line, session count, the folder's ≈$ this month
  (§16), one state-coloured dot per session, and a **coin stack** (one coin per dollar) on the deck.

### 15.5 Sub-agents
- Nested agents (spawnDepth 2) orbit their parent *duckling*, not the session duck.
- Background agents drift on a longer, thinner, dimmer leash and keep working after the
  parent's turn ends. Active links are thick and lit; finished ones thin and dull.
- Packet text is hover-level: labels ride a tether only for the hovered or pinned session.

### 15.6 Overlay: glance / hover / click
- Glance: the duck, its beacon, its chips, and (kiosk `K`) a screen-space **tag** on every
  duck — big name, one-word status (`writing`, `thinking`, `bash`, `your turn`, `asking
  you`, `needs permission`) with a state-coloured underline; stacked tags are pushed up and
  get a leader line.
- Hover: the card — state-coloured bar, context meter, the question/denial in colour, what
  it is doing now, what you said, what it said, sub-agents, queue, permission mode, tool mix.
- Click: the sidebar — everything above plus spend per model, sub-agent list, packets, last tools.

### 15.7 Cameras and sound
- `C` **director**: an auto camera for a second monitor. Priorities: blocked > question >
  spawn > compaction > error > done > prompt, then the hardest-working duck, with an
  overview beat every 40 s. Critically damped springs on position and look-at;
  `tests/headless_director.py` bounds the camera's second difference and turn rate.
- `--kiosk` launcher flag = fullscreen + director + tags on all. `--sound` / `S`: synthesised
  cues via `aud` (prompt bloop, report chime, question ding, error buzz, geyser, tests).

### 15.8 Contract and tests
`tests/headless_motion.py` unchanged and green. New: `tests/test_signals.py` (reducers,
adapter parsing, inference), `tests/headless_director.py` (camera + world continuity),
extended `tests/headless_smoke.py` (beacons, chips, board, coins, nested/background
ducklings, compaction pop, inferred block, denial). `dev/render_showcase.py` renders
`out/showcase_*.png` and `out/showcase_clip.mp4`; `dev/gui_shot.py` screenshots the real
GUI overlay.

### 15.9 Considered and not kept
- A harbour (ships, tugs, cranes) instead of a pool: stronger for tools-as-cranes, weaker
  for the one thing that matters most, which is counting who is paddling. Kept the pool.
- Cost as duck size: funny, but it hides the model hat and makes lanes unreadable. Coins.
- Text on every packet: a wall of text at three ducklings. Hover-level now.

## 16. Usage ledger and range picker (built 2026-09-13)

Design: `docs/superpowers/specs/2026-09-13-usage-ledger-design.md`.

### 16.1 Why
v0.2's `$ spent` summed the sessions still in the pool, so spend fell when ducks left and a
restart forgot it. The logs make a better answer possible and a naive one wrong:
- `cost-state` lines are rare and carry no timestamp, so they cannot be bucketed by time.
- Every assistant line carries `message.usage` with a timestamp, including the cache write
  split (`ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens`) and `speed`.
- One API reply is often written as several lines repeating its usage; `message.id` +
  `requestId` identify it. Counting lines inflated tokens (9,091 repeats in a month here).

### 16.2 The ledger
- `duck_pond/pricing.py`: API list $/MTok per model family (longest id prefix wins); cache
  writes 1.25× input (5 min) and 2× (1 h); cache reads per model (Fable 5.1 $0.25); fast mode
  doubles input and output. Unknown models count in tokens and show as `+?`, never guessed.
- `duck_pond/ledger.py`: rows priced into UTC minute buckets (≈$, unpriced tokens, output
  tokens, session ids), per-session and per-folder ≈$. Ranges are cut on local calendar
  boundaries at query time. A repeated reply key is ignored.
- Fed twice: the adapter's `backfill()` reads every transcript on disk once at startup on the
  worker thread (a month, ~480 MB, in about a second; `UsageBatch` events, no ducks), then live
  `Usage` events. `BackfillDone` flips the board from `scanning logs…` to figures. The fleet
  de-duplicates live usage with its own key set, so session token counts stay right. Events that
  report a running `cost_usd` (the demo fixture, other tools) contribute its increase instead of
  a price lookup.
- Nothing is stored: Claude Code's ~30-day log cleanup bounds week and month history.

### 16.3 The board

| tab | bars | "this range" line |
|---|---|---|
| `min` | 60 × minute | last 60 min |
| `hour` (default) | 24 × hour | last 24 h |
| `day` | 30 × local day | last 30 days |
| `week` | 8 × Mon–Sun | last 8 weeks |
| `month` | 6 × calendar month | last 6 months |

Rows: states; tabs (click a plate, or `T`, or the sidebar); `last 24 h  ≈$ · out tok ·
sessions`; `September  ≈$ · out tok · sessions` (always month to date); footer with the bar
peak, the clock and, on week/month, `logs keep ~30 days`; ≈$ bars, the current bucket gold.
Lane signs show the folder's month-to-date ≈$; the hover card shows the session's ≈$
(sub-agents included) beside any recorded `cost-state` total; the card footer shows ≈$ today.

### 16.4 Readability pass (2026-09-13)
- **Headless runs**: `entrypoint: sdk-cli` marks a `claude -p` / Agent SDK session
  (`Session.headless`). Its `end_turn` sends the report up and ends the session at once (fade,
  then removal), so a scheduled pipeline never piles up yellow "waiting" ducks.
- **States**: working = teal for both generating and tool running; waiting = `#FFC400`; idle =
  no lamp, no halo, body colour mostly drained and alpha 0.55. Halo emission 2.2 → 0.7: under
  Blender's default AgX view the brighter glow rendered yellow as cream.
- **Key**: a screen-space legend (top right, `H`): halo = state, body colour = tool
  (`HARNESS_LABELS`), hat = model (`theme.HAT_LEGEND`).
- **Names**: duck names 0.2 m (ducklings 0.13 m), cut at 24 characters, on a dark badge sized to
  the text (`pool.add_badge` / `fit_badge`, fitted from the data timer because it evaluates the
  depsgraph); branch flags too. Session ducks scale 1.35 (was 1.6).
- **Lane signs**: `deck.LaneSigns` owns the whole sign: a screen-aligned root with a plate,
  folder name, branch · sessions · ≈$ line and state dots as children; the coin stack stands
  beside it. `pool.Lanes` only lays out lanes and ropes.

### 16.5 Tests
`tests/test_ledger.py` (pricing, de-duplication, local boundaries across midnight, Monday and
the 1st, per-session / per-folder spend, synthetic backfill, live event fields);
`tests/test_core.py::test_backfill_real_logs`; `tests/headless_smoke.py` (tabs, both lines, bar
counts per range, underline, month coin stack).
