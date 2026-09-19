"""Pure tests for the usage-limit reader (no Blender, no CLI).

    python tests/test_usage.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from duck_pond.usage_limits import Usage, parse_usage  # noqa: E402

REAL = """You are currently using your subscription to power your Claude Code usage

Current session: 24% used · resets Sep 19, 8:30pm (America/Toronto)
Current week (all models): 3% used · resets Sep 26, 4pm (America/Toronto)

What's contributing to your limits usage?
Approximate, based on local sessions on this machine — does not include other devices or claude.ai.

Last 24h · 1087 requests · 12 sessions
  83% of your usage was at >150k context
"""


def test_parses_the_real_output():
    u = parse_usage(REAL)
    assert u.ok
    assert abs(u.session.frac - 0.24) < 1e-9, u.session
    assert abs(u.week.frac - 0.03) < 1e-9, u.week
    assert u.session.resets == "Sep 19, 8:30pm", u.session.resets
    assert u.week.resets == "Sep 26, 4pm", u.week.resets


def test_ignores_the_percentages_in_the_breakdown():
    """The breakdown below is full of percentages; only the two limit lines count."""
    u = parse_usage(REAL)
    assert u.session.frac == 0.24 and u.week.frac == 0.03


def test_other_week_labels():
    u = parse_usage("Current session: 7% used · resets 9pm\nCurrent week (Opus): 88% used · resets Fri 4pm\n")
    assert u.ok and u.session.frac == 0.07 and abs(u.week.frac - 0.88) < 1e-9
    assert u.session.resets == "9pm" and u.week.resets == "Fri 4pm"


def test_decimals_and_clamping():
    u = parse_usage("Current session: 99.5% used · resets now\nCurrent week (all models): 120% used · resets later\n")
    assert abs(u.session.frac - 0.995) < 1e-9
    assert u.week.frac == 1.0, "over 100 % is still a full pitcher, not an overflowing one"


def test_one_window_missing_leaves_the_other_at_zero():
    u = parse_usage("Current session: 40% used · resets 8pm\n")
    assert u.ok and u.session.frac == 0.4
    assert u.week.frac == 0.0 and u.week.resets == ""


def test_api_key_user_gets_no_limits_and_says_why():
    u = parse_usage("You are using an API key, so there are no subscription limits to show.\n")
    assert not u.ok and "no limits in the CLI output" in u.error


def test_empty_output():
    u = parse_usage("")
    assert not u.ok and u.error == "the CLI printed nothing"


def test_a_default_usage_is_empty_not_an_error():
    u = Usage()
    assert not u.ok and u.session.frac == 0.0 and u.week.frac == 0.0 and u.error == ""


def test_reset_keeps_the_date_but_drops_the_timezone():
    u = parse_usage("Current session: 1% used · resets Sep 19, 8:30pm (America/Toronto)\n")
    assert u.session.resets == "Sep 19, 8:30pm"


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"ERROR {name}: {exc!r}")
    sys.exit(1 if failures else 0)
