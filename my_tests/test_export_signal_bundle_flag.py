import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import my_scripts.export_daily_pool as edp
import pytest
from myquant_contract import canonical_json_bytes, validate_signal_bundle


@pytest.fixture
def prediction(tmp_path, monkeypatch):
    monkeypatch.setattr(edp, "REPO_ROOT", tmp_path)
    path = tmp_path / "pred.csv"
    path.write_text(
        "datetime,instrument,score\n"
        "2026-03-06,SZ000001,2\n"
        "2026-03-06,SH600000,1\n"
        "2026-03-11,SZ300190,3\n",
        encoding="utf-8",
    )
    return path


def _run(prediction, output, *flags):
    return edp.main(["--pred", str(prediction), "--out-dir", str(output), *flags])


def _bundle(output):
    payload = (output / "signal-bundle.json").read_bytes()
    bundle = json.loads(payload)
    validate_signal_bundle(bundle)
    assert payload == canonical_json_bytes(bundle)
    return bundle


def test_default_cli_writes_no_sidecar(prediction, tmp_path):
    output = tmp_path / "off"
    assert _run(prediction, output) == 0
    assert not (output / "signal-bundle.json").exists()
    assert (output / "20260311.csv").read_bytes() == b"000001\n600000\n"
    args = edp.build_parser().parse_args(["--pred", str(prediction)])
    assert args.emit_signal_bundle is False
    assert args.available_at_time is None
    assert args.price_domain == "unspecified"


def test_flag_writes_bundle_pred_minus_one_skips_last_day(prediction, tmp_path):
    output = tmp_path / "on"
    assert _run(prediction, output, "--emit-signal-bundle") == 0
    bundle = _bundle(output)
    assert bundle["signal_asof_policy"] == "pred_minus_one"
    assert bundle["availability"] == "unproven"
    assert bundle["available_at"] is None
    assert bundle["price_domain"] == "unspecified"
    assert len(bundle["rows"]) == 1
    row = bundle["rows"][0]
    assert row["signal_asof"] == "2026-03-06"
    assert row["target_session"] == "2026-03-11"
    assert row["pool_file"] == "20260311.csv"
    payload = (output / row["pool_file"]).read_bytes()
    assert row["pool_md5"] == hashlib.md5(payload).hexdigest()
    assert row["pool_sha256"] == hashlib.sha256(payload).hexdigest()
    assert sorted(p.name for p in output.glob("*.csv")) == ["20260311.csv"]


def test_file_path_cli_emits_valid_bundle_without_pythonpath(prediction, tmp_path):
    # Keep the real entry point and its repository layout, including manifest
    # writes, entirely under tmp_path. No wrapper may supply the missing path.
    source_root = Path(edp.__file__).resolve().parents[1]
    cli_root = tmp_path / "cli-repo"
    scripts = cli_root / "my_scripts"
    scripts.mkdir(parents=True)
    for filename in (
        "export_daily_pool.py", "host_env.py", "float_cap_gate.py",
        "data_root.py", "ranking_neutralize.py", "run_manifest.py",
    ):
        shutil.copy2(source_root / "my_scripts" / filename, scripts / filename)
    shutil.copytree(
        source_root / "myquant_contract", cli_root / "myquant_contract",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    output = tmp_path / "cli-output"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable, "my_scripts/export_daily_pool.py", "--pred", str(prediction),
            "--out-dir", str(output), "--emit-signal-bundle",
        ],
        cwd=cli_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    bundle = _bundle(output)
    assert [row["pool_file"] for row in bundle["rows"]] == ["20260311.csv"]
    assert (output / "20260311.csv").read_bytes() == b"000001\n600000\n"
    assert (cli_root / "manifests").is_dir()


def test_flag_declared_time_stamps_signal_asof_not_buy_date(prediction, tmp_path):
    with prediction.open("a", encoding="utf-8") as stream:
        stream.write("2026-03-16,BJ920014,4\n")
    output = tmp_path / "declared"
    assert _run(
        prediction, output, "--emit-signal-bundle", "--available-at-time", "15:30:00+08:00",
        "--price-domain", "front",
    ) == 0
    bundle = _bundle(output)
    assert bundle["availability"] == "declared"
    assert bundle["available_at"] == "2026-03-06T15:30:00+08:00"
    assert [row["signal_asof"] for row in bundle["rows"]] == ["2026-03-06", "2026-03-11"]
    assert bundle["price_domain"] == "front"


