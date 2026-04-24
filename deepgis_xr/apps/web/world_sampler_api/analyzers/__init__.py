"""
Per-model analyzer branches for the world-sampler API.

One submodule per `model_type` value accepted by the
`/webclient/sampler/analyze-viewport` endpoint. Each submodule
exposes a single `_analyze_viewport_<model>(...)` function with the
same signature it had when they all lived inside the monolithic
`world_sampler_api.py`. That stability is intentional: the HTTP
dispatcher in `http.py` still imports them by name.

Shared plumbing (GeoJSON conversion, Grounding-DINO visualisation)
lives in `_helpers.py` because it is used by the grounding_dino and
grounded_sam branches.

The next, behaviour-preserving step is the Analyzer ABC +
`ANALYZER_REGISTRY` — an explicit registry keyed by `model_type`
that replaces the if/elif chain inside `analyze_viewport`. That
change is what unblocks the kernelcal ModelKernelSelector thread
(Thread 2 in the integration plan). It is not part of this refactor
commit because it changes the contract of what an analyzer *is*; it
lands separately after the API shape is pinned.
"""

from .sam import _analyze_viewport_sam
from .zero_shot import _analyze_viewport_zero_shot
from .mask2former import _analyze_viewport_mask2former
from .yolov8 import _analyze_viewport_yolov8
from .grounding_dino import _analyze_viewport_grounding_dino
from .grounded_sam import _analyze_viewport_grounded_sam
from .prithvi import _analyze_viewport_prithvi
from .maskrcnn_rocks import _analyze_viewport_maskrcnn_rocks
from .urban_spectral import _analyze_viewport_urban_spectral

from ._helpers import (
    _create_grounding_dino_visualization,
    _detections_to_geojson,
    _masks_to_geojson_with_contours,
)

__all__ = [
    "_analyze_viewport_sam",
    "_analyze_viewport_zero_shot",
    "_analyze_viewport_mask2former",
    "_analyze_viewport_yolov8",
    "_analyze_viewport_grounding_dino",
    "_analyze_viewport_grounded_sam",
    "_analyze_viewport_prithvi",
    "_analyze_viewport_maskrcnn_rocks",
    "_analyze_viewport_urban_spectral",
    "_create_grounding_dino_visualization",
    "_detections_to_geojson",
    "_masks_to_geojson_with_contours",
]
