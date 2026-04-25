"""
Tests for `_mask_to_polygons_norm` — the cv2-backed mask vectorizer.

These are the contracts deepgis-xr's `_polygons_norm_to_geojson` is
relying on. If any of these change without the consumer being
updated, the mask overlay on the Cesium viewport will silently
regress to bounding boxes.

Run with: python -m pytest tests/test_mask_polygons.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from inference import _mask_to_polygons_norm  # noqa: E402


def test_empty_mask_yields_no_rings():
    bmask = np.zeros((50, 50), dtype=np.uint8)
    rings = _mask_to_polygons_norm(bmask)
    assert rings == []


def test_solid_rectangle_yields_one_normalized_ring():
    bmask = np.zeros((100, 200), dtype=np.uint8)
    bmask[20:80, 40:160] = 1
    rings = _mask_to_polygons_norm(bmask)

    assert len(rings) == 1
    ring = rings[0]
    # Closed ring with at least 4 distinct corners + closure point.
    assert ring[0] == ring[-1]
    assert len(ring) >= 5
    for x, y in ring:
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0
    xs = [pt[0] for pt in ring]
    ys = [pt[1] for pt in ring]
    # Expected normalized bounds for the filled rectangle.
    assert abs(min(xs) - 40 / 200) < 1e-6
    assert abs(max(xs) - 159 / 200) < 0.01
    assert abs(min(ys) - 20 / 100) < 1e-6
    assert abs(max(ys) - 79 / 100) < 0.01


def test_two_disjoint_blobs_yield_two_rings_largest_first():
    bmask = np.zeros((100, 100), dtype=np.uint8)
    bmask[10:30, 10:30] = 1   # 400 px
    bmask[50:90, 50:95] = 1   # 1800 px
    rings = _mask_to_polygons_norm(bmask)

    assert len(rings) == 2
    # Sanity: the bigger blob (bottom-right) shows up first because
    # the helper sorts rings by descending pixel area.
    big_xs = [pt[0] for pt in rings[0]]
    small_xs = [pt[0] for pt in rings[1]]
    assert max(big_xs) > max(small_xs)


def test_tiny_speck_below_min_points_is_dropped():
    bmask = np.zeros((50, 50), dtype=np.uint8)
    bmask[10, 10] = 1
    bmask[10, 11] = 1
    rings = _mask_to_polygons_norm(bmask, epsilon_px=0.5, min_points=3)
    # A 2-pixel sliver simplifies to <3 points and is filtered out.
    assert rings == []
