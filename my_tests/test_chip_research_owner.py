"""Synthetic migration contracts; no provider access, model fitting or PortAna run."""
import ast
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from qlib.utils import get_cls_kwargs

from my_scripts.chip_research import factor_expr as handlers
from my_scripts.chip_research import qlib_workflow as workflow

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "examples/chip_research/筹码分布因子.ipynb"
PERIODS = (("2020-01-01", "2022-12-31"), ("2023-01-01", "2023-12-31"), ("2024-01-01", "2024-12-31"))


@pytest.mark.parametrize("builder,extra,dataset", [
    (workflow.get_dataset_config, (), "DatasetH"),
    (workflow.get_tsdataset_config, (20,), "TSDatasetH"),
])
def test_dataset_config_resolves_native_handler_without_bt(builder, extra, dataset):
    config = builder("pool", *PERIODS, *extra)
    assert config["class"] == dataset
    handler = config["kwargs"]["handler"]
    cls, kwargs = get_cls_kwargs(handler)
    assert cls is handlers.Chips
    assert kwargs["fit_start_time"] == PERIODS[0][0]
    assert kwargs["fit_end_time"] == PERIODS[0][1]
    assert config["kwargs"]["segments"] == dict(zip(("train", "valid", "test"), PERIODS))


@pytest.mark.parametrize("cls,count,window", [(handlers.Chips, 12, 80), (handlers.TurnCoeffChips, 4, 60)])
def test_handler_preserves_features_label_and_processors(cls, count, window, monkeypatch):
    calls = []
    monkeypatch.setattr(handlers.DataHandlerLP, "__init__", lambda self, **kw: calls.append(kw))
    obj = cls(instruments="pool", start_time=PERIODS[0][0], end_time=PERIODS[2][1],
              fit_start_time=PERIODS[0][0], fit_end_time=PERIODS[0][1])
    config = calls[0]["data_loader"]["kwargs"]["config"]
    fields, names = config["feature"]
    assert len(fields) == len(names) == count
    assert all(field.endswith(f",{window})") for field in fields)
    assert config["label"] == (["Ref($open, -2)/Ref($open, -1) - 1"], ["LABEL0"])
    assert calls[0]["learn_processors"] == [{"class": "DropnaLabel", "kwargs": {}}]
    assert obj.get_feature_config() == (fields, names)


@pytest.mark.parametrize("model", ["transformer_ts", "transformer", "alstm", "adarnn", "tcn_ts", "gbdt"])
def test_model_config_builders_do_not_initialize_models_or_data(model, monkeypatch):
    monkeypatch.setattr(workflow, "init_instance_by_config", Mock(side_effect=AssertionError("model initialization")))
    config = workflow.MODEL_CONFIG[model]()
    assert config["class"] and config["module_path"].startswith("qlib.contrib.model.")
    assert isinstance(config["kwargs"], dict)


def test_explicit_workflow_wires_training_signals_and_portana_with_mock_ports(monkeypatch):
    model, recorder, dataset = Mock(), SimpleNamespace(info={"id": "synthetic"}), object()
    created = []
    monkeypatch.setattr(workflow, "init_instance_by_config", Mock(return_value=model))
    monkeypatch.setattr(workflow, "R", SimpleNamespace(start=Mock(return_value=nullcontext()),
        save_objects=Mock(), get_recorder=Mock(return_value=recorder)))
    def record(kind):
        def create(*args):
            value = Mock()
            created.append((kind, args, value))
            return value
        return create
    for name in ("SignalRecord", "SigAnaRecord", "PortAnaRecord"):
        monkeypatch.setattr(workflow, name, record(name))
    result = workflow.run_model(dataset, "gbdt", *PERIODS[2], model_kw={"num_boost_round": 7})
    model.fit.assert_called_once_with(dataset, save_path=None)
    assert [kind for kind, _args, _record in created] == ["SignalRecord", "SigAnaRecord", "PortAnaRecord"]
    assert created[0][1] == (model, dataset, recorder)
    config = created[2][1][1]
    assert config["strategy"]["kwargs"]["signal"] == (model, dataset)
    assert config["backtest"]["start_time"] == PERIODS[2][0]
    assert config["backtest"]["exchange_kwargs"]["trade_unit"] == 100
    assert result["recorder"] is recorder
    for _kind, _args, value in created:
        value.generate.assert_called_once_with()


def test_failed_fit_never_produces_signals_or_portana(monkeypatch):
    model = Mock()
    model.fit.side_effect = RuntimeError("synthetic fit failure")
    monkeypatch.setattr(workflow, "init_instance_by_config", Mock(return_value=model))
    monkeypatch.setattr(workflow, "R", SimpleNamespace(start=Mock(return_value=nullcontext())))
    signal = Mock(side_effect=AssertionError("signal after failed fit"))
    monkeypatch.setattr(workflow, "SignalRecord", signal)
    with pytest.raises(RuntimeError, match="fit failure"):
        workflow.run_model(object(), "gbdt", *PERIODS[2])
    signal.assert_not_called()


def test_numerical_package_import_has_no_bt_or_training_dependency(tmp_path):
    code = """
import importlib.abc, sys
class BlockSource(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in {'backtest','common','oskh_data','oskh_factors','qlib_cost','my_scripts'}:
            raise AssertionError('reverse source dependency: ' + name)
sys.meta_path.insert(0, BlockSource())
import myquant_factors
assert callable(myquant_factors.calc_dist_chips)
"""
    import os
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_notebook_keeps_historical_outputs_without_scr_or_bt_imports():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    receipt = json.loads((NOTEBOOK.parent / "migration-receipt.json").read_text(encoding="utf-8"))
    historic = [c.get("outputs", []) for c in notebook["cells"][2:] if c["cell_type"] == "code"]
    digest = hashlib.sha256(json.dumps(historic, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert digest == receipt["historical_outputs_sha256"]
    assert sum(map(len, historic)) == 57
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        text = "".join(cell["source"])
        ast.parse(text)
        assert "from scr." not in text and "MYQUANT_BT_REPO" not in text
        assert "qlib_cost" not in text
    assert notebook["metadata"]["migration"]["executed_during_migration"] is False


def test_notebook_requires_explicit_data_configuration_before_any_execution(monkeypatch):
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    code = "".join(notebook["cells"][1]["source"])
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("MYQUANT_CHIP_QLIB_URI", raising=False)
    monkeypatch.delenv("MYQUANT_CHIP_RUN_ROOT", raising=False)
    with pytest.raises(RuntimeError, match="MYQUANT_CHIP_QLIB_URI"):
        exec(compile(code, "notebook-setup", "exec"), {})
