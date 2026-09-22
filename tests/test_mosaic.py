"""Pure tests for the deck mosaic: per-project spend per bucket (no Blender).

    python tests/test_mosaic.py

The mosaic is the one surface that says *which* folder spent the money and *when*. The board
only ever says what the fleet spent in total, so the split is new information and the sum of
the rows has to agree with it.
"""
import os
import sys
from datetime import timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from duck_pond.ledger import UsageLedger  # noqa: E402
from duck_pond.model import Fleet  # noqa: E402
from duck_pond.theme import folder_name  # noqa: E402
from duck_pond.ui.cards import heat_model  # noqa: E402

TZ = timezone(timedelta(hours=-4))   # a fixed offset keeps the hour boundaries deterministic
NOW = 1_700_000_000.0
HOUR = 3600.0


def _fleet(rows):
    f = Fleet()
    f.ledger = UsageLedger(tz=TZ)
    for at, cwd, usd in rows:
        f.ledger.add({"at": at, "session_id": "s", "cwd": cwd, "usd": usd, "key": f"{at}{cwd}{usd}"})
    f.ledger.ready = True
    return f


def test_folder_name_is_the_last_segment():
    assert folder_name("C:\\Users\\dev\\Projects\\storefront") == "storefront"
    assert folder_name("/home/dev/docs-site/") == "docs-site"
    assert folder_name("") == "(no cwd)"
    assert folder_name("/home/dev/an-extremely-long-folder", 12) == "an-extremel…"


def test_a_folders_bars_land_in_the_right_hours():
    f = _fleet([(NOW - 2 * HOUR, "/a", 1.0), (NOW - 2 * HOUR + 30, "/a", 0.5),
                (NOW - 10 * HOUR, "/a", 2.0)])
    bars = f.ledger.cwd_bars("/a", "hour", NOW)
    assert len(bars) == 24
    assert abs(bars[-3] - 1.5) < 1e-9, bars[-3]     # both rows in the same hour, added up
    assert abs(bars[-11] - 2.0) < 1e-9, bars[-11]
    assert abs(sum(bars) - 3.5) < 1e-9


def test_the_rows_add_up_to_the_board():
    f = _fleet([(NOW - 3 * HOUR, "/a", 1.0), (NOW - 3 * HOUR, "/b", 2.0),
                (NOW - 9 * HOUR, "/b", 0.25)])
    total = f.ledger.bars("hour", NOW)
    per = [f.ledger.cwd_bars(c, "hour", NOW) for c in ("/a", "/b")]
    for i, t in enumerate(total):
        assert abs(t - sum(p[i] for p in per)) < 1e-9, i


def test_a_folder_with_nothing_is_all_zeroes_not_an_error():
    f = _fleet([(NOW - HOUR, "/a", 1.0)])
    assert f.ledger.cwd_bars("/nope", "hour", NOW) == [0.0] * 24


def test_spend_outside_the_window_is_left_out():
    f = _fleet([(NOW - 40 * HOUR, "/a", 9.0), (NOW - HOUR, "/a", 1.0)])
    bars = f.ledger.cwd_bars("/a", "hour", NOW)
    assert abs(sum(bars) - 1.0) < 1e-9, sum(bars)


def test_cwds_are_busiest_first():
    f = _fleet([(NOW - HOUR, "/quiet", 0.1), (NOW - HOUR, "/loud", 5.0)])
    assert f.ledger.cwds() == ["/loud", "/quiet"]


def test_the_model_keeps_the_pools_own_lane_order():
    f = _fleet([(NOW - HOUR, "/a", 0.1), (NOW - HOUR, "/b", 5.0)])
    h = heat_model(f, NOW, "hour", keys=["/a", "/b"])
    assert [name for name, _v in h.rows] == ["a", "b"], h.rows


def test_a_lane_with_no_spend_still_gets_a_row():
    # "nothing happened in this project" is worth seeing, not worth hiding
    f = _fleet([(NOW - HOUR, "/a", 1.0)])
    h = heat_model(f, NOW, "hour", keys=["/a", "/idle"])
    assert [name for name, _v in h.rows] == ["a", "idle"]
    assert sum(dict(h.rows)["idle"]) == 0.0


def test_a_folder_with_no_lane_and_no_spend_is_dropped()  :
    f = _fleet([(NOW - 40 * HOUR, "/ancient", 9.0), (NOW - HOUR, "/a", 1.0)])
    h = heat_model(f, NOW, "hour", keys=["/a"])
    assert [name for name, _v in h.rows] == ["a"], h.rows


def test_too_many_folders_keeps_the_busiest():
    rows = [(NOW - HOUR, f"/p{i}", float(i)) for i in range(9)]
    f = _fleet(rows)
    h = heat_model(f, NOW, "hour", keys=[], max_rows=3)
    assert [name for name, _v in h.rows] == ["p8", "p7", "p6"], h.rows


def test_the_peak_is_the_biggest_single_cell():
    f = _fleet([(NOW - 2 * HOUR, "/a", 1.0), (NOW - 3 * HOUR, "/b", 4.0)])
    h = heat_model(f, NOW, "hour", keys=["/a", "/b"])
    assert abs(h.peak - 4.0) < 1e-9
    assert "b" in h.foot and "4" in h.foot, h.foot


def test_the_last_column_is_the_hour_we_are_in():
    f = _fleet([(NOW, "/a", 1.0)])
    h = heat_model(f, NOW, "hour", keys=["/a"])
    assert h.now_col == 23
    assert dict(h.rows)["a"][h.now_col] > 0, "spend from a minute ago belongs to the last column"


def test_ticks_are_spread_across_the_row_and_read_as_clock_times():
    f = _fleet([(NOW, "/a", 1.0)])
    h = heat_model(f, NOW, "hour", keys=["/a"])
    cols = [c for c, _lab in h.ticks]
    assert cols == [0, 6, 12, 18], cols
    assert all(lab.endswith(":00") and len(lab) == 5 for _c, lab in h.ticks), h.ticks


def test_an_empty_pond_says_so_rather_than_drawing_nothing():
    h = heat_model(_fleet([]), NOW, "hour", keys=[])
    assert h.rows == []
    assert h.peak == 0.0
    assert "nothing" in h.foot, h.foot


def test_a_ledger_still_scanning_says_that_instead():
    f = _fleet([(NOW, "/a", 1.0)])
    f.ledger.ready = False
    h = heat_model(f, NOW, "hour", keys=["/a"])
    assert not h.ready and h.rows == [] and "scanning" in h.foot


def test_every_range_works_not_just_the_hour():
    f = _fleet([(NOW - HOUR, "/a", 1.0)])
    for name in ("min", "hour", "day", "week", "month"):
        h = heat_model(f, NOW, name, keys=["/a"])
        assert h.title, name
        assert len(dict(h.rows)["a"]) == len(f.ledger.bars(name, NOW)), name


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
