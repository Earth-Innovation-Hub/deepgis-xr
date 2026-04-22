"""
deepgis_xr.apps.web.world_sampler_api — package form.

Previously this was a single 2 575-line module. It is being split into
focused submodules as part of the Tier-C refactor (see
`notes/2026-04-22-deepgis-xr-refactoring.md` in the integration
manuscript workspace). The motivation is unblocking the kernelcal
Thread 1 (MaxCal World Sampler) and Thread 2 (Model-Kernel Selector)
work: both need to plug into the analyzer branches without wading
through the 2 500 lines of unrelated HTTP handling and ML scaffolding.

This `__init__.py` re-exports every public name that `urls.py` routes
to, so `from deepgis_xr.apps.web import world_sampler_api;
world_sampler_api.foo` continues to work unchanged while functions
migrate out of `legacy.py` into focused submodules.

Migration order (commits land in this order):
    1. Scaffold                                   (this commit)
    2. core helpers                               → core.py
    3. HTTP handlers                              → http.py
    4. Per-model analyzers + shared helpers       → analyzers/
    [deferred] Analyzer ABC + ANALYZER_REGISTRY   → analyzers/base.py
               + dispatch from http.py. This is a behavior-preserving
               design change, not a move, and lands separately once the
               API contract for kernelcal-backed analyzers is pinned.

As each submodule is added, its names are imported here and removed
from the explicit import list against legacy. Nothing outside the
`world_sampler_api/` package should need to change.
"""

# fmt: off
from .core import (
    get_or_create_sampler,
    altitude_to_zoom_level,
    reset_global_sampler,
    # module-global sampler (kept re-exported so external probes — e.g.
    # admin shells — can still see it by name; real callers should go
    # through get_or_create_sampler() / reset_global_sampler())
    _global_sampler,
)

from .http import (
    # HTTP handlers (9 endpoints wired in apps/web/urls.py)
    initialize_sampler, sample_locations, update_distribution,
    query_region, get_statistics, reset_sampler,
    get_sample_history, get_scored_locations, analyze_viewport,
)

from .legacy import (
    # per-model analyzer branches
    _analyze_viewport_sam,
    _analyze_viewport_zero_shot,
    _analyze_viewport_mask2former,
    _analyze_viewport_yolov8,
    _analyze_viewport_grounding_dino,
    _analyze_viewport_grounded_sam,
    _analyze_viewport_prithvi,

    # shared analyzer helpers (grounding_dino + grounded_sam)
    _create_grounding_dino_visualization,
    _detections_to_geojson,
    _masks_to_geojson_with_contours,
)
# fmt: on

__all__ = [
    "get_or_create_sampler",
    "altitude_to_zoom_level",
    "initialize_sampler",
    "sample_locations",
    "update_distribution",
    "query_region",
    "get_statistics",
    "reset_sampler",
    "get_sample_history",
    "get_scored_locations",
    "analyze_viewport",
]
