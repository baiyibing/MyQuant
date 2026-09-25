from pathlib import Path


def test_readme_boundary():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "backtrader 回测" not in readme
    assert "Cerebro" in readme
