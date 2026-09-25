from pathlib import Path


def test_ci_ruff_targets_contract_only():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    ).read_text(encoding="utf-8")
    assert "ruff check myquant_contract" in workflow
    assert "ruff check my_scripts" not in workflow
    assert "ruff check qlib_scripts" not in workflow
    pytest_job = workflow.split("\n  pytest:\n", 1)[1]
    assert "pip install ruff" in pytest_job
    assert "ruff check myquant_contract" in pytest_job
