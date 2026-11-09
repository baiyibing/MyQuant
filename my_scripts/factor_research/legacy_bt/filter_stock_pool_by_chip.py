"""MyQuant factor research CLI; paths must be configured explicitly."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from myquant_factors._runtime import configure_host
configure_host(research_root=lambda: ROOT)
from myquant_factors.research.entries.legacy_bt.filter_stock_pool_by_chip import main
if __name__ == "__main__":
    raise SystemExit(main())
