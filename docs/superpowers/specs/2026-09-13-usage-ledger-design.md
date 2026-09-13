# Usage ledger and range picker — design

Date: 2026-09-13 · Status: approved in chat, awaiting spec review

## Problem

The scoreboard's `$ spent` sums `Session.cost_usd` over `Fleet.sessions`. A session leaves that dict
about 31 minutes after it goes quiet (30 min to `ended`, 60 s fade), and at startup the adapter only
opens transcripts touched in the last 10 minutes. So spend shrinks when ducks leave, and a restart
forgets almost everything. The bar chart is 30 bars of output tokens per minute (`Fleet.history`,
60 minutes kept) and nothing says so.

Findings from the local logs (`~/.claude/projects`, 2026-09-13):

- `cost-state` lines are rare (2 of 20 recent transcripts), carry a session running total, and have
  **no timestamp**. They cannot be bucketed by time.
- Every assistant line carries `message.usage` with a timestamp: `input_tokens`,
  `cache_creation_input_tokens` (split into `cache_creation.ephemeral_5m_input_tokens` /
  `ephemeral_1h_input_tokens`), `cache_read_input_tokens`, `output_tokens`, `speed`.
- One API reply is often written as several lines repeating the same usage: 9,091 repeated
  `(message.id, requestId)` pairs in a month. The adapter counts each line today, so `tok/min`
  and per-session tokens are inflated.
