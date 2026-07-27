import pytest
from mlglance.cli import build_parser, parse_interval, auto_interval, AUTO_MIN, AUTO_MAX, AUTO_COLD


def test_cli_defaults():
    a = build_parser().parse_args([])
    assert a.path is None
    assert a.watch is False
    assert a.interval is None          # auto by default
    assert a.total == 0


def test_cli_flags_wire_through():
    a = build_parser().parse_args(
        ["f.jsonl", "--ascii", "--no-color", "--log-y", "--total", "500", "-n", "0.5", "-w"])
    assert a.path == "f.jsonl"
    assert a.ascii and a.no_color and a.log_y and a.watch
    assert a.total == 500
    assert a.interval == 0.5


def test_interval_auto_and_presets():
    p = build_parser()
    assert p.parse_args(["-n", "auto"]).interval is None
    assert p.parse_args(["-n", "5"]).interval == 5.0
    assert p.parse_args(["-n", "30"]).interval == 30.0
    assert p.parse_args(["-n", "1min"]).interval == 60.0
    assert p.parse_args(["-n", "2m"]).interval == 120.0
    assert p.parse_args(["-n", "0.5s"]).interval == 0.5


def test_parse_interval_rejects_garbage():
    for bad in ["nope", "0", "-3", "1.2.3"]:
        with pytest.raises(Exception):
            parse_interval(bad)


def test_auto_interval_tracks_cadence():
    # cold start before cadence is known → the cold default
    assert auto_interval(None, 0.0) == AUTO_COLD
    # but ease toward the ceiling if a static/finished file never writes
    assert auto_interval(None, 100.0) == AUTO_MAX
    # fast run floors out; very slow run climbs toward (and clamps at) the ceiling
    assert auto_interval(0.2, 0.0) == AUTO_MIN
    assert auto_interval(4.0, 0.0) == 2.0          # 4s/step → poll ~2s
    assert auto_interval(30.0, 0.0) == AUTO_MAX     # 30s/step → clamped at ceiling
    # a quiet stream (idle ≫ cadence) backs the poll off above the steady value
    assert auto_interval(1.0, 12.0) > auto_interval(1.0, 0.0)


def test_cli_version_exits_zero(capsys):
    with pytest.raises(SystemExit) as e:
        build_parser().parse_args(["--version"])
    assert e.value.code == 0
    assert "0.1.0" in capsys.readouterr().out
