"""
Core state and helpers for the world-sampler API.

Moved out of the legacy module in the Tier C refactor. This module owns:

1. The process-global `WorldSampler` singleton. Yes, it is a module
   global — parallel to the original implementation, and still a
   known limitation (no per-session isolation, no thread safety). The
   production story (Django cache, DB-backed session state) is still
   on the roadmap and unchanged by this refactor; see the Tier C entry
   in `notes/2026-04-22-deepgis-xr-refactoring.md`.

2. `get_or_create_sampler(session_id)` — lazy lookup.

3. `reset_global_sampler(sampler)` — new helper. The legacy module
   mutated the global via `global _global_sampler` inside its
   `initialize_sampler` HTTP handler. Now that the handler lives in
   a different submodule (`http.py`), it mutates the global through
   this function so the assignment lands on *this* module's
   `_global_sampler`, not on a local binding in `http.py`. The old
   name (`_global_sampler`) is still re-exported from the package's
   `__init__.py` so existing admin-shell probes continue to work.

4. `altitude_to_zoom_level(altitude)` — pure helper used by
   analyze_viewport (lifted out of the HTTP module so it stays
   importable by test code without Django request plumbing).
"""

import math
from typing import Optional

from ..world_sampler import WorldSampler


# Global sampler instance (in production, use Django cache or database)
_global_sampler: Optional[WorldSampler] = None


def get_or_create_sampler(session_id: str = 'default') -> WorldSampler:
    """Get or create a sampler instance for a session"""
    global _global_sampler
    
    # In production, store per-session in cache/database
    # For now, use a single global instance
    if _global_sampler is None:
        _global_sampler = WorldSampler(
            num_points=1000,
            initialization='gaussian_mixture',
            seed=None  # Random seed
        )
    
    return _global_sampler


def reset_global_sampler(sampler: WorldSampler) -> WorldSampler:
    """
    Replace the process-global sampler with `sampler` and return it.

    Used by `http.initialize_sampler` when a client POSTs a new
    initialization config. Kept as a function so the assignment binds
    to *this* module's `_global_sampler` regardless of which module
    calls it.
    """
    global _global_sampler
    _global_sampler = sampler
    return _global_sampler


def altitude_to_zoom_level(altitude: float) -> int:
    """
    Convert Cesium camera altitude to approximate zoom level.
    Cesium zoom levels roughly follow: altitude = 40075000 / (2^zoom)
    """
    if altitude <= 0:
        return 28  # Maximum zoom
    zoom = math.log2(40075000 / altitude)
    return max(0, min(28, int(round(zoom))))
