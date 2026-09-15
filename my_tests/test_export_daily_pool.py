import json
from pathlib import Path

import pytest

import my_scripts.export_daily_pool as edp
from my_scripts.export_daily_pool import (
    DEFAULT_OUT_DIR,
    apply_neutralization,
    build_parser,
    export_daily_pool,
    load_predictions,
    main,
)


def _pred(tmp_path: Path, text: str):
    path = tmp_path / "pred.csv"
    path.write_text(text, encoding="utf-8")
    return load_predictions(path)


def test_pred_minus_one_uses_previous_prediction_and_skips_last(tmp_path):
    predictions = _pred(
        tmp_path,
        "datetime,instrument,score,label\n"
        "2026-03-02,SZ300190,2,0\n"
        "2026-03-02,SH600000,1,0\n"
        "2026-03-05,BJ920014,3,0\n"
        "2026-03-09,SZ000001,4,0\n",
    )
    out = tmp_path / "out"

    written, _ = export_daily_pool(predictions, out, topk=1)

    assert [path.name for path in written] == ["20260305.csv", "20260309.csv"]
    assert (out / "20260305.csv").read_text(encoding="utf-8") == "300190\n"
    assert (out / "20260309.csv").read_text(encoding="utf-8") == "920014\n"
    assert not (out / "20260302.csv").exists()


def test_identity_tiebreak_dedupe_illegal_and_contract_bytes(tmp_path):
    predictions = _pred(
        tmp_path,
        "datetime,instrument,score\n"
        "2026-03-02,SZ300190,9\n"
        "2026-03-02,SH600000,9\n"
        "2026-03-02,BJ920014,9\n"
        "2026-03-02,600000,8\n"
        "2026-03-02,000001,7\n"
        "2026-03-02,FOO,10\n"
        "2026-03-02,SH12,10\n"
        "2026-03-02,SZ300190X,10\n"
        "2026-03-03,NOPE,1\n",
    )
    out = tmp_path / "identity"

    written, illegal = export_daily_pool(predictions, out, asof="identity")

    assert [path.name for path in written] == ["20260302.csv"]
    assert illegal == 4
    payload = written[0].read_bytes()
    assert payload == b"920014\n600000\n300190\n000001\n"
    assert not payload.startswith(b"\xef\xbb\xbf")
    assert all(len(line) == 6 and line.isdigit() for line in payload.decode().splitlines())
    assert not (out / "20260303.csv").exists()


def test_default_asof_and_default_out_dir_are_locked():
    args = build_parser().parse_args(["--pred", "anything.csv"])
    assert args.asof == "pred_minus_one"
    assert args.out_dir == DEFAULT_OUT_DIR


def test_missing_pred_is_system_exit_with_path(tmp_path, capsys):
    missing = tmp_path / "missing.csv"
    with pytest.raises(SystemExit):
        main(["--pred", str(missing), "--out-dir", str(tmp_path / "out")])
    assert str(missing) in capsys.readouterr().err


def test_neutralize_defaults_to_off():
    args = build_parser().parse_args(["--pred", "anything.csv"])
    assert args.neutralize is None
    assert args.industry_map is None
    assert args.float_cap is None


# --- M3-D neutralize wiring -------------------------------------------------

# Industry offsets dominate the raw ranking: 银行 scores sit above 电子, so the
# raw Top1 is 600000 and the industry-demeaned Top1 is 300190.
_NEUTRALIZE_PRED = (
    "datetime,instrument,score\n"
    "2026-03-02,SH600000,10\n"
    "2026-03-02,SH600016,9\n"
    "2026-03-02,SZ300190,2\n"
    "2026-03-02,SZ000725,0\n"
)

