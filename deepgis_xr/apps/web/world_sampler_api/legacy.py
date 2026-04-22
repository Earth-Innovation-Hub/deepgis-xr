"""
Tombstone for the original world_sampler_api.py.

Everything that used to live here has been relocated:

    get_or_create_sampler       -> .core
    altitude_to_zoom_level      -> .core
    _global_sampler             -> .core
    reset_global_sampler        -> .core (new, replaces module-global mutation)

    initialize_sampler          -> .http
    sample_locations            -> .http
    update_distribution         -> .http
    query_region                -> .http
    get_statistics              -> .http
    reset_sampler               -> .http
    get_sample_history          -> .http
    get_scored_locations        -> .http
    analyze_viewport            -> .http

    _analyze_viewport_sam             -> .analyzers.sam
    _analyze_viewport_zero_shot       -> .analyzers.zero_shot
    _analyze_viewport_mask2former     -> .analyzers.mask2former
    _analyze_viewport_yolov8          -> .analyzers.yolov8
    _analyze_viewport_grounding_dino  -> .analyzers.grounding_dino
    _analyze_viewport_grounded_sam    -> .analyzers.grounded_sam
    _analyze_viewport_prithvi         -> .analyzers.prithvi

    _create_grounding_dino_visualization  -> .analyzers._helpers
    _detections_to_geojson                -> .analyzers._helpers
    _masks_to_geojson_with_contours       -> .analyzers._helpers

This file is kept on-disk for one more cycle so any stray
`from deepgis_xr.apps.web.world_sampler_api.legacy import ...`
import in a notebook or external tool fails loudly rather than
silently returning stale code. The package's `__init__.py`
re-exports every public name; prefer that entry point.

It is scheduled for deletion after the Tier-C branch is reviewed,
merged, and the main/dev branches have had one deploy cycle without
any consumer complaining.
"""

from .core import (  # noqa: F401  re-exports
    _global_sampler,
    altitude_to_zoom_level,
    get_or_create_sampler,
    reset_global_sampler,
)
from .http import (  # noqa: F401  re-exports
    analyze_viewport,
    get_sample_history,
    get_scored_locations,
    get_statistics,
    initialize_sampler,
    query_region,
    reset_sampler,
    sample_locations,
    update_distribution,
)
from .analyzers import (  # noqa: F401  re-exports
    _analyze_viewport_grounded_sam,
    _analyze_viewport_grounding_dino,
    _analyze_viewport_mask2former,
    _analyze_viewport_prithvi,
    _analyze_viewport_sam,
    _analyze_viewport_yolov8,
    _analyze_viewport_zero_shot,
    _create_grounding_dino_visualization,
    _detections_to_geojson,
    _masks_to_geojson_with_contours,
)
