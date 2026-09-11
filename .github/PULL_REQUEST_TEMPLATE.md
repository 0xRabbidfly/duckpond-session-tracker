## What

<!-- One or two sentences. What does the pool do differently after this change? -->

## Why

<!-- The problem, the signal that was invisible, the jitter you saw. Link the issue if there is one. -->

## How to see it

<!-- Every kept idea must be visible in Blender. Tell the reviewer where to look:
     a fixture event, a key to press, a still in out/. Paste a screenshot or clip if it is visual. -->

## Checklist

- [ ] `ruff check .` passes
- [ ] `python tests/test_core.py` and `python tests/test_signals.py` pass
- [ ] `blender -b --python tests/headless_motion.py` still prints `ALL PASS` (the smoothness contract)
- [ ] `blender -b --python tests/headless_smoke.py` passes if the scene or fixture changed
- [ ] New behaviour has a test, or the PR says why it cannot
- [ ] Nothing writes under `~/.claude/projects` (read-only, always)
- [ ] `README.md` / `SPEC.md` / `CHANGELOG.md` updated if a user sees the change
