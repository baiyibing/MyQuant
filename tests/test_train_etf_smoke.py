# -*- coding: utf-8 -*-
import sys
import json
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("myquant_infra.adapters.qlib_data", reason="optional C1 infra pin")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "my_scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "my_scripts"))

from myquant_infra.adapters.qlib_data.build_etf_qlib import BuildEtfError  # noqa: E402
from train_etf_smoke import (  # noqa: E402
    acceptance_ic,
    assert_etf_provider,
    finite_corr,
    in_segment_label_mask,
    effective_fit_segments,
    persist_segment,
    prepare_artifact_output,
)
import train_etf_smoke as smoke  # noqa: E402


def test_cross_boundary_label_is_excluded():
    calendar = pd.bdate_range("2024-01-01", periods=6)
    # 段只到第 3 个交易日。T=第 2 天的 +1/+2 会落到段外。
    dates = list(calendar[:4])
    mask = in_segment_label_mask(dates, calendar, str(cast(pd.Timestamp, calendar[0]).date()), str(cast(pd.Timestamp, calendar[2]).date()))
    assert mask.tolist() == [True, False, False, False]


def test_finite_corr_rejects_empty_and_non_finite():
    assert finite_corr([1.0, np.nan], [1.0, 2.0]) == (None, 1)
    ic, n = finite_corr([1.0, 2.0, 3.0], [1.0, 2.0, 4.0])
    assert n == 3
    assert ic is not None and np.isfinite(ic)


def test_acceptance_ic_drops_cross_boundary_rows():
    calendar = pd.bdate_range("2024-01-01", periods=8)
    pred = np.arange(6, dtype="float64")
    label = pred * 2
    report = acceptance_ic(pred, label, calendar[:6], calendar, str(cast(pd.Timestamp, calendar[0]).date()), str(cast(pd.Timestamp, calendar[3]).date()))
    assert report["kept"] < report["rows"]
    assert report["n"] == report["kept"]
    assert report["ic"] is not None and np.isfinite(report["ic"])


def test_provider_name_and_alias(tmp_path: Path):
    stock = tmp_path / "my_data"
    etf = tmp_path / "my_data_etf"
    nested = stock / "my_data_etf"
    stock.mkdir()
    etf.mkdir()
    nested.mkdir()
    with pytest.raises(BuildEtfError):
        assert_etf_provider(stock, protected=(stock,))
    with pytest.raises(BuildEtfError):
        assert_etf_provider(nested, protected=(stock,))
    assert assert_etf_provider(etf, protected=(stock,))


def test_effective_segments_use_calendar_sessions_and_keep_test_nominal():
    calendar = pd.to_datetime(["2024-12-25", "2024-12-27", "2024-12-30", "2024-12-31",
        "2025-01-02", "2025-01-03", "2025-12-29", "2025-12-30", "2025-12-31",
        "2026-01-05", "2026-01-06"])
    original = dict(smoke.SEGMENTS)
    effective = effective_fit_segments(calendar)
    assert effective["train"] == (smoke.TRAIN_START, "2024-12-27")
    assert effective["valid"] == (smoke.VALID_START, "2025-12-29")
    assert effective["test"] == smoke.SEGMENTS["test"] and smoke.SEGMENTS == original
    for name in ("train", "valid"):
        dates = calendar[(calendar >= effective[name][0]) & (calendar <= effective[name][1])]
        assert in_segment_label_mask(dates, calendar, *original[name]).all()


@pytest.mark.parametrize("calendar", [[], ["2024-01-01", "2024-01-01"], ["2024-01-02", "2024-01-01"]])
def test_effective_segments_reject_invalid_calendar(calendar):
    with pytest.raises(BuildEtfError, match="calendar"):
        effective_fit_segments(calendar)


def test_effective_segments_reject_empty_fit_labels():
    with pytest.raises(BuildEtfError, match="no in-segment fit labels"):
        effective_fit_segments(pd.to_datetime(["2024-12-30", "2024-12-31", "2025-01-02"]))


def test_artifact_masks_roundtrip_and_independent_ic(tmp_path):
    calendar = pd.bdate_range("2024-12-20", "2025-01-06")
    dates = pd.to_datetime(["2024-12-20", "2024-12-23", "2024-12-24", "2024-12-30", "2024-12-31"])
    frame = pd.DataFrame({"pred": [1., 2., np.nan, 4., 5.], "label": [1., 3., 4., 5., 6.]},
        index=pd.MultiIndex.from_product([dates, ["SH510300"]], names=["datetime", "instrument"]))
    report = acceptance_ic(frame["pred"], frame["label"], dates, calendar, *smoke.SEGMENTS["train"])
    record = persist_segment(tmp_path, "lgb", "train", frame, calendar, report)
    restored = pd.read_parquet(tmp_path / record["path"])
    assert restored["accepted"].tolist() == [True, True, False, False, False]
    accepted = restored.loc[restored["accepted"]]
    assert len(accepted) == report["n"] == 2
    assert accepted["pred"].corr(accepted["label"]) == pytest.approx(report["ic"])
    assert smoke.file_sha256(tmp_path / record["path"]) == record["sha256"]
    pd.testing.assert_frame_equal(restored[["pred", "label"]], frame)


