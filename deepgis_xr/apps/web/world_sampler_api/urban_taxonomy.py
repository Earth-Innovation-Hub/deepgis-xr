"""
``urban_v1``: PHX_URBAN_V0 plus the urban object classes text-prompted
models can name directly (house, pool, parking lot, solar panel).

kernelcal ships Q_s priors only for ``phx_urban_v0``. This module lifts
those priors onto ``urban_v1`` and adds priors for the ultralytics
kernels (SAM 3, YOLOE-26, YOLO26 COCO), so a SceneGraph can fuse all
of them in one posterior.

Q_s convention (same as kernelcal): ``matrix[native, category]`` is
P(native label | true category), and every column sums to one.

Lifting rule: each new category starts from the column of the v0
category it was split out of (``CHILD_OF``). A source that cannot tell
a house from a building therefore says the same thing about both, and
the split is decided by the sources that can (SAM 3 / YOLOE prompts).
"""

from __future__ import annotations

from typing import Dict, Mapping, Optional, Sequence

import numpy as np
from kernelcal.distinction_game import PHX_URBAN_V0, Taxonomy, default_q_s_table
from kernelcal.distinction_game.q_s import ConfusionMatrix
from kernelcal.distinction_game.taxonomy import by_name as _kc_by_name


CHILD_OF = {
    'house': 'building',
    'solar_panel': 'building',
    'parking_lot': 'pavement',
    'pool': 'water',
}

URBAN_V1 = Taxonomy(
    name='urban_v1',
    categories=(
        'unknown', 'building', 'house', 'solar_panel',
        'road', 'vehicle', 'pavement', 'parking_lot',
        'tree', 'vegetation_other',
        'bare_ground', 'water', 'pool', 'debris',
    ),
    super_classes={
        'building': 'structure', 'house': 'structure', 'solar_panel': 'structure',
        'road': 'transport', 'vehicle': 'transport',
        'pavement': 'transport', 'parking_lot': 'transport',
        'tree': 'vegetation', 'vegetation_other': 'vegetation',
        'bare_ground': 'natural', 'water': 'natural', 'pool': 'natural', 'debris': 'natural',
    },
    description=(
        'PHX_URBAN_V0 with house, solar_panel, parking_lot and pool split out '
        'of building, pavement and water for text-prompted kernels.'
    ),
)

TAXONOMIES = {PHX_URBAN_V0.name: PHX_URBAN_V0, URBAN_V1.name: URBAN_V1}

# Kernels whose claims only make sense under urban_v1.
URBAN_V1_SOURCES = ('sam3', 'yoloe', 'yolo26')


def taxonomy_by_name(name: Optional[str]) -> Taxonomy:
    if not name:
        return PHX_URBAN_V0
    if name in TAXONOMIES:
        return TAXONOMIES[name]
    return _kc_by_name(name)


def _column_stochastic(m: np.ndarray) -> np.ndarray:
    sums = m.sum(axis=0, keepdims=True)
    sums[sums == 0] = 1.0
    return m / sums


def lift_to_urban_v1(cm: ConfusionMatrix) -> ConfusionMatrix:
    """Re-index a phx_urban_v0 Q_s onto urban_v1 columns."""
    src = np.asarray(cm.matrix, dtype=float)
    out = np.zeros((src.shape[0], URBAN_V1.n))
    for j, cat in enumerate(URBAN_V1.categories):
        out[:, j] = src[:, PHX_URBAN_V0.index_of(CHILD_OF.get(cat, cat))]
    return ConfusionMatrix(
        source_id=cm.source_id,
        taxonomy=URBAN_V1,
        native_labels=tuple(cm.native_labels),
        matrix=_column_stochastic(out),
        description=f'{cm.description} (lifted to urban_v1)'.strip(),
    )


def _q_from_affinity(
    source_id: str,
    affinity: Mapping[str, Mapping[str, float]],
    *,
    floor: float = 0.02,
    description: str = '',
) -> ConfusionMatrix:
    """Build Q_s from ``native -> {category: weight}``.

    ``floor`` keeps every native label possible under every category so
    one surprising claim can't zero a posterior. The ``unknown`` column
    is uniform.
    """
    natives = tuple(affinity)
    m = np.full((len(natives), URBAN_V1.n), floor)
    m[:, URBAN_V1.index_of('unknown')] = 1.0
    for i, native in enumerate(natives):
        for cat, w in affinity[native].items():
            m[i, URBAN_V1.index_of(cat)] += w
    return ConfusionMatrix(
        source_id=source_id,
        taxonomy=URBAN_V1,
        native_labels=natives,
        matrix=_column_stochastic(m),
        description=description,
    )


