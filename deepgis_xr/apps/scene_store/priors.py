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
MISS_MIN_PIXELS = 64        # an entity smaller than this many ground pixels could not have been seen
# A region smaller than this many pixels of its own capture is a fragment: stored, never evidence.
# The same size below which a miss is not counted, so what cannot be missed cannot be a hit either.
# (Stored urban_v1 entities were found again in 9% of the later looks where they were this small.)
FRAGMENT_MIN_PIXELS = MISS_MIN_PIXELS

# Below this top posterior an entity is labelled unknown (its posterior keeps the best guess).
# Stored beliefs cluster at 0.10-0.20 (unlabelled OSM and plain SAM regions, near uniform over
# 10-14 categories), with a valley at 0.25-0.30 before the next mode.
LOW_CONFIDENCE = 0.25

# Pose uncertainty of a capture taken from the 3D globe (1 sigma). The virtual camera is exact
# relative to the imagery; the error is the imagery's own georegistration.
VIRTUAL_CAMERA_SIGMA_H_M = 2.5
VIRTUAL_CAMERA_SIGMA_V_M = 5.0

# Geometry plausibility. A region covering most of the capture footprint is the frame itself
# (a whole-image box or mask), not an object: it is stored but never becomes evidence.
GATE_FOOTPRINT_FRAC = 0.5
# Plausible ground area (m²) per category; outside the range each e-fold costs GEOMETRY_SLOPE
# in log-potential, down to GEOMETRY_FLOOR. Categories not listed (unknown) are unconstrained,
# so an implausible region drifts toward unknown instead of becoming a giant car or road.
CATEGORY_AREA_M2 = {
    'vehicle': (1.5, 120.0),
    'house': (30.0, 3000.0),
    'pool': (4.0, 600.0),
    'solar_panel': (1.0, 20000.0),
    'tree': (1.0, 3000.0),
    'debris': (0.5, 2000.0),
    'building': (20.0, 200000.0),
    'road': (20.0, 300000.0),
    'parking_lot': (100.0, 100000.0),
}
GEOMETRY_SLOPE = 2.0
GEOMETRY_FLOOR = -8.0
# A road region this large is long and thin; one this compact (4πA/P², 1 = disc, π/4 = square)
# is a frame-clipped or whole-area blob.
ROAD_BLOB_MIN_M2 = 5000.0
ROAD_BLOB_COMPACTNESS = 0.35
ROAD_BLOB_PENALTY = -3.0

# Existence sensor model: P(detected | present), P(detected | absent).
# P_DETECT is the fallback for a taxonomy with no fitted detection model (see detection_model.py):
# a miss then weighs the same whatever the object's size and the zoom of the look.
P_DETECT = 0.8
P_FALSE_ALARM = 0.05
P_DETECT_MAX = 0.98         # a fitted probability is kept inside [P_FALSE_ALARM, P_DETECT_MAX]

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

# Field readings: a ground robot's spectrometer, aimed with a laser, registered to the entity
# under the laser target. The target's position is uncertain by the robot's position and by
# its aim (range x heading error), plus the patch the spectrometer averages.
FIELD_POSITION_SIGMA_M = 2.5
FIELD_HEADING_SIGMA_DEG = 5.0
FIELD_MAX_RANGE_M = 60.0
FIELD_MIN_WEIGHT = 0.25     # least share of the target's uncertainty that must fall on the entity
FIELD_MIN_SUN_DEG = 10.0    # the index needs daylight
# The NIR/red index is a ratio of raw counts, not reflectance, so it is used as one yes/no
# question: is the patch green vegetation? Above this value the robot's own notes call it green
# (in daylight its readings sit near -0.2 on built surfaces and near +0.6 on grass).
FIELD_GREEN_INDEX = 0.14
# P(green | category). Daylight readings on stored entities (Nov 2026): 20 of 26 green on
# vegetation_other, 8 of 112 on house and building, 0 of 12 on tree (a side view of a canopy
# or trunk), so tree is left near neutral. Categories not listed use FIELD_P_GREEN_OTHER.
FIELD_P_GREEN = {
    'vegetation_other': 0.75,
    'tree': 0.4,
    'building': 0.1, 'house': 0.1, 'solar_panel': 0.1, 'road': 0.1, 'vehicle': 0.1,
    'pavement': 0.1, 'parking_lot': 0.1, 'pool': 0.1, 'water': 0.1,
}
FIELD_P_GREEN_OTHER = 0.25

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


def geometry_table(taxonomy, area_m2, compactness=None):
    """Log-potential over categories for one region's ground area and shape (None if neutral)."""
    t = np.zeros(taxonomy.n)
    if not area_m2 or area_m2 <= 0:
        return None
    for cat, (lo, hi) in CATEGORY_AREA_M2.items():
        if cat not in taxonomy.categories:
            continue
        if area_m2 < lo:
            t[taxonomy.index_of(cat)] = -GEOMETRY_SLOPE * math.log(lo / area_m2)
        elif area_m2 > hi:
            t[taxonomy.index_of(cat)] = -GEOMETRY_SLOPE * math.log(area_m2 / hi)
    if 'road' in taxonomy.categories and compactness is not None and \
            area_m2 > ROAD_BLOB_MIN_M2 and compactness >= ROAD_BLOB_COMPACTNESS:
        t[taxonomy.index_of('road')] += ROAD_BLOB_PENALTY
    t = np.maximum(t, GEOMETRY_FLOOR)
    return t if t.any() else None


HIT_TABLE = [math.log(P_FALSE_ALARM), math.log(P_DETECT)]
MISS_TABLE = [math.log(1 - P_FALSE_ALARM), math.log(1 - P_DETECT)]


def miss_table(p_detect):
    """log P(not detected | absent, present) for a look that finds a present object with ``p_detect``.

    At ``p_detect`` = P_FALSE_ALARM the look says nothing; it never counts for the object."""
    p = min(max(float(p_detect), P_FALSE_ALARM), P_DETECT_MAX)
    return [math.log(1 - P_FALSE_ALARM), math.log(1 - p)]


def field_green_table(taxonomy, green):
    """log P(the patch reads green, or not | category) for one field reading."""
    t = np.empty(taxonomy.n)
    for i, cat in enumerate(taxonomy.categories):
        p = FIELD_P_GREEN.get(cat, FIELD_P_GREEN_OTHER)
        t[i] = math.log(p if green else 1 - p)
    return t


def feedback_category_table(taxonomy, category):
    k = taxonomy.n
    t = np.full(k, math.log((1 - FEEDBACK_P) / (k - 1)))
    t[taxonomy.index_of(category)] = math.log(FEEDBACK_P)
    return FEEDBACK_STRENGTH * t


def feedback_exists_table(present):
    p = FEEDBACK_P if present else 1 - FEEDBACK_P
    return [FEEDBACK_STRENGTH * math.log(1 - p), FEEDBACK_STRENGTH * math.log(p)]
