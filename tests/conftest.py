"""Pytest config: make the platform_overlay importable as `backend.*`.

The overlay mirrors the AutoGPT Platform path layout
(``backend/backend/blocks/...``) so the block's internal
``from backend.blocks.autogen_team import ...`` resolves in standalone dev
exactly as it will inside the platform.
"""

import sys
from pathlib import Path

_OVERLAY = Path(__file__).resolve().parent.parent / "platform_overlay"
if str(_OVERLAY) not in sys.path:
    sys.path.insert(0, str(_OVERLAY))