# Text prompts for SAM 3 / YOLOE, keyed by the phrase the user types.
# Unlisted phrases fall back to UNMAPPED_PROMPT (weak evidence only).
PROMPT_AFFINITY: Dict[str, Dict[str, float]] = {
    'building':      {'building': 0.8, 'house': 0.5, 'solar_panel': 0.1},
    'house':         {'house': 0.8, 'building': 0.4},
    'roof':          {'house': 0.5, 'building': 0.5},
    'solar panel':   {'solar_panel': 0.85, 'building': 0.1},
    'tree':          {'tree': 0.85, 'vegetation_other': 0.2},
    'grass':         {'vegetation_other': 0.8, 'tree': 0.1},
    'lawn':          {'vegetation_other': 0.8},
    'bush':          {'vegetation_other': 0.6, 'tree': 0.3},
    'car':           {'vehicle': 0.9},
    'truck':         {'vehicle': 0.85},
    'vehicle':       {'vehicle': 0.85},
    'swimming pool': {'pool': 0.9, 'water': 0.3},
    'pool':          {'pool': 0.85, 'water': 0.3},
    'water':         {'water': 0.8, 'pool': 0.4},
    'road':          {'road': 0.8, 'pavement': 0.3, 'parking_lot': 0.1},
    'parking lot':   {'parking_lot': 0.8, 'pavement': 0.4},
    'sidewalk':      {'pavement': 0.7, 'road': 0.1},
    'dirt':          {'bare_ground': 0.7},
    'rock':          {'bare_ground': 0.4, 'debris': 0.4},
}
UNMAPPED_PROMPT = '<other_prompt>'

# COCO classes YOLO26 can fire on from the air.
COCO_AFFINITY: Dict[str, Dict[str, float]] = {
    'car':        {'vehicle': 0.9},
    'truck':      {'vehicle': 0.85},
    'bus':        {'vehicle': 0.8},
    'motorcycle': {'vehicle': 0.6},
    'bicycle':    {'vehicle': 0.3},
    'boat':       {'vehicle': 0.3, 'pool': 0.1, 'water': 0.1},
    'airplane':   {'vehicle': 0.5},
    'train':      {'vehicle': 0.6, 'road': 0.1},
}
UNMAPPED_COCO = '<other_coco>'


def prompt_native_label(phrase: str) -> str:
    key = (phrase or '').strip().lower()
    return key if key in PROMPT_AFFINITY else UNMAPPED_PROMPT


def coco_native_label(name: str) -> str:
    key = (name or '').strip().lower()
    return key if key in COCO_AFFINITY else UNMAPPED_COCO


def _ultralytics_q_s() -> Dict[str, ConfusionMatrix]:
    prompts = dict(PROMPT_AFFINITY, **{UNMAPPED_PROMPT: {}})
    coco = dict(COCO_AFFINITY, **{UNMAPPED_COCO: {}})
    return {
        'sam3': _q_from_affinity(
            'sam3', prompts,
            description='SAM 3 text-prompted masks; native label = prompt phrase.',
        ),
        'yoloe': _q_from_affinity(
            'yoloe', prompts, floor=0.04,
            description='YOLOE-26 open-vocabulary prompts; noisier than SAM 3 at nadir.',
        ),
        'yolo26': _q_from_affinity(
            'yolo26', coco,
            description='YOLO26 COCO; only vehicles are meaningful from the air.',
        ),
    }


# mr_rocks was trained on Bishop rock fields. Over a city its "rock" masks are roofs, yards and
# oblique smears, not debris, so in urban taxonomies "rock" points at unknown and debris gets the
# same small rate as pavement. The rooftop (building 0.45) and bare-ground rates are kept.
MR_ROCKS_URBAN_ROCK = {'unknown': 0.85, 'debris': 0.1}


def urban_mr_rocks(cm: ConfusionMatrix) -> ConfusionMatrix:
    m = np.array(cm.matrix, dtype=float)
    rock = list(cm.native_labels).index('rock')
    for cat, p in MR_ROCKS_URBAN_ROCK.items():
        j = cm.taxonomy.index_of(cat)
        rest = m[:, j].sum() - m[rock, j]
        m[:, j] *= (1 - p) / rest if rest > 0 else 1.0
        m[rock, j] = p
    return ConfusionMatrix(
        source_id=cm.source_id,
        taxonomy=cm.taxonomy,
        native_labels=tuple(cm.native_labels),
        matrix=m,
        description=f'{cm.description} (urban: rock -> unknown, not debris)',
    )


def q_s_table_for(taxonomy: Taxonomy) -> Dict[str, ConfusionMatrix]:
    if taxonomy is PHX_URBAN_V0:
        table = dict(default_q_s_table(taxonomy=PHX_URBAN_V0))
    elif taxonomy is URBAN_V1:
        table = {sid: lift_to_urban_v1(cm) for sid, cm in default_q_s_table(taxonomy=PHX_URBAN_V0).items()}
        table.update(_ultralytics_q_s())
    else:
        raise KeyError(f'no Q_s priors for taxonomy {taxonomy.name!r}')
    if 'mr_rocks' in table:
        table['mr_rocks'] = urban_mr_rocks(table['mr_rocks'])
    return table


def pick_taxonomy(requested: Optional[str], sources: Sequence[str]) -> Taxonomy:
    """Explicit request wins; otherwise urban_v1 when any ultralytics kernel contributed."""
    if requested:
        return taxonomy_by_name(requested)
    if any(s in URBAN_V1_SOURCES for s in sources):
        return URBAN_V1
    return PHX_URBAN_V0
