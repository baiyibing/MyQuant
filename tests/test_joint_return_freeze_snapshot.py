"""Data-free assembler checks; all section files are synthetic pytest temporaries."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from my_scripts import joint_return_freeze_snapshot as freeze
from my_scripts.joint_return_contract import (
    CANDIDATE_RECORDER, ContractError, canonical_bytes, content_hash, load_snapshot,
    raw_hash, validate_snapshot,
)
from my_scripts.joint_return_portfolio import build_portfolio
from test_joint_return_portfolio import snapshot  # reuse the existing synthetic fixture


def write_json(path, value):
    path.write_bytes(canonical_bytes(value) + b"\n")


@pytest.fixture
def bundle(snapshot, tmp_path):
    paths = {name: tmp_path / f"{name}.json" for name in (*freeze.SECTIONS, "metadata")}
    paths["output"] = tmp_path / "out" / "frozen.json"
    for name in freeze.SECTIONS:
        # Deliberately noncanonical source bytes: raw and content hashes differ.
        raw = json.dumps(snapshot[name], ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        paths[name].write_bytes(raw)
        snapshot["metadata"]["inputs"][name].update(
            uri=str(paths[name]), raw_sha256=raw_hash(raw), content_sha256=content_hash(snapshot[name]))
    write_json(paths["metadata"], snapshot["metadata"])
    return paths


def argv(bundle):
    return [arg for name, path in bundle.items() for arg in (f"--{name.replace('_', '-')}", str(path))]


def mutate(bundle, section, change):
    value = json.loads(bundle[section].read_bytes())
    change(value)
    write_json(bundle[section], value)
    if section != "metadata":
        metadata = json.loads(bundle["metadata"].read_bytes())
        metadata["inputs"][section].update(raw_sha256=raw_hash(bundle[section].read_bytes()),
                                           content_sha256=content_hash(value))
        write_json(bundle["metadata"], metadata)


def assert_blocked(bundle, capsys, match, *, args=None):
    assert freeze.main(argv(bundle) if args is None else args) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] in {"INPUT_BLOCKED", "PAIR_INVALID", "SEMANTICS_BLOCKED", "OUTPUT_BLOCKED"}
    assert match in result["detail"]
    assert "snapshot" not in result
    assert not bundle["output"].exists()
    assert not bundle["output"].parent.exists()


def test_assemble_preserves_explicit_sections_and_verifies_both_hashes(bundle, capsys):
    before = {name: bundle[name].read_bytes() for name in (*freeze.SECTIONS, "metadata")}
    assert freeze.main(argv(bundle)) == 0
    manifest = json.loads(capsys.readouterr().out)
    assembled, source = load_snapshot(bundle["output"])
    validate_snapshot(assembled)
    assert assembled["kind"] == "frozen"
    assert manifest["status"] == "FROZEN_SNAPSHOT_ASSEMBLED"
    assert manifest["snapshot"] == source
    assert source["raw_verified"] is True
    assert source["raw_sha256"] == raw_hash(bundle["output"].read_bytes())
    assert source["content_sha256"] == content_hash(assembled)
    assert source["raw_sha256"] != source["content_sha256"]
    assert manifest["metadata_source"]["raw_sha256"] == raw_hash(before["metadata"])
    assert manifest["input_raw_hashes_verified"] is True
    assert manifest["input_status"] == "INPUT_BLOCKED"
    assert manifest["execution_status"] == manifest["portfolio_status"] == "NOT_RUN"
    assert manifest["real_input_blockers"]
    for name in freeze.SECTIONS:
        assert assembled[name] == json.loads(before[name])
        assert manifest["inputs"][name]["raw_verified"] is True
        assert manifest["inputs"][name]["raw_sha256"] == raw_hash(before[name])
        assert manifest["inputs"][name]["content_sha256"] == content_hash(assembled[name])
    assert assembled["metadata"] == json.loads(before["metadata"])
    assert all(bundle[name].read_bytes() == raw for name, raw in before.items())
    first = bundle["output"].read_bytes()
    bundle["output"] = bundle["output"].with_name("second.json")
    assert freeze.main(argv(bundle)) == 0
    assert bundle["output"].read_bytes() == first
    # Assembly is not a synthetic escape hatch through the frozen P-REF gate.
    with pytest.raises(ContractError, match="MQ-PJSON reference content drift"):
        build_portfolio(assembled)


@pytest.mark.parametrize("section", (*freeze.SECTIONS, "metadata"))
def test_missing_explicit_file_blocks_without_output(bundle, capsys, section):
    bundle[section].unlink()
    assert_blocked(bundle, capsys, "declared input unavailable")


@pytest.mark.parametrize("section", (*freeze.SECTIONS, "metadata"))
def test_omitted_cli_input_reports_input_blocked(bundle, capsys, section):
    args = argv({name: path for name, path in bundle.items() if name != section})
    assert_blocked(bundle, capsys, "required", args=args)


@pytest.mark.parametrize("section", freeze.SECTIONS)
def test_raw_only_drift_is_rejected_even_when_json_content_is_unchanged(bundle, capsys, section):
    bundle[section].write_bytes(bundle[section].read_bytes() + b" \n")
    assert_blocked(bundle, capsys, f"{section} raw_sha256 drift")


@pytest.mark.parametrize("hash_key", ("raw_sha256", "content_sha256"))
def test_declared_hash_drift_is_not_silently_resealed(bundle, capsys, hash_key):
    mutate(bundle, "metadata", lambda m: m["inputs"]["plans"].update({hash_key: "0" * 64}))
    assert_blocked(bundle, capsys, f"plans {hash_key} drift")


@pytest.mark.parametrize("change,match", [
    (lambda m: m.pop("fees"), "missing"),
    (lambda m: m["inputs"]["plans"].pop("coverage"), "missing"),
    (lambda m: m["inputs"]["plans"].update(version=""), "empty source"),
    (lambda m: m.update(contract_hash="0" * 64), "contract hash drift"),
    (lambda m: m["implementation_bases"].update(MQ="0" * 40), "implementation base drift"),
    (lambda m: m["code_shas"].update(MQ="short"), "invalid full hash"),
    (lambda m: m.update(sidecar_sha256="0" * 64), "sidecar hash mismatch"),
    (lambda m: m.update(pred_recorder_id="8a061ea4"), "full recorder mismatch"),
    (lambda m: m.update(candidate_recorder_id="0" * 32), "full recorder mismatch"),
    (lambda m: m.update(pred_recorder_id=CANDIDATE_RECORDER), "full recorder mismatch"),
    (lambda m: m["strategy"].update(topk=0), "topk must be a positive integer"),
    (lambda m: m["strategy"].update(n_drop=11), "n_drop must be an integer"),
    (lambda m: m["strategy"].update(source="PortAna_positions"), "backtest rule intents required"),
    (lambda m: m["strategy"].update(eligibility_rules={}), "eligibility rules missing"),
    (lambda m: m["inputs"]["scores"].update(recorder_id=CANDIDATE_RECORDER), "control recorder"),
    (lambda m: m["inputs"]["scores"].update(version=CANDIDATE_RECORDER), "candidate score source"),
])
def test_metadata_drift_is_rejected(bundle, capsys, change, match):
    mutate(bundle, "metadata", change)
    assert_blocked(bundle, capsys, match)


@pytest.mark.parametrize("section,change,match", [
    ("plans", lambda p: p.clear(), "backtest rule plans missing"),
    ("plans", lambda p: p.pop(), "missing/extra arm-days"),
    ("plans", lambda p: p.append(p[0]), "duplicate daily arm plan"),
    ("plans", lambda p: p[0].update(source="PortAna_positions"), "cannot reconstruct intent"),
    ("plans", lambda p: p[0].pop("source"), "missing"),
    ("plans", lambda p: p[0]["buy_candidates"][0].pop("original_target_quantity"), "missing"),
    ("plans", lambda p: p[0].update(corporate_actions=[{"factor": 2}]), "company-action mapping"),
    ("scores", lambda s: s[0].update(candidate_score=99), "candidate score is forbidden"),
    ("scores", lambda s: s[0].update(source_version=CANDIDATE_RECORDER), "candidate score source"),
    ("scores", lambda s: s[0].update(recorder_id=CANDIDATE_RECORDER), "candidate score source"),
    ("initial_state", lambda s: s.pop("cash"), "missing"),
    ("pref", lambda p: p.pop("expected"), "missing"),
])
def test_invalid_sections_fail_even_with_matching_declared_hashes(bundle, capsys, section, change, match):
    mutate(bundle, section, change)
    assert_blocked(bundle, capsys, match)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}',
                                  b'\xef\xbb\xbf{}', b'\0', b'\xff', b'[]'])
def test_invalid_metadata_json_fails_closed(bundle, capsys, raw):
    bundle["metadata"].write_bytes(raw)
    assert_blocked(bundle, capsys, "")


def test_only_explicit_paths_and_fixed_contract_are_read(bundle, capsys, monkeypatch):
    contract = Path(freeze.__file__).resolve().parents[1] / "docs/reviews/joint-return-v1/contract.md"
    allowed = {*bundle.values(), contract}
    read_bytes = Path.read_bytes
    reads = []

    def checked_read(path):
        assert path in allowed, f"undeclared read: {path}"
        reads.append(path)
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", checked_read)
    assert freeze.main(argv(bundle)) == 0
    assert set(reads) == allowed
    capsys.readouterr()


def test_declared_uri_never_redirects_the_cli_path(bundle, capsys, monkeypatch):
    mutate(bundle, "metadata", lambda m: m["inputs"]["scores"].update(uri="/undeclared/candidate.json"))
    read_bytes = Path.read_bytes

    def checked_read(path):
        assert str(path) != "/undeclared/candidate.json"
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", checked_read)
    assert_blocked(bundle, capsys, "uri differs from explicit path")


def test_existing_output_is_never_overwritten(bundle, capsys):
    bundle["output"].parent.mkdir()
    bundle["output"].write_bytes(b"immutable prior output\n")
    assert freeze.main(argv(bundle)) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "OUTPUT_BLOCKED"
    assert bundle["output"].read_bytes() == b"immutable prior output\n"


def test_output_cannot_replace_an_input(bundle, capsys):
    bundle["output"] = bundle["plans"]
    before = bundle["plans"].read_bytes()
    assert freeze.main(argv(bundle)) == 2
    assert "output must not replace" in json.loads(capsys.readouterr().out)["detail"]
    assert bundle["plans"].read_bytes() == before


def test_failed_write_removes_partial_output(bundle, capsys, monkeypatch):
    real_open = Path.open

    class FailedWrite:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def write(self, data):
            self.stream.write(data[:10])
            raise OSError("injected disk full")

        def __exit__(self, *args):
            self.stream.close()

    def open_file(path, *args, **kwargs):
        stream = real_open(path, *args, **kwargs)
        return FailedWrite(stream) if path == bundle["output"] and args == ("xb",) else stream

    monkeypatch.setattr(Path, "open", open_file)
    assert freeze.main(argv(bundle)) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "OUTPUT_BLOCKED" and "disk full" in result["detail"]
    assert not bundle["output"].exists()


def test_failed_readback_removes_new_output(bundle, capsys, monkeypatch):
    def failed_readback(path):
        raise ContractError("PAIR_INVALID", "injected readback failure")

    monkeypatch.setattr(freeze, "load_snapshot", failed_readback)
    assert freeze.main(argv(bundle)) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "PAIR_INVALID"
    assert not bundle["output"].exists()


def test_module_cli_and_import_fence_are_data_free(bundle):
    script = """
import sys
import my_scripts.joint_return_freeze_snapshot
for name in ('qlib', 'host_env', 'backtrader', 'mlflow', 'data_root', 'analysis_export', 'numpy'):
    assert name not in sys.modules, name
"""
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)
    command = [sys.executable, "-m", "my_scripts.joint_return_freeze_snapshot"]
    help_result = subprocess.run([*command, "--help"], check=True, capture_output=True, text=True)
    assert "--plans" in help_result.stdout and "--metadata" in help_result.stdout
    result = subprocess.run([*command, *argv(bundle)], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)["snapshot"]["uri"] == str(bundle["output"])
