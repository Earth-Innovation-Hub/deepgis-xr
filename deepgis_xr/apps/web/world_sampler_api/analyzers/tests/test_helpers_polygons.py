"""
Unit tests for `_polygons_norm_to_geojson`.

The helper is intentionally pure (no Django, no I/O) so we exercise it
directly without spinning up an app context. The behaviours we lock
in here are the ones the maskrcnn-rocks pipeline depends on:

  1. When a detection ships `mask_polygons_norm`, the resulting
     feature is a Polygon whose exterior ring matches that data
     (with closure enforced) and `has_mask` is True.
  2. Multiple rings round-trip in `[exterior, hole, ...]` order.
  3. Detections without polygons fall back to a normalized bbox
     rectangle and `has_mask` is False.
  4. Degenerate ring data (fewer than 3 distinct points) is treated
     as no-polygon and falls through to the bbox path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
HELPERS = HERE.parent / "_helpers.py"

spec = importlib.util.spec_from_file_location(
    "world_sampler_api_helpers_under_test", HELPERS
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)
_polygons_norm_to_geojson = mod._polygons_norm_to_geojson


def _make_det(detection_id, polygons=None, bbox=None, **extra):
    det = {
        "detection_id": detection_id,
        "class_name": "rock",
        "confidence": 0.9,
        "bbox": bbox if bbox is not None else [10.0, 20.0, 60.0, 80.0],
    }
    if polygons is not None:
        det["mask_polygons_norm"] = polygons
    det.update(extra)
    return det


def test_polygon_path_emits_real_mask_geometry():
    ring = [
        [0.10, 0.10], [0.40, 0.10], [0.40, 0.40], [0.10, 0.40], [0.10, 0.10],
    ]
    det = _make_det(1, polygons=[ring])

    fc = _polygons_norm_to_geojson([det], image_width=100, image_height=200)

    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 1
    f = fc["features"][0]
    assert f["geometry"]["type"] == "Polygon"
    assert f["geometry"]["coordinates"] == [ring]
    assert f["properties"]["has_mask"] is True
    assert f["properties"]["detection_id"] == 1
    assert f["properties"]["category"] == "rock"


def test_polygon_path_closes_ring_when_caller_forgot():
    open_ring = [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]]
    det = _make_det(2, polygons=[open_ring])

    fc = _polygons_norm_to_geojson([det], 100, 100)

    coords = fc["features"][0]["geometry"]["coordinates"]
    assert len(coords) == 1
    assert coords[0][0] == coords[0][-1]
    assert len(coords[0]) == len(open_ring) + 1


def test_multiple_rings_round_trip_as_exterior_then_holes():
    exterior = [
        [0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0],
    ]
    hole = [
        [0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6], [0.4, 0.4],
    ]
    det = _make_det(3, polygons=[exterior, hole])

    fc = _polygons_norm_to_geojson([det], 100, 100)

    coords = fc["features"][0]["geometry"]["coordinates"]
    assert coords == [exterior, hole]
    assert fc["features"][0]["properties"]["has_mask"] is True


def test_falls_back_to_normalized_bbox_when_no_polygons():
    det = _make_det(4, polygons=None, bbox=[20.0, 40.0, 60.0, 80.0])

    fc = _polygons_norm_to_geojson([det], image_width=100, image_height=200)

    f = fc["features"][0]
    assert f["properties"]["has_mask"] is False
    expected = [[
        [0.20, 0.20], [0.60, 0.20], [0.60, 0.40],
        [0.20, 0.40], [0.20, 0.20],
    ]]
    assert f["geometry"]["coordinates"] == expected
    # bbox_pixels is the original pixel-space rectangle, untouched.
    assert f["properties"]["bbox_pixels"] == [20.0, 40.0, 60.0, 80.0]


def test_degenerate_polygons_fall_through_to_bbox():
    det = _make_det(5, polygons=[[[0.1, 0.1], [0.2, 0.2]]])

    fc = _polygons_norm_to_geojson([det], 100, 100)

    f = fc["features"][0]
    assert f["properties"]["has_mask"] is False
    coords = f["geometry"]["coordinates"]
    assert len(coords) == 1
    # bbox-derived rectangle has 5 vertices (closed).
    assert len(coords[0]) == 5


def test_optional_area_propagates_when_present():
    det = _make_det(6, polygons=[[[0.0, 0.0], [0.4, 0.0], [0.4, 0.4], [0.0, 0.0]]],
                    area=12345.0)

    fc = _polygons_norm_to_geojson([det], 100, 100)

    assert fc["features"][0]["properties"]["area"] == 12345.0