# Size dominates the raw ranking: the largest cap has the top raw score, while
# 000004 carries the only positive alpha and wins on the size residual.
_SIZE_PRED = (
    "datetime,instrument,score\n"
    "2026-03-02,SH600519,24\n"
    "2026-03-02,SZ000001,23\n"
    "2026-03-02,SZ000002,22\n"
    "2026-03-02,SZ000003,21\n"
    "2026-03-02,SZ000004,21.5\n"
    "2026-03-02,SZ000005,19\n"
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _industry_map(tmp_path: Path) -> Path:
    return _write(
        tmp_path / "map.csv",
        "code_qlib,code_gildata,name,sw_l1\n"
        "SH600000,600000.SH,浦发银行,银行\n"
        "SH600016,600016.SH,民生银行,银行\n"
        "SZ300190,300190.SZ,维尔利,电子\n"
        "SZ000725,000725.SZ,京东方A,电子\n",
    )


def _float_cap(tmp_path: Path, *, gate_passes: bool = True) -> Path:
    caps = {
        "SH600519": 24.0,
        "SZ000001": 23.0,
        "SZ000002": 22.0,
        "SZ000003": 21.0,
        "SZ000004": 20.0,
        "SZ000005": 19.0,
    }
    # Turnover tracks cap when the derivation is sound; the blocked fixture
    # scrambles it so the daily rank correlation collapses.
    amounts = [1e11, 5e10, 2e10, 9e9, 4e9, 1e9]
    if not gate_passes:
        amounts = [4e9, 1e11, 1e9, 5e10, 2e10, 9e9]
    lines = ["datetime,instrument,log_float_cap,$amount"]
    for (code, cap), amount in zip(caps.items(), amounts):
        lines.append(f"2026-03-02,{code},{cap},{amount}")
    return _write(tmp_path / "cap.csv", "\n".join(lines) + "\n")


def _run_export(tmp_path: Path, monkeypatch, argv: list[str]) -> tuple[Path, dict]:
    monkeypatch.setattr(edp, "REPO_ROOT", tmp_path)
    out = tmp_path / "out"
    assert main(["--out-dir", str(out), "--asof", "identity", "--topk", "1", *argv]) == 0
    manifests = list((tmp_path / "manifests").glob("export_*.json"))
    assert len(manifests) == 1
    return out, json.loads(manifests[0].read_text(encoding="utf-8"))["config"]


def test_default_path_is_unchanged_and_manifest_records_no_neutralize(tmp_path, monkeypatch):
    pred = _write(tmp_path / "pred.csv", _NEUTRALIZE_PRED)

    out, config = _run_export(tmp_path, monkeypatch, ["--pred", str(pred)])

    assert (out / "20260302.csv").read_bytes() == b"600000\n"
    assert config["neutralize"] == "none"
    assert "neutralize_industry_map" not in config


def test_industry_neutralize_reranks_before_topn_and_keeps_the_byte_contract(tmp_path, monkeypatch):
    pred = _write(tmp_path / "pred.csv", _NEUTRALIZE_PRED)
    industry_map = _industry_map(tmp_path)

    out, config = _run_export(
        tmp_path,
        monkeypatch,
        ["--pred", str(pred), "--neutralize", "industry", "--industry-map", str(industry_map)],
    )

    payload = (out / "20260302.csv").read_bytes()
    # Truncation happens after neutralization: the demeaned Top1 wins the file.
    assert payload == b"300190\n"
    assert not payload.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in payload
    assert all(len(line) == 6 and line.isdigit() for line in payload.decode().splitlines())
    assert config["neutralize"] == "industry"
    assert config["neutralize_industry_map"] == str(industry_map)
    assert config["neutralize_industry_bypass_rows"] == 0


def test_industry_neutralize_counts_unmapped_names_in_the_manifest(tmp_path, monkeypatch):
    pred = _write(tmp_path / "pred.csv", _NEUTRALIZE_PRED + "2026-03-02,SZ301999,1\n")
    industry_map = _industry_map(tmp_path)

    _, config = _run_export(
        tmp_path,
        monkeypatch,
        ["--pred", str(pred), "--neutralize", "industry", "--industry-map", str(industry_map)],
    )

    assert config["neutralize_industry_bypass_rows"] == 1
    assert config["neutralize_industry_bypass_instruments"] == 1


def test_size_neutralize_runs_when_the_cap_gate_passes(tmp_path, monkeypatch):
    pred = _write(tmp_path / "pred.csv", _SIZE_PRED)
    cap = _float_cap(tmp_path)

    out, config = _run_export(
        tmp_path, monkeypatch, ["--pred", str(pred), "--neutralize", "size", "--float-cap", str(cap)]
    )

    assert (out / "20260302.csv").read_bytes() == b"000004\n"
    assert config["neutralize"] == "size"
    assert config["float_cap_gate_passed"] is True
    assert config["float_cap_gate_median_rank_corr"] == 1.0


def test_size_neutralize_is_blocked_when_the_cap_gate_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(edp, "REPO_ROOT", tmp_path)
    pred = _write(tmp_path / "pred.csv", _SIZE_PRED)
    cap = _float_cap(tmp_path, gate_passes=False)
    out = tmp_path / "out"

    with pytest.raises(SystemExit):
        main(
            [
                "--pred", str(pred),
                "--out-dir", str(out),
                "--asof", "identity",
                "--neutralize", "size",
                "--float-cap", str(cap),
            ]
        )

    assert "size neutralization blocked" in capsys.readouterr().err
    assert not out.exists()
    assert not (tmp_path / "manifests").exists()


def test_both_is_blocked_by_the_same_gate_while_industry_stays_available(tmp_path, monkeypatch):
    pred = _write(tmp_path / "pred.csv", _SIZE_PRED)
    cap = _float_cap(tmp_path, gate_passes=False)
    industry_map = _write(
        tmp_path / "map2.csv",
        "code_qlib,code_gildata,name,sw_l1\n"
        "SH600519,600519.SH,贵州茅台,食品饮料\n"
        "SZ000001,000001.SZ,平安银行,银行\n"
        "SZ000002,000002.SZ,万科A,房地产\n"
        "SZ000003,000003.SZ,某某,房地产\n"
        "SZ000004,000004.SZ,某某,银行\n"
        "SZ000005,000005.SZ,某某,银行\n",
    )
    predictions = load_predictions(pred)

    with pytest.raises(ValueError, match="size neutralization blocked"):
        apply_neutralization(
            predictions, method="both", industry_map=industry_map, float_cap=cap
        )

    frame, config = apply_neutralization(
        predictions, method="industry", industry_map=industry_map
    )
    assert config["neutralize"] == "industry"
    assert len(frame) == len(predictions)


def test_neutralize_requires_its_inputs(tmp_path):
    predictions = _pred(tmp_path, _NEUTRALIZE_PRED)
    with pytest.raises(ValueError, match="--industry-map"):
        apply_neutralization(predictions, method="industry")
    with pytest.raises(ValueError, match="--float-cap"):
        apply_neutralization(predictions, method="size")
    with pytest.raises(ValueError, match="--industry-map"):
        apply_neutralization(predictions, method="both")


def test_float_cap_input_accepts_raw_bin16_fields(tmp_path, monkeypatch):
    pred = _write(tmp_path / "pred.csv", _SIZE_PRED)
    lines = ["datetime,instrument,$close,$adfadfbasiccurhold,$amount"]
    for index, code in enumerate(
        ["SH600519", "SZ000001", "SZ000002", "SZ000003", "SZ000004", "SZ000005"]
    ):
        close = 100.0 / (index + 1)
        lines.append(f"2026-03-02,{code},{close},1e9,{close * 1e8}")
    cap = _write(tmp_path / "raw_cap.csv", "\n".join(lines) + "\n")

    _, config = _run_export(
        tmp_path, monkeypatch, ["--pred", str(pred), "--neutralize", "size", "--float-cap", str(cap)]
    )

    assert config["float_cap_gate_passed"] is True
    assert config["neutralize_size_bypass_rows"] == 0


def test_float_cap_input_without_usable_columns_is_rejected(tmp_path):
    predictions = _pred(tmp_path, _SIZE_PRED)
    cap = _write(tmp_path / "bad_cap.csv", "datetime,instrument,cap\n2026-03-02,SH600519,1\n")
    with pytest.raises(ValueError, match="log_float_cap"):
        apply_neutralization(predictions, method="size", float_cap=cap)


def test_refuses_stock_pool_output(tmp_path):
    predictions = _pred(tmp_path, "datetime,instrument,score\n2026-03-02,600000,1\n")
    forbidden = tmp_path / "stock_pool" / "nested"
    with pytest.raises(ValueError, match="stock_pool"):
        export_daily_pool(predictions, forbidden, asof="identity")
    assert not forbidden.exists()



def test_export_manifest_includes_pred_md5(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from export_daily_pool import main
    from run_manifest import load_manifest, md5_file

    pred = tmp_path / "pred.csv"
    pred.write_text(
        "datetime,instrument,score\n"
        "2026-03-02,SH600000,0.3\n"
        "2026-03-02,SH600001,0.2\n"
        "2026-03-03,SH600000,0.25\n"
        "2026-03-03,SH600001,0.15\n",
        encoding="utf-8",
    )
    out = tmp_path / "pool"
    man_dir = tmp_path / "manifests"
    monkeypatch.setattr("export_daily_pool.REPO_ROOT", tmp_path)
    # write_export_manifest uses REPO_ROOT / manifests
    rc = main(["--pred", str(pred), "--out-dir", str(out), "--topk", "1"])
    assert rc == 0
    manifests = list((tmp_path / "manifests").glob("*.json"))
    assert manifests, "expected export manifest"
    man = load_manifest(manifests[0])
    assert man["config"]["pred_md5"] == md5_file(pred)
