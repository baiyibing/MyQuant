# -*- coding: utf-8 -*-
"""Tests for turnover_resist_bridge (PyO3 FFI + CLI fallback)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


class TestBridgeMode:
    def test_bridge_mode_returns_valid_string(self):
        from myquant_factors.bridge.turnover_resist import bridge_mode

        mode = bridge_mode()
        assert mode in ("pyo3_ffi", "cli_fallback")

    def test_is_ffi_available_does_not_crash(self):
        from myquant_factors.bridge.turnover_resist import is_ffi_available

        result = is_ffi_available()
        assert isinstance(result, bool)


class TestCliFallback:
    @pytest.mark.parametrize("invalid_kind", ["missing", "directory"])
    def test_invalid_explicit_exe_never_uses_another_binary(self, tmp_path, monkeypatch, invalid_kind):
        from myquant_factors.bridge.turnover_resist import _find_exe

        fallback = tmp_path / "cargo/release/turnover-resist.exe"
        fallback.parent.mkdir(parents=True)
        fallback.write_text("stale alternate binary", encoding="utf-8")
        invalid = tmp_path / "explicit-exe"
        if invalid_kind == "directory":
            invalid.mkdir()
        monkeypatch.setenv("TURNOVER_RESIST_EXE", str(invalid))
        monkeypatch.setenv("CARGO_TARGET_DIR", str(tmp_path / "cargo"))
        with pytest.raises(FileNotFoundError, match="TURNOVER_RESIST_EXE") as error:
            _find_exe()
        assert str(invalid) in str(error.value)

    def test_valid_explicit_exe_has_precedence(self, tmp_path, monkeypatch):
        from myquant_factors.bridge.turnover_resist import _find_exe

        chosen = tmp_path / "selected.exe"
        chosen.write_text("selected artifact", encoding="utf-8")
        monkeypatch.setenv("TURNOVER_RESIST_EXE", str(chosen))
        assert _find_exe() == chosen

    @pytest.mark.parametrize("binary", ["turnover-resist.exe", "turnover-resist"])
    def test_no_explicit_exe_preserves_cargo_target_search(self, tmp_path, monkeypatch, binary):
        from myquant_factors.bridge.turnover_resist import _find_exe

        selected = tmp_path / "release-fast" / binary
        selected.parent.mkdir()
        selected.write_text("compiled artifact", encoding="utf-8")
        monkeypatch.delenv("TURNOVER_RESIST_EXE", raising=False)
        monkeypatch.setenv("CARGO_TARGET_DIR", str(tmp_path))
        assert _find_exe() == selected

    @pytest.mark.skipif(sys.platform != "win32", reason="turnover-resist.exe is the Windows CLI fallback")
    def test_find_exe_returns_path(self):
        from myquant_factors.bridge.turnover_resist import _find_exe

        try:
            exe = _find_exe()
        except FileNotFoundError:
            pytest.skip("turnover-resist.exe not built on this runner (set TURNOVER_RESIST_EXE)")
        assert exe.name == "turnover-resist.exe"

    def test_cli_compute_echo_fails_without_data(self):
        """CLI should fail gracefully when data_dir doesn't exist."""
        from myquant_factors.bridge.turnover_resist import _cli_compute

        with pytest.raises((RuntimeError, FileNotFoundError)):
            _cli_compute(
                date="20991231",
                data_dir="Z:/nonexistent_path_for_test",
                window=20,
                step=0.01,
                sort_by="circulating",
                free_float_policy="warn-zero",
                target_date_policy="strict",
                bb_ddof=1,
                max_grid_points=250_000,
            )




class TestBridgeRespectsPreferFfi:
    def test_prefer_ffi_false_goes_cli_directly(self, monkeypatch):
        """When prefer_ffi=False, skip FFI and go straight to CLI."""
        from myquant_factors.bridge.turnover_resist import compute_turnover_resist

        # With no data and prefer_ffi=False, should raise from CLI path
        with pytest.raises((RuntimeError, FileNotFoundError)):
            compute_turnover_resist(
                date="20991231",
                data_dir="Z:/nonexistent",
                prefer_ffi=False,
            )


class TestCliBomCsv:
    def test_cli_compute_reads_utf8_bom_stock_code(self, tmp_path, monkeypatch):
        """Rust CLI writes UTF-8 BOM CSV; bridge must keep fieldname stock_code."""
        import subprocess
        from pathlib import Path as P

        from myquant_factors.bridge import turnover_resist as tr

        date = "20260825"
        data_dir = tmp_path
        out = data_dir / f"_turnover_resist_{date}.csv"
        # Simulate Rust CLI UTF-8 BOM header (utf-8-sig write).
        out.write_text(
            "stock_code,stock_name,date,close,turnover_resistance\n"
            "000001.SZ,PingAn,20260825,10.5,0.42\n",
            encoding="utf-8-sig",
        )
        assert out.read_bytes()[:3] == b"\xef\xbb\xbf"

        monkeypatch.setattr(tr, "_find_exe", lambda: P("/fake/turnover-resist"))

        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc())

        rows = tr._cli_compute(
            date=date,
            data_dir=str(data_dir),
            window=1000,
            step=0.01,
            sort_by="circulating",
            free_float_policy="warn-zero",
            target_date_policy="strict",
            bb_ddof=1,
            max_grid_points=250_000,
        )
        assert len(rows) == 1
        assert "stock_code" in rows[0]
        assert rows[0]["stock_code"] == "000001.SZ"
        assert "\ufeffstock_code" not in rows[0]
        assert rows[0]["close"] == 10.5
        assert rows[0]["turnover_resistance"] == 0.42
