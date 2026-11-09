"""Real Qlib/LightGBM integration over an explicitly synthetic isolated provider."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd
import pytest

from my_scripts.chip_research.acceptance import prepare
from myquant_infra.artifacts.provenance import sha256_file
from myquant_infra.contracts.signal_bundle import validate_signal_bundle

ROOT = Path(__file__).resolve().parents[1]
SYMBOLS = ["SH600000", "SH600004", "SZ000001", "SZ000002"]


def build_provider(root):
    """Synthetic OHLCV only; delegate the actual provider encoding to infra."""
    from myquant_infra.adapters.qlib_data.dump_bin import DumpDataAll
    source, provider = root / "csv", root / "provider"
    source.mkdir(parents=True)
    dates = pd.bdate_range("2024-01-02", periods=200)
    t = np.arange(len(dates))
    for i, symbol in enumerate(SYMBOLS):
        close = 20 + i + 0.02 * t + (1 + 0.1 * i) * np.sin(t / (7 + i) + i)
        volume = 100000 + 20000 * (1 + np.sin(t / 11 + i))
        pd.DataFrame({
            "date": dates, "symbol": symbol, "open": close * (1 + 0.002 * np.cos(t + i)),
            "close": close, "high": close + 0.4, "low": close - 0.4,
            "volume": volume, "vol": volume, "amount": close * volume,
            "turnover_rate": 0.015 + 0.005 * np.sin(t / 9 + i), "factor": 1.,
        }).to_csv(source / f"{symbol}.csv", index=False)
    DumpDataAll(str(source), str(provider), max_workers=1,
                include_fields="open,close,high,low,volume,vol,amount,turnover_rate,factor").dump()
    return provider, dates


@pytest.fixture(scope="module")
def synthetic_provider(tmp_path_factory):
    return build_provider(tmp_path_factory.mktemp("native-chip-provider"))


@pytest.fixture
def acceptance_tmp():
    # The CLI deliberately refuses all source-checkout outputs, even ignored pytest dirs.
    with tempfile.TemporaryDirectory(prefix="myquant-chip-acceptance-") as name:
        yield Path(name).resolve()


def arguments(provider, output, dates):
    return argparse.Namespace(provider=str(provider), output=str(output), instruments=",".join(SYMBOLS),
        benchmark=SYMBOLS[0], handler="Chips", input_kind="synthetic", price_domain="none",
        train=[str(dates[90].date()), str(dates[140].date())],
        valid=[str(dates[141].date()), str(dates[160].date())],
        test=[str(dates[161].date()), str(dates[170].date())])


def test_fit_windows_purge_future_label_sessions(synthetic_provider, acceptance_tmp):
    provider, dates = synthetic_provider
    *_, segments, _files = prepare(arguments(provider, acceptance_tmp / "run", dates))
    assert segments["train"][1] == dates[138]
    assert segments["valid"][1] == dates[158]
    assert segments["test"][1] == dates[170]


@pytest.mark.parametrize("bad", ["existing", "provider", "source", "overlap", "missing", "too_long"])
def test_bad_inputs_fail_before_any_output(synthetic_provider, acceptance_tmp, bad):
    provider, dates = synthetic_provider
    args = arguments(provider, acceptance_tmp / "run", dates)
    if bad == "existing":
        Path(args.output).mkdir()
    elif bad == "provider":
        args.output = str(provider / "output")
    elif bad == "source":
        args.output = str(ROOT / "my_scripts" / "never-write-acceptance")
    elif bad == "overlap":
        args.valid = args.train
    elif bad == "missing":
        args.instruments = "SH600999,SH600004,SZ000001"
    elif bad == "too_long":
        args.test = [str(dates[161].date()), str(dates[195].date())]
    with pytest.raises((ValueError, FileNotFoundError, FileExistsError)):
        prepare(args)
    assert not (provider / "output").exists()
    assert not (ROOT / "my_scripts" / "never-write-acceptance").exists()


@pytest.mark.parametrize("handler", ["Chips", "TurnCoeffChips"])
def test_native_factor_train_backtest_and_signal_contract(synthetic_provider, acceptance_tmp, handler):
    provider, dates = synthetic_provider
    args = arguments(provider, acceptance_tmp / "run", dates)
    command = [sys.executable, "-m", "my_scripts.chip_research.acceptance", "--provider", str(provider),
        "--output", args.output, "--input-kind", "synthetic", "--handler", handler,
        "--instruments", args.instruments, "--benchmark", args.benchmark, "--price-domain", "none",
        "--train", *args.train, "--valid", *args.valid, "--test", *args.test]
    result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1"),
                            capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert result.returncode == 0, result.stdout[-2500:] + result.stderr[-6000:]
    output = Path(args.output)
    receipt = json.loads((output / "acceptance.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "PASS" and receipt["input_kind"] == "synthetic"
    assert receipt["provider_unchanged"] is True
    assert receipt["predictions"] == 4 * 10 and receipt["pool_files"] == 9
    assert receipt["rows"] == {"train": 4 * 49, "valid": 4 * 18, "test": 4 * 10}
    for relative, digest in receipt["artifact_sha256"].items():
        assert sha256_file(output / relative) == digest
    for relative, digest in receipt["input_sha256"].items():
        assert sha256_file(provider / relative) == digest
    bundle = json.loads((output / "signals/signal-bundle.json").read_text())
    validate_signal_bundle(bundle, files_root=output / "signals")
    assert bundle["availability"] == "unproven"
    assert all(row["target_session"] > row["signal_asof"] for row in bundle["rows"])
    frame = pd.read_parquet(output / "backtest.parquet")
    assert frame["cost"].sum() > 0
