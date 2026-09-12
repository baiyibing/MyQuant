from pathlib import Path

import pytest

from my_scripts.export_daily_pool import (
    DEFAULT_OUT_DIR,
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


def test_refuses_stock_pool_output(tmp_path):
    predictions = _pred(tmp_path, "datetime,instrument,score\n2026-03-02,600000,1\n")
    forbidden = tmp_path / "stock_pool" / "nested"
    with pytest.raises(ValueError, match="stock_pool"):
        export_daily_pool(predictions, forbidden, asof="identity")
    assert not forbidden.exists()
