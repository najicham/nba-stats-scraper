# Unit tests for predictions module
import sys
from pathlib import Path

# Ensure project root is at the beginning of sys.path to avoid
# namespace conflicts with test directories
project_root = str(Path(__file__).parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
