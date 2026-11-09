"""MyQuant factor research CLI; data roots remain explicit."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from myquant_factors._runtime import configure_host
configure_host(research_root=lambda: ROOT)
from myquant_factors.research.entries.gates.verify_minute_chip import main

if __name__ == "__main__":
    raise SystemExit(main())
