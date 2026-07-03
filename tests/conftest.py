# Test root conftest — shared across all test directories

import sys
from pathlib import Path

# Ensure src/ is on the path for all tests
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))