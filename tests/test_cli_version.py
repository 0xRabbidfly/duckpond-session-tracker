"""Pure tests for the CLI version reader (no Blender, no CLI, no network).

    python tests/test_cli_version.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from duck_pond.cli_version import Versions, parse_latest, parse_local  # noqa: E402


def test_reads_the_real_cli_output():
    assert parse_local("2.1.273 (Claude Code)") == "2.1.273"


def test_reads_a_prerelease():
    assert parse_local("2.2.0-rc.1 (Claude Code)") == "2.2.0-rc.1"


def test_junk_from_the_cli_is_no_version():
    for bad in ("", "command not found", "Claude Code", "v2.1 beta"):
        assert parse_local(bad) == "", bad


def test_reads_the_registry_document():
    assert parse_latest('{"name": "@anthropic-ai/claude-code", "version": "2.1.278"}') == "2.1.278"


def test_junk_from_the_registry_is_no_version():
    for bad in ("", "not json", "{}", '{"version": null}', '{"version": "latest"}',
                '{"version": 3}', "[]"):
        assert parse_latest(bad) == "", bad


def test_behind_compares_numerically_not_as_text():
    # the whole point: "2.1.9" > "2.1.10" as strings, and that is the wrong answer
    assert Versions(yours="2.1.9", latest="2.1.10").behind
    assert not Versions(yours="2.1.10", latest="2.1.9").behind
    assert not Versions(yours="2.1.278", latest="2.1.278").behind
    assert Versions(yours="1.9.9", latest="2.0.0").behind


def test_a_prerelease_is_behind_its_own_release():
    assert Versions(yours="2.2.0-rc.1", latest="2.2.0").behind
    assert not Versions(yours="2.2.0", latest="2.2.0-rc.1").behind


def test_behind_needs_both_halves():
    assert not Versions(yours="2.1.273", latest="").behind
    assert not Versions(yours="", latest="2.1.278").behind


def test_known_is_either_half():
    assert not Versions().known
    assert Versions(yours="2.1.273").known
    assert Versions(latest="2.1.278").known


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
