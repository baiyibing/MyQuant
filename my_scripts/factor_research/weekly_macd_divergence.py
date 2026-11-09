"""MyQuant factor research CLI; no BT source dependency."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from myquant_factors._runtime import configure_host
configure_host(research_root=lambda: ROOT)
from myquant_factors.research.weekly_macd_divergence import main

if __name__ == "__main__":
    raise SystemExit(main())