@pytest.mark.parametrize("invalid_time", ["2026-03-12T00:00:00+08:00", "24:00:00+08:00"])
def test_flag_rejects_non_clock_available_at_time(prediction, tmp_path, capsys, invalid_time):
    # The CLI rejects full timestamps and rollover hours as invalid clocks;
    # the builder tests cover available_at dates after target_session.
    output = tmp_path / "invalid"
    with pytest.raises(SystemExit) as exc:
        _run(prediction, output, "--emit-signal-bundle", "--available-at-time", invalid_time)
    assert exc.value.code == 2
    assert "--available-at-time must be HH:MM:SS+08:00" in capsys.readouterr().err
    assert not (output / "signal-bundle.json").exists()


@pytest.mark.parametrize("asof", ["pred_minus_one", "identity"])
def test_pool_csv_bytes_unchanged_when_flag_on(prediction, tmp_path, asof):
    off, on = tmp_path / "off", tmp_path / "on"
    assert _run(prediction, off, "--asof", asof) == 0
    assert _run(prediction, on, "--asof", asof, "--emit-signal-bundle") == 0
    files = lambda root: {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*.csv")}
    assert files(off) == files(on)
    assert _bundle(on)["signal_asof_policy"] == asof


def test_bundle_omits_invalid_days_scores_only_and_stale_files(prediction, tmp_path):
    prediction.write_text(
        "datetime,instrument,score\n2026-03-06,INVALID,1\n"
        "2026-03-11,SZ000001,2\n2026-03-16,SH600000,3\n", encoding="utf-8",
    )
    output = tmp_path / "out"
    output.mkdir()
    stale = output / "20260311.csv"
    stale.write_bytes(b"300190\n")
    assert _run(prediction, output, "--emit-signal-bundle") == 0
    assert [row["pool_file"] for row in _bundle(output)["rows"]] == ["20260316.csv"]
    assert stale.read_bytes() == b"300190\n"
    bundle_before = (output / "signal-bundle.json").read_bytes()
    pools_before = {p.name: p.read_bytes() for p in output.glob("*.csv")}
    assert _run(prediction, output, "--scores-only", "--emit-signal-bundle") == 0
    assert (output / "signal-bundle.json").read_bytes() == bundle_before
    assert {p.name: p.read_bytes() for p in output.glob("*.csv")} == pools_before


def test_empty_export_preserves_existing_bundle(prediction, tmp_path):
    output = tmp_path / "existing"
    assert _run(prediction, output, "--emit-signal-bundle") == 0
    bundle_before = (output / "signal-bundle.json").read_bytes()
    pool_before = (output / "20260311.csv").read_bytes()
    prediction.write_text("datetime,instrument,score\n2026-03-06,SZ000001,2\n", encoding="utf-8")
    assert _run(prediction, output, "--emit-signal-bundle") == 0
    assert (output / "signal-bundle.json").read_bytes() == bundle_before
    assert (output / "20260311.csv").read_bytes() == pool_before


def test_scores_only_in_fresh_directory_writes_empty_bundle(prediction, tmp_path):
    output = tmp_path / "scores-only"
    assert _run(prediction, output, "--scores-only", "--emit-signal-bundle") == 0
    assert _bundle(output)["rows"] == []
    assert not list(output.glob("*.csv"))
    assert (output / "scores" / "20260311.csv").is_file()


def test_empty_export_does_not_invent_signal_date(prediction, tmp_path, capsys):
    prediction.write_text("datetime,instrument,score\n2026-03-06,SZ000001,2\n", encoding="utf-8")
    output = tmp_path / "empty"
    assert _run(prediction, output, "--emit-signal-bundle") == 0
    assert _bundle(output)["rows"] == []
    with pytest.raises(SystemExit) as exc:
        _run(prediction, tmp_path / "empty-declared", "--emit-signal-bundle",
             "--available-at-time", "15:00:00+08:00")
    assert exc.value.code == 2
    assert "without a written pool's signal_asof" in capsys.readouterr().err


def test_builder_value_error_is_cli_error(prediction, tmp_path, monkeypatch, capsys):
    def reject(*args, **kwargs):
        raise ValueError("invalid bundle fixture")

    monkeypatch.setattr("myquant_contract.build_signal_bundle", reject)
    with pytest.raises(SystemExit) as exc:
        _run(prediction, tmp_path / "out", "--emit-signal-bundle")
    assert exc.value.code == 2
    assert "invalid bundle fixture" in capsys.readouterr().err


def test_legacy_manifest_failure_still_returns_success(prediction, tmp_path, monkeypatch, capsys):
    def reject(**kwargs):
        raise RuntimeError("legacy fixture failure")

    monkeypatch.setattr(edp, "write_export_manifest", reject)
    output = tmp_path / "out"
    assert _run(prediction, output, "--emit-signal-bundle") == 0
    assert _bundle(output)["rows"]
    assert "Failed to write export manifest: legacy fixture failure" in capsys.readouterr().err
