"""Synthetic lake -> real staging/gates -> mocked dump, with no host provider."""

import json
import socket
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qlib_scripts import build_etf_qlib as build  # noqa: E402
from qlib_scripts import stage_etf_daily_from_lake as stage  # noqa: E402

FIXTURE_LAKE = ROOT / "tests" / "fixtures" / "etf_daily_lake"
FRONT_ROOT = FIXTURE_LAKE / "dividend_type=front"
EXPECTED_ROWS = {"sh510300": 31, "sh510050": 16, "sz159915": 11, "sh518880": 9}


@pytest.fixture(autouse=True)
def offline_only(tmp_path: Path, monkeypatch):
    # Default protected paths resolve inside the test, never under the real home.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    for name in ("OSKH_SOURCE_PARQUET_ROOT", "OSKH_ETF_DAILY_ROOT"):
        monkeypatch.setenv(name, str(tmp_path / "unused-lake"))
    protected = build.default_protected()
    for path in protected:
        path.mkdir(parents=True)
        (path / "KEEP").write_text("stock sentinel", encoding="utf-8")

    def unexpected(*_args, **_kwargs):
        pytest.fail("Offline smoke must not use network, subprocesses, real wipe, or qlib readback")

    monkeypatch.setattr(socket, "create_connection", unexpected)
    monkeypatch.setattr(socket.socket, "connect", unexpected)
    monkeypatch.setattr(build, "_run", unexpected)
    monkeypatch.setattr(build, "default_wipe", unexpected)
    monkeypatch.setattr(build, "verify_readback", unexpected)
    originals = {path: path.read_bytes() for path in FIXTURE_LAKE.rglob("*.parquet")}
    yield
    assert {path: path.read_bytes() for path in FIXTURE_LAKE.rglob("*.parquet")} == originals
    for path in protected:
        assert list(path.iterdir()) == [path / "KEEP"]
        assert (path / "KEEP").read_text(encoding="utf-8") == "stock sentinel"


@pytest.fixture
def cfg(tmp_path: Path) -> build.BuildConfig:
    return build.BuildConfig(
        lake_root=FRONT_ROOT,
        staging_dir=tmp_path / "staging",
        qlib_dir=tmp_path / "my_data_etf",
        meta_dir=tmp_path / "meta",
        verify=False,
    )


def _stage(cfg: build.BuildConfig) -> dict:
    assert cfg.resolved_lake() == FRONT_ROOT
    return stage.stage_lake(cfg.resolved_lake(), cfg.staging_dir, max_workers=1)


def test_fixture_staging_calendar_vwap_basis_and_dump_argv(cfg):
    payload = _stage(cfg)
    assert payload["written"] == 4
    assert payload["window"] == [stage.WINDOW_START, stage.WINDOW_END]
    assert payload["skipped_empty"] == payload["dropped_no_none"] == 0
    calendar = build.ensure_calendar_subset(cfg.staging_dir)
    assert len(calendar) == 31
    assert calendar.min() == pd.Timestamp(stage.WINDOW_START)
    assert calendar.max() == pd.Timestamp(stage.WINDOW_END)
    assert (calendar.weekday < 5).all()
    assert {path.stem for path in cfg.staging_dir.glob("*.parquet")} == set(EXPECTED_ROWS)
    for stem, rows in EXPECTED_ROWS.items():
        frame = pd.read_parquet(cfg.staging_dir / f"{stem}.parquet")
        assert list(frame.columns) == ["date", "symbol", *stage.DUMP_FIELDS]
        assert len(frame) == rows
        assert set(frame["symbol"]) == {stem.upper()}
        assert set(frame["date"]) <= set(calendar)
        if stem != build.CALENDAR_STEM:
            assert set(frame["date"]) < set(calendar)
        assert frame["vwap"].tolist() == pytest.approx(frame["close"].tolist())

    reports = build.ensure_staged_vwap(cfg.staging_dir)
    assert {report["stem"] for report in reports} == set(EXPECTED_ROWS)
    for evidence in build.ensure_lake_basis(FRONT_ROOT):
        assert evidence["px_start"] == pytest.approx(0.88)
        assert evidence["px_end"] == pytest.approx(1.0)
        assert evidence["amt_ratio_median"] == evidence["vol_ratio_median"] == 1.0
        assert evidence["raw_gap_median"] > evidence["scaled_gap_median"]

    argv = build.dump_argv(cfg)
    assert argv[:3] == [sys.executable, str(build.DUMP_BIN), "dump_all"]
    assert f"--data_path={cfg.staging_dir}" in argv
    assert f"--qlib_dir={cfg.qlib_dir}" in argv
    assert "--file_suffix=.parquet" in argv
    assert "--max_workers=8" in argv
    assert "--exclude_fields=symbol" in argv
    assert f"--include_fields={','.join(stage.DUMP_FIELDS)}" in argv
    assert not any("dump_update" in arg for arg in argv)


