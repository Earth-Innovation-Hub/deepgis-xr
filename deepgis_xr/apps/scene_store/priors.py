"""Hand-set priors for the spatiotemporal factor graph.

All tables are indexed by category *name*, so they apply to any taxonomy
that has the categories (phx_urban_v0 simply lacks house, pool, ...).
"""

import math

import numpy as np

# Data association.
ASSOC_IOU = 0.3
ASSOC_CENTROID_M = 2.0      # small objects (cars) whose masks jitter between captures
MISS_COVERAGE = 0.9         # footprint must cover this much of an entity to count a miss

# Existence sensor model: P(detected | present), P(detected | absent).
P_DETECT = 0.8
P_FALSE_ALARM = 0.05

# Half-lives in hours. Perceptual (category) evidence is down-weighted by
# age at inference time; existence half-lives set how fast the existence
# chain forgets toward 0.5 between observations.
HOUR, DAY, YEAR = 1.0, 24.0, 24.0 * 365
PERCEPTUAL_HALF_LIFE_H = 5 * YEAR
EXISTENCE_HALF_LIFE_H = {
    'vehicle': 4 * HOUR,
    'debris': 30 * DAY,
    'unknown': 30 * DAY,
    'vegetation_other': YEAR,
    'bare_ground': YEAR,
    'water': YEAR,
    'tree': 2 * YEAR,
}
DEFAULT_EXISTENCE_HALF_LIFE_H = 5 * YEAR

# User feedback: how sure a correction is, and how many observations it outweighs.
FEEDBACK_P = 0.98
FEEDBACK_STRENGTH = 4.0

# Adjacency co-occurrence (symmetric), log-potential added when both hold.
CONTEXT_BETA = 0.5
CONTEXT_DEGREE_CAP = 6      # nearest neighbours per entity per capture
CONTEXT = {
    ('vehicle', 'road'): 0.5,
    ('vehicle', 'parking_lot'): 0.7,
    ('vehicle', 'pavement'): 0.3,
    ('pool', 'house'): 0.5,
    ('pool', 'building'): 0.2,
    ('house', 'house'): 0.3,
    ('tree', 'vegetation_other'): 0.3,
    ('tree', 'house'): 0.2,
    ('vehicle', 'tree'): -0.2,
    ('pool', 'road'): -0.5,
}

# Containment (parent, child), log-potential; anything else is neutral.
CONTAINS = {
    ('building', 'solar_panel'): 1.0,
    ('house', 'solar_panel'): 1.0,
    ('parking_lot', 'vehicle'): 0.8,
    ('road', 'vehicle'): 0.6,
    ('pavement', 'vehicle'): 0.4,
    ('vegetation_other', 'tree'): 0.3,
    ('solar_panel', 'building'): -1.0,
    ('solar_panel', 'house'): -1.0,
    ('vehicle', 'building'): -1.0,
    ('vehicle', 'house'): -1.0,
    ('pool', 'house'): -0.5,
}


def existence_half_life_h(category):
    return EXISTENCE_HALF_LIFE_H.get(category, DEFAULT_EXISTENCE_HALF_LIFE_H)


def decay_weight(age_h, half_life_h):
    if age_h <= 0:
        return 1.0
    return 0.5 ** (age_h / half_life_h)


def persistence_table(dt, half_life_h):
    """log P(x_t | x_prev) for a gap ``dt``: stay with prob e, else resample uniformly."""
    e = decay_weight(max(dt.total_seconds(), 0.0) / 3600.0, half_life_h)
    t = np.full((2, 2), (1 - e) / 2)
    t[np.diag_indices(2)] += e
    return np.log(np.maximum(t, 1e-12))


def _pair_table(taxonomy, pairs, *, symmetric):
    t = np.zeros((taxonomy.n, taxonomy.n))
    cats = taxonomy.categories
    for (a, b), w in pairs.items():
        if a in cats and b in cats:
            i, j = taxonomy.index_of(a), taxonomy.index_of(b)
            t[i, j] = w
            if symmetric:
                t[j, i] = w
    return t


def context_table(taxonomy):
    return CONTEXT_BETA * _pair_table(taxonomy, CONTEXT, symmetric=True)


def contains_table(taxonomy):
    return _pair_table(taxonomy, CONTAINS, symmetric=False)


HIT_TABLE = [math.log(P_FALSE_ALARM), math.log(P_DETECT)]
MISS_TABLE = [math.log(1 - P_FALSE_ALARM), math.log(1 - P_DETECT)]


def feedback_category_table(taxonomy, category):
    k = taxonomy.n
    t = np.full(k, math.log((1 - FEEDBACK_P) / (k - 1)))
    t[taxonomy.index_of(category)] = math.log(FEEDBACK_P)
    return FEEDBACK_STRENGTH * t


def feedback_exists_table(present):
    p = FEEDBACK_P if present else 1 - FEEDBACK_P
    return [FEEDBACK_STRENGTH * math.log(1 - p), FEEDBACK_STRENGTH * math.log(p)]