- A month is 605 session transcripts + 70 sub-agent transcripts, ~480 MB; oldest 2026-08-14
  (Claude Code's 30-day cleanup). Scanning only lines containing `"usage"` takes 1.1 s.

## Decisions (from the brainstorm)

1. Stats: a picker-driven "this range" line **plus** a fixed month-to-date line.
2. Money is an estimate: tokens × API list price, shown as `≈$` (API-equivalent, not a bill).
3. No history file. Everything is rebuilt from the transcripts on disk at startup; week and month
   bars only reach back as far as Claude Code keeps logs (~30 days).
4. Bars show ≈$ per bucket. Tabs are clickable on the board; `T` cycles; the sidebar has the same
   choice.

## Architecture

```
transcripts ──► ClaudeCodeAdapter ──► worker queue ──► Fleet.apply ──► UsageLedger ──► Scoreboard
   (on disk)     backfill() once:                      _on_Usage          (minute        LaneSigns
                 UsageBatch per file                   _on_UsageBatch     buckets)       cards / panel
                 poll(): live Usage (+key, model, cache split)
```

### `duck_pond/pricing.py` (new, pure)

- `PRICES`: model-family prefix → `(input, output, cache_read)` in $/MTok. Longest prefix wins.
  Source: Claude API reference, cached 2026-06-24.

  | prefix | input | output | cache read |
  |---|---|---|---|
  | `claude-fable-5-1` | 10 | 50 | 0.25 |
  | `claude-fable-5` | 10 | 50 | 1.00 |
  | `claude-opus-5` | 5 | 25 | 0.50 |
  | `claude-opus-4-8` | 5 | 25 | 0.50 |
  | `claude-sonnet-5` | 2 | 10 | 0.20 |
  | `claude-haiku-4-5` | 1 | 5 | 0.10 |

- Cache writes: 5-minute TTL at 1.25 × input, 1-hour TTL at 2 × input. When the TTL split is
  absent, all `cache_creation_input_tokens` count as 5-minute.
- `speed == "fast"` doubles input and output rates (Opus 5 fast mode is $10/$50).
- `cost(model, in, cw5m, cw1h, cr, out, speed) -> float | None`. `None` = unknown model; its
  tokens still count.

### `duck_pond/ledger.py` (new, pure)

- `UsageLedger.add(row) -> bool`: `row` has `at, session_id, agent_id, cwd, model, key, tokens_in,
  cache_write_5m, cache_write_1h, cache_read, tokens_out, speed`. Returns `False` for a repeated
  `key` (`message.id + ":" + requestId`; rows without a key are never de-duplicated).
- Storage: one bucket per UTC minute epoch → `[usd, unpriced_tokens, tokens_in, cache_write,
  cache_read, tokens_out]` plus a set of session ids. Per session: usd and tokens. Per cwd: a list
  of `(minute, usd)` for month-to-date lookups.
- Queries (`now` passed in; local time via `time.localtime`, overridable in tests):
  - `window(start, end) -> Stats(usd, unpriced, tokens_out, sessions)`
  - `bars(range_name, now) -> list[(label_start, usd)]` and the window it covers
  - `month_to_date(now) -> Stats` (from local 00:00 on the 1st)
  - `session_usd(session_id)`, `cwd_month_usd(cwd, now)`, `today(now) -> Stats`
- `ready` flag: `False` until the backfill has been applied.
- "sessions" in any `Stats` = distinct session ids with at least one usage row in the window.
  Sub-agent rows carry their parent's session id, so a sub-agent never counts as its own session.
- "out tok" = `tokens_out` only; cache reads dominate total tokens and would drown the number.

Ranges (bucket boundaries in local time; weeks start Monday):

| range | bars | bucket | stats line label |
|---|---|---|---|
| `min` | 60 | 1 minute | `last 60 min` |
| `hour` (default) | 24 | 1 hour | `last 24 h` |
| `day` | 30 | local day | `last 30 days` |
| `week` | 8 | Mon–Sun | `last 8 weeks` |
| `month` | 6 | calendar month | `last 6 months` |

### Adapter (`duck_pond/adapters/claude_code.py`)

- `_usage_event` gains `model`, `key`, `cache_write_5m`, `cache_write_1h`, `cache_read`, `speed`.
  Existing `tokens_in` / `tokens_out` / `context_used` keep their meaning.
- New `backfill(now) -> list[dict]`: every `*.jsonl` and `subagents/agent-*.jsonl` under the
  projects dir, lines containing `"usage"` (plus the first line with `cwd` per file), emitting one
  `{"type": "UsageBatch", "rows": [...]}` per file. No `SessionSeen`, so no ducks. Unreadable
  files and malformed lines are skipped.
- `Adapter.backfill` in `base.py` defaults to `[]` (the stub fixture's live `Usage` events feed the
  ledger directly).

### Fleet and runtime

- `Fleet.ledger = UsageLedger()`. `_on_Usage` skips a reply key the fleet has already counted
  (its own set, separate from the ledger's, so the backfill cannot zero live session tokens),
  then adds the row to the ledger and updates agent tokens, samples and the per-minute `history`.
  This fixes the inflated `tok/min`. When a Usage event reports a running `cost_usd` (the demo
  fixture, adapters for other tools), the increase is the row's `usd` instead of a price lookup. `_on_UsageBatch` adds rows to the ledger only. A `BackfillDone` event sets
  `ledger.ready`.
- `Runtime._worker_loop` calls each adapter's `backfill` once before polling, queues the batches,
  then `BackfillDone`. Errors go to `last_error`; live polling still starts.
- `Runtime.board_range = "hour"`; `DuckPondSettings.board_range` (EnumProperty, update callback)
  mirrors it; `T` in the hover modal cycles it.
- `Session.cost_usd` (recorded `cost-state`) stays as it is; `Fleet.totals` keeps its keys.

### Scoreboard (`duck_pond/scene/deck.py`)

Board grows taller. Rows, top to bottom:

1. states: `2 WORKING · 1 WAITING · 3 IDLE` (unchanged)
2. tabs: five text objects, `dp_kind = "range_tab"`, `dp_range = <name>`; selected one gold with an
   underline bar, others dim
3. range stats: `last 24 h   ≈$84.10 · 1.1M out tok · 12 sessions`
4. month-to-date: `September   ≈$1,240 · 14M out tok · 311 sessions`
5. bars: 60 pre-built, the first N shown for the range, height = usd / peak; the current bucket gold
6. footer: `peak ≈$9.80/h · 13:05 Sunday 13 September`; on `week` / `month` also
   `(logs keep ~30 days)`

`≈$x +?` when the window has unpriced tokens. Before `ledger.ready`, rows 3–4 read `scanning logs…`.

### Clicks (`duck_pond/ui/hover.py`)

`_cast` keeps the hit object. A click on a `range_tab` sets the range and leaves the pin alone;
otherwise the existing pin / release behaviour applies.

### Other readers

- Lane signs: `$` and coins become `ledger.cwd_month_usd(cwd)`.
- Hover card: session `$` becomes `≈$` from `ledger.session_usd`; when a recorded `cost-state` total
  exists it is shown as well (`≈$41.20 · recorded $39.80`).
- Card footer (`cards.totals_line`): `≈$ today`.
- Sidebar: the range dropdown; per-model spend keeps using `model_usage`.

## Error handling

- Unknown model: tokens counted, usd excluded, `+?` shown.
- Line without a timestamp: live events use the poll time (existing `_ts` fallback); backfill skips
  the row.
- Backfill failure: `last_error` is set and `BackfillDone` is still queued, so the board leaves
  `scanning logs…` and shows whatever was loaded plus live usage from then on.
- Files disappearing mid-scan: skipped.

## Testing

- `tests/test_ledger.py` (pure): key de-duplication; bucketing across local midnight, a Monday and
  the 1st of a month with an injected timezone; each range's bar count and window; pricing for
  5-minute vs 1-hour cache writes, Fable 5.1 cache reads, Opus 5 fast mode; unknown model → `+?`;
  `session_usd` and `cwd_month_usd`.
- `tests/test_signals.py`: repeated usage lines no longer double `history` or tokens.
- `tests/test_core.py`: `backfill` on the real logs creates no sessions and yields a ledger with
  usd > 0; timing printed.
- `tests/headless_smoke.py`: tab objects exist, rows 3–4 have text, bar count per range, clicking
  logic covered by setting `RT.board_range`.
- GUI (event simulation, as for click-to-pin): click each tab and press `T`; check row 3's label and
  the visible bar count; screenshot.

## Docs

`SPEC.md` new section (usage ledger, ranges, estimate caveat), README scoreboard paragraph and keys
table (`T`, tab click), `CHANGELOG.md` entries (added ledger and picker; changed de-duplicated
tokens, lane sign and card spend).

## Out of scope

A history file, user-editable price overrides, pricing for non-Claude harnesses (their tokens show
under `+?`), Bedrock/Vertex rate cards.