def test_execute_dumps_only_after_real_fixture_gates(cfg, monkeypatch):
    calls = []
    cfg.wipe_qlib_dir = True
    cfg.qlib_dir.mkdir()
    sentinel = cfg.qlib_dir / "partial"
    sentinel.write_text("mock wipe keeps this", encoding="utf-8")

    def record_gate(name, original):
        def checked(path):
            result = original(path)
            calls.append(name)
            return result

        return checked

    for name in ("ensure_calendar_subset", "ensure_staged_vwap", "ensure_lake_basis"):
        monkeypatch.setattr(build, name, record_gate(name, getattr(build, name)))

    def stage_spy(config):
        _stage(config)
        calls.append("stage")

    def wipe_spy(path):
        assert path == cfg.qlib_dir
        calls.append("wipe")

    def dump_spy(config):
        assert config is cfg
        assert calls == ["wipe", "stage", "ensure_calendar_subset", "ensure_staged_vwap", "ensure_lake_basis"]
        evidence = json.loads((config.resolved_meta() / "vwap_basis.json").read_text(encoding="utf-8"))
        assert {row["code"] for row in evidence} == set(build.READBACK_CODES)
        calls.append("dump")

    assert build.execute(cfg, stage_fn=stage_spy, dump_fn=dump_spy, wipe_fn=wipe_spy) == 0
    assert calls.count("dump") == 1
    assert calls[-1] == "dump"
    assert sentinel.read_text(encoding="utf-8") == "mock wipe keeps this"
    assert not (cfg.qlib_dir / "features").exists()
    # Tiny fixtures intentionally cannot satisfy the unchanged ETF_FULL_MIN_BARS.
    assert (cfg.qlib_dir / "instruments" / "etf_full.txt").read_text(encoding="utf-8") == ""
    gaps = pd.read_csv(cfg.resolved_meta() / "etf_full_gaps.csv")
    assert len(gaps) == 4
    assert not gaps["in_etf_full"].any()


@pytest.mark.parametrize(
    ("broken", "message"),
    [("extra_date", "超出 510300"), ("weekend", "非交易日"), ("vwap", "VWAP")],
)
def test_broken_staging_stops_before_dump(cfg, broken, message):
    calls = []

    def broken_stage(config):
        _stage(config)
        stem = "sh510050" if broken == "extra_date" else build.CALENDAR_STEM
        path = config.staging_dir / f"{stem}.parquet"
        frame = pd.read_parquet(path)
        if broken == "vwap":
            frame["vwap"] = frame["close"] * 1.1
        else:
            # A weekday outside the sparse reference calendar must also fail.
            day = "2020-01-03" if broken == "extra_date" else "2020-01-04"
            frame.loc[1, "date"] = pd.Timestamp(day)
        frame.to_parquet(path, index=False)
        calls.append("stage")

    with pytest.raises(build.BuildEtfError, match=message):
        build.execute(
            cfg,
            stage_fn=broken_stage,
            dump_fn=lambda _cfg: calls.append("dump"),
            wipe_fn=lambda _path: calls.append("wipe"),
        )
    assert calls == ["stage"]
    assert not cfg.qlib_dir.exists()
    assert not cfg.resolved_meta().exists()


@pytest.mark.parametrize("provider", ["my_data", "my_data_1min"])
def test_fixture_refuses_default_protected_provider_before_any_work(cfg, provider):
    cfg.qlib_dir = Path.home() / ".qlib" / "qlib_data" / provider
    cfg.wipe_qlib_dir = True
    calls = []
    with pytest.raises(build.BuildEtfError, match="受保护目录"):
        build.execute(
            cfg,
            stage_fn=lambda _cfg: calls.append("stage"),
            dump_fn=lambda _cfg: calls.append("dump"),
            wipe_fn=lambda _path: calls.append("wipe"),
        )
    assert calls == []
    assert not cfg.staging_dir.exists()
    assert not cfg.resolved_meta().exists()


def test_fixture_cli_dry_run_does_not_stage_wipe_or_dump(cfg, capsys):
    cfg.qlib_dir.mkdir()
    sentinel = cfg.qlib_dir / "KEEP"
    sentinel.write_text("ETF sentinel", encoding="utf-8")
    assert build.main(
        [
            "--lake-root", str(FRONT_ROOT),
            "--staging-dir", str(cfg.staging_dir),
            "--qlib-dir", str(cfg.qlib_dir),
            "--meta-dir", str(cfg.resolved_meta()),
            "--wipe-qlib-dir", "--dry-run",
        ]
    ) == 0
    output = capsys.readouterr().out
    assert str(FRONT_ROOT) in output
    assert "dump_all" in output
    assert "--max-workers 8" in output
    assert "--max_workers=8" in output
    assert "dump_update" not in output
    assert not cfg.staging_dir.exists()
    assert not cfg.resolved_meta().exists()
    assert list(cfg.qlib_dir.iterdir()) == [sentinel]
    assert sentinel.read_text(encoding="utf-8") == "ETF sentinel"