def test_artifact_output_rejects_provider_overlap_and_stale_receipt(tmp_path):
    provider = tmp_path / "my_data_etf"
    provider.mkdir()
    with pytest.raises(BuildEtfError):
        prepare_artifact_output(provider / "outputs", provider)
    stale = tmp_path / "run"
    stale.mkdir()
    (stale / "acceptance.json").write_text('{"status":"PASS"}')
    with pytest.raises(BuildEtfError, match="fresh directory"):
        prepare_artifact_output(stale, provider)
    assert json.loads((stale / "acceptance.json").read_text())["status"] == "PASS"


@pytest.mark.parametrize("write_failure", [False, True])
def test_main_wires_purged_fit_segments_and_artifact_failure_is_not_success(monkeypatch, tmp_path, write_failure):
    calendar = pd.to_datetime(["2020-01-02", "2020-01-03", "2024-12-27", "2024-12-30", "2024-12-31",
        "2025-01-02", "2025-01-03", "2025-12-29", "2025-12-30", "2025-12-31",
        "2026-01-05", "2026-01-06", "2026-01-07", "2026-10-09", "2026-10-12", "2026-10-13"])
    provider = tmp_path / "my_data_etf"
    (provider / "calendars").mkdir(parents=True)
    (provider / "instruments").mkdir()
    (provider / "calendars/day.txt").write_text("\n".join(str(x.date()) for x in calendar) + "\n")
    for name in ("all", "etf_full"):
        (provider / f"instruments/{name}.txt").write_text("SH510300 2020-01-02 2026-10-13\n")
    captured = {}

    class Dataset:
        def __init__(self, handler, segments):
            self.handler, self.segments = handler, segments
            captured["segments"] = segments

        def prepare(self, segment, **_kwargs):
            start, end = self.segments[segment]
            dates = calendar[(calendar >= start) & (calendar <= end)]
            index = pd.MultiIndex.from_product([dates, ["SH510300"]], names=["datetime", "instrument"])
            return pd.DataFrame({"LABEL0": np.arange(len(index), dtype=float)}, index=index)

    class Model:
        def fit(self, dataset):
            captured["fit_called"] = True
            for segment in ("train", "valid"):
                labels = dataset.prepare(segment)
                dates = smoke._dates_of(labels.index)
                assert in_segment_label_mask(dates, calendar, *smoke.SEGMENTS[segment]).all()

        def predict(self, dataset, segment):
            labels = dataset.prepare(segment)
            return pd.Series(np.arange(len(labels), dtype=float), index=labels.index)

    handler = SimpleNamespace(infer_processors=[], learn_processors=[], get_label_config=lambda: smoke.LABEL_EXPR)
    close = pd.DataFrame({"$close": 1.0},
        index=pd.MultiIndex.from_product([["SH510300"], calendar], names=["instrument", "datetime"]))
    fake_d = SimpleNamespace(calendar=lambda **_k: calendar, instruments=lambda **_k: "etf_full", features=lambda *_a, **_k: close)
    modules = {name: ModuleType(name) for name in ("qlib", "qlib.constant", "qlib.data", "qlib.data.dataset",
        "qlib.data.dataset.handler", "qlib.utils", "qlib.workflow", "joblib")}
    setattr(modules["qlib"], "init", lambda **_k: None)
    setattr(modules["qlib.constant"], "REG_CN", "cn")
    setattr(modules["qlib.data"], "D", fake_d)
    setattr(modules["qlib.data.dataset"], "DatasetH", Dataset)
    setattr(modules["qlib.data.dataset.handler"], "DataHandlerLP", SimpleNamespace(DK_L="learn", DK_I="infer"))
    setattr(modules["qlib.utils"], "init_instance_by_config", lambda _config: handler)
    setattr(modules["qlib.workflow"], "R", SimpleNamespace(start=lambda **_k: nullcontext(), get_recorder=lambda: SimpleNamespace(id="offline")))
    setattr(modules["joblib"], "parallel_backend", lambda *_a: nullcontext())
    for name, value in modules.items():
        monkeypatch.setitem(sys.modules, name, value)
    monkeypatch.setattr(smoke, "build_named_model", lambda *_a: Model())
    if write_failure:
        monkeypatch.setattr(pd.DataFrame, "to_parquet", lambda *_a, **_k: (_ for _ in ()).throw(OSError("write failed")))
    out = tmp_path / "run"
    rc = smoke.main(["--qlib-dir", str(provider), "--out-dir", str(out), "--models", "lgb", "--write-acceptance-artifacts"])
    receipt = json.loads((out / "acceptance.json").read_text(encoding="utf-8"))
    assert captured["fit_called"] and captured["segments"] == effective_fit_segments(calendar)
    assert rc == (2 if write_failure else 0)
    assert receipt["status"] == ("FAIL" if write_failure else "PASS")
    assert receipt["models"]["lgb"]["status"] == receipt["status"]
    if not write_failure:
        assert set(receipt["models"]["lgb"]["segments"]) == set(smoke.SEGMENTS)
        assert receipt["mask_bounds"] == "nominal segments"
