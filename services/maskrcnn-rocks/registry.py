"""
registry.py — discover available rock Mask R-CNN checkpoints at startup.

On container start we walk ``WEIGHTS_ROOT`` (bind-mounted to the canonical
archive at ``/mnt/22tb-hdd/maskrcnn`` on tesseract) and build an id → metadata
map.  The registry drives:

  * ``GET  /api/models``       — lists every checkpoint the container can load
  * ``POST /api/predict``      — ``model_id`` selects which checkpoint to use

Naming of registry ids follows
    ``<family>_<variant>_<epoch>``
e.g.
    ``bishop_hero_e0004``
    ``bishop_tl_rgb_e0023``
    ``bishop_ntl_mult_d1_e0049``
    ``gobabeb_hero_e0011``
    ``gobabeb_rock_tl_rgbdem_e0039``
    ``tornado_eureka_aug_bin_e0031``

Variant channel counts are *declared* from filename hints for documentation,
but the *authoritative* channel count is read from each checkpoint's
``backbone.body.conv1.weight`` shape on load — never trust filenames.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)


# Filename → declared input channels (best-effort documentation only; the
# loader overrides this by reading conv1 from the checkpoint).
_CHANNEL_HINTS = [
    (r"rgbd1",           4),
    (r"rgbd3",           6),
    (r"rgb_re_nir",      5),
    (r"mult_d1",         9),
    (r"mult",            8),
    (r"dem1",            1),
    (r"dem3",            3),
    (r"dem(?![0-9])",    3),
    (r"rgb(?![a-z])",    3),
]


def _guess_channels(filename: str) -> Optional[int]:
    fn = filename.lower()
    for pat, ch in _CHANNEL_HINTS:
        if re.search(pat, fn):
            return ch
    return None


@dataclass
class ModelEntry:
    id: str
    family: str                  # bishop | gobabeb | tornado | hypolith | ...
    category: str                # aquatic | terrestrial | space
    variant: str                 # hero | tl_rgb | ntl_mult_d1 | eureka_aug_bin
    path: str                    # absolute path inside container
    rel_path: str                # path relative to WEIGHTS_ROOT
    epoch: Optional[int] = None
    declared_channels: Optional[int] = None
    tags: List[str] = field(default_factory=list)
    description: str = ""
    size_bytes: int = 0


_EPOCH_RE = re.compile(r"e(?:poch_)?(\d{3,6})", re.IGNORECASE)


def _parse_epoch(stem: str) -> Optional[int]:
    m = _EPOCH_RE.search(stem)
    return int(m.group(1)) if m else None


def _family_from_path(rel: Path) -> tuple[str, str]:
    parts = rel.parts
    category = parts[0] if parts else "unknown"
    family = parts[1] if len(parts) > 1 else "unknown"
    # Trim "deepgis_" prefix that some project dirs carry.
    family = re.sub(r"^deepgis_", "", family)
    # Normalize commonly-split names.
    family = family.replace("jezero_field", "").rstrip("_") or family
    if family.startswith("bishop"):
        family = "bishop"
    if family.startswith("gobabeb"):
        family = "gobabeb"
    if family.startswith("tornado"):
        family = "tornado"
    return category, family


def _id_from(family: str, variant: str, epoch: Optional[int]) -> str:
    e = f"_e{epoch:04d}" if epoch is not None else ""
    return f"{family}_{variant}{e}".lower()


def _variant_from_filename(family: str, stem: str, sub: str) -> str:
    """Derive the variant token (after family) from the filename/subdir."""
    s = stem.lower()
    # Strip leading "<family>_" if present.
    if s.startswith(family + "_"):
        s = s[len(family) + 1:]
    # Strip trailing _eNNNN.
    s = _EPOCH_RE.sub("", s).rstrip("_")
    # Fallbacks for hero (top-level of a project dir) and for names like
    # ``epoch_0004`` that contain only the epoch.
    if not s or s == "epoch":
        s = "hero"
    # Prefix by ablation bucket (tl / ntl / rock / c3) if we found one.
    if sub:
        s = f"{sub}_{s}" if not s.startswith(sub + "_") else s
    return s


def discover(weights_root: str) -> Dict[str, ModelEntry]:
    root = Path(weights_root)
    if not root.exists():
        log.warning("WEIGHTS_ROOT %s does not exist", weights_root)
        return {}

    entries: Dict[str, ModelEntry] = {}
    for p in sorted(root.rglob("*.param")):
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue

        category, family = _family_from_path(rel)

        # Determine ablation bucket (e.g. ablations/tl/*.param -> sub="tl").
        sub = ""
        rel_parts = list(rel.parts)
        if "ablations" in rel_parts:
            idx = rel_parts.index("ablations")
            if idx + 1 < len(rel_parts) - 1:
                sub = rel_parts[idx + 1]

        variant = _variant_from_filename(family, p.stem, sub)
        epoch = _parse_epoch(p.stem)
        ch = _guess_channels(p.name)
        tags = []
        if "ablations" in rel_parts:
            tags.append("ablation")
        else:
            tags.append("curated")
        if sub:
            tags.append(sub)
        if ch == 3 and "rgb" in p.name.lower():
            tags.append("rgb")
        if "mult" in p.name.lower():
            tags.append("multispectral")
        if "dem" in p.name.lower():
            tags.append("dem")

        entry = ModelEntry(
            id=_id_from(family, variant, epoch),
            family=family,
            category=category,
            variant=variant,
            path=str(p),
            rel_path=str(rel),
            epoch=epoch,
            declared_channels=ch,
            tags=tags,
            description="",
            size_bytes=p.stat().st_size,
        )

        # Collision guard — keep the one with the higher epoch, else keep the
        # curated one over the ablation one.
        if entry.id in entries:
            other = entries[entry.id]
            if (entry.epoch or 0) > (other.epoch or 0):
                entries[entry.id] = entry
            continue
        entries[entry.id] = entry

    log.info("registry: discovered %d checkpoints under %s", len(entries), root)
    return entries


def to_public_json(entries: Dict[str, ModelEntry]) -> List[dict]:
    return [asdict(e) for e in sorted(entries.values(), key=lambda e: e.id)]


def pick_default(entries: Dict[str, ModelEntry], requested: Optional[str]) -> Optional[str]:
    if requested and requested in entries:
        return requested
    # Prefer the bishop hero as the default since it's our flagship rock
    # model with a dedicated training run.
    for candidate in ("bishop_hero_e0004", "gobabeb_hero_e0011"):
        if candidate in entries:
            return candidate
    return next(iter(entries)) if entries else None
