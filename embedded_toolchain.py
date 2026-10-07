"""
Toolchain management facade.
Implementation is modularized in `scripts/toolchain.py`.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.toolchain import *  # noqa: F401, F403
