"""
Unit-level sanity tests for the registry filename parser.  No GPU / no model
loading required.  Run with: python -m pytest tests/
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from registry import discover, pick_default  # noqa: E402


def _touch(path: Path, size: int = 8) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)


def test_bishop_hero_and_ablations_discovered(tmp_path: Path) -> None:
    root = tmp_path / "maskrcnn"
    _touch(root / "terrestrial/bishop_jezero_field/epoch_0004.param")
    _touch(root / "terrestrial/bishop_jezero_field/ablations/tl/bishop_tl_rgb_e0023.param")
    _touch(root / "terrestrial/bishop_jezero_field/ablations/tl/bishop_tl_rgbd1_e0023.param")
    _touch(root / "terrestrial/bishop_jezero_field/ablations/ntl/bishop_ntl_mult_d1_e0049.param")
    _touch(root / "terrestrial/gobabeb_namib/epoch_0011.param")
    _touch(root / "terrestrial/tornado/detector_eureka_aug_bin_e0031.param")

    entries = discover(str(root))
    ids = set(entries)

    assert "bishop_hero_e0004" in ids
    assert "bishop_tl_rgb_e0023" in ids
    assert "bishop_tl_rgbd1_e0023" in ids
    assert "bishop_ntl_mult_d1_e0049" in ids
    assert "gobabeb_hero_e0011" in ids
    assert any("eureka" in i for i in ids)

    bishop = entries["bishop_tl_rgbd1_e0023"]
    assert bishop.family == "bishop"
    assert "rgbd1" in bishop.variant
    assert bishop.declared_channels == 4
    assert "tl" in bishop.tags

    mult = entries["bishop_ntl_mult_d1_e0049"]
    assert mult.declared_channels == 9  # "mult_d1" -> 9 per hints

    assert pick_default(entries, None) == "bishop_hero_e0004"
    assert pick_default(entries, "gobabeb_hero_e0011") == "gobabeb_hero_e0011"
