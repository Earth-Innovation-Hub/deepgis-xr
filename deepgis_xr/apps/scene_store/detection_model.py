"""How likely a later look is to find an entity again.

The existence chain needs P(detected | present) for every look that covered an entity.
One fixed value treats a house first seen at 10 cm pixels and looked for again at 80 cm
pixels like a repeat at the same zoom. This module fits that probability on the store's
own record. A look is a capture whose footprint covered an entity seen earlier by one of
its kernels; it found the entity when one of its detections was merged into it, which is
exactly when ingest writes a hit instead of a miss.

    logit P(found) = intercept + log2_pixels * (log2 pixels - 10)
                     + coarser * max(z, 0) + finer * max(-z, 0) + category offset

    pixels   entity area / (ground size of a pixel in the looking capture)^2
    z        log2(pixel size of the looking capture / pixel size at the first sighting)
    category what the entity was believed to be before the look

A non-find is a detector miss only if the object was there. Looks are therefore kept only
when the looking capture shows the same imagery as the first sighting (or neither is
dated), so the ground cannot have changed between the two.

The hit table stays fixed. A small object is both less often detected and less often
hallucinated, and the likelihood ratio of a hit is what the chain uses; the store holds
no record of false alarms to fit that ratio on.
"""

import math
import time

import numpy as np
from django.db import connections

from . import priors
from .models import DetectionModel

DB = 'observations'
MIN_LOOKS = 200
MIN_CATEGORY_LOOKS = 25
CACHE_S = 60.0
_cache = {}

# Every (later capture, entity) pair that ingest would have judged a hit or a miss, with what
# was known before the look. Entity area, outline and sources are today's values.
LOOKS_SQL = """
WITH firsts AS (
  SELECT DISTINCT ON (a.entity_id) a.entity_id, c.captured_at, c.gsd_m, d.category,
         c.imagery_start, c.imagery_end
    FROM sg_association a
    JOIN sg_detection d ON d.id = a.detection_id
    JOIN sg_capture c ON c.id = d.capture_id
   WHERE d.gate = '' AND c.taxonomy = %(taxonomy)s AND c.gsd_m IS NOT NULL
   ORDER BY a.entity_id, c.captured_at, d.id)
SELECT e.id, c.id, e.area_m2 / (c.gsd_m * c.gsd_m), c.gsd_m / f.gsd_m,
       COALESCE((SELECT s.category FROM sg_belief_snapshot s
                  WHERE s.entity_id = e.id AND s.at < c.recorded_at
                  ORDER BY s.at DESC, s.id DESC LIMIT 1), f.category),
       EXISTS (SELECT 1 FROM sg_association a JOIN sg_detection d ON d.id = a.detection_id
                WHERE a.entity_id = e.id AND d.capture_id = c.id AND d.gate = '')
  FROM sg_capture c
  JOIN sg_entity e ON e.taxonomy = c.taxonomy AND e.retired_at IS NULL
       AND e.geom && c.footprint AND e.sources && c.sources
       AND ST_XMax(e.geom) <= 180 AND ST_XMin(e.geom) >= -180 AND ST_YMax(e.geom) <= 90 AND ST_YMin(e.geom) >= -90
       AND ST_Area(ST_Intersection(e.geom, c.footprint)) >= %(coverage)s * ST_Area(e.geom)
  JOIN firsts f ON f.entity_id = e.id AND f.captured_at < c.captured_at
 WHERE c.taxonomy = %(taxonomy)s AND c.gsd_m IS NOT NULL AND e.area_m2 IS NOT NULL
   AND e.area_m2 >= %(min_pixels)s * c.gsd_m * c.gsd_m
   AND (c.imagery_start IS NULL OR f.imagery_start IS NULL
        OR (c.imagery_start = f.imagery_start AND c.imagery_end = f.imagery_end))
"""

FIRST_GSD_SQL = """
SELECT DISTINCT ON (a.entity_id) a.entity_id, c.gsd_m
  FROM sg_association a
  JOIN sg_detection d ON d.id = a.detection_id
  JOIN sg_capture c ON c.id = d.capture_id
 WHERE a.entity_id = ANY(%s) AND d.gate = '' AND c.gsd_m IS NOT NULL
 ORDER BY a.entity_id, c.captured_at, d.id
"""


def features(pixels, zoom_ratio):
    """[1, log2 pixels - 10, doublings coarser, doublings finer] for one look."""
    z = math.log2(zoom_ratio) if zoom_ratio and zoom_ratio > 0 else 0.0
    return [1.0, math.log2(max(float(pixels), 1.0)) - 10.0, max(z, 0.0), max(-z, 0.0)]


class Fitted:
    def __init__(self, version, coefficients):
        self.version = version
        c = coefficients
        self.base = [c['intercept'], c['log2_pixels'], c['coarser'], c['finer']]
        self.category = c.get('category') or {}

    def p_detect(self, pixels, zoom_ratio, category):
        """P(this look finds the entity | it is there), inside [P_FALSE_ALARM, P_DETECT_MAX]."""
        s = sum(w * x for w, x in zip(self.base, features(pixels, zoom_ratio)))
        s += self.category.get(category, 0.0)
        p = 1.0 / (1.0 + math.exp(-max(min(s, 30.0), -30.0)))
        return min(max(p, priors.P_FALSE_ALARM), priors.P_DETECT_MAX)


def active(taxonomy):
    """The fit in use for ``taxonomy``, or None (the fixed priors.P_DETECT then applies)."""
    hit = _cache.get(taxonomy)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    row = DetectionModel.objects.filter(taxonomy=taxonomy, active=True).order_by('-version').first()
    model = Fitted(row.version, row.coefficients) if row else None
    _cache[taxonomy] = (time.monotonic(), model)
    return model


def forget():
    _cache.clear()


def first_gsd(entity_ids):
    """{entity id: pixel size (m) of the capture that first saw it}."""
    if not entity_ids:
        return {}
    with connections[DB].cursor() as cur:
        cur.execute(FIRST_GSD_SQL, [list(entity_ids)])
        return dict(cur.fetchall())


def miss_evidence(model, *, area_m2, gsd_m, first_gsd_m, category):
    """(log table, metadata) for a miss factor on one entity in one capture."""
    if model is None or not area_m2 or not gsd_m:
        return priors.MISS_TABLE, {'p_detect': priors.P_DETECT}
    pixels = area_m2 / gsd_m ** 2
    ratio = gsd_m / first_gsd_m if first_gsd_m else 1.0
    p = model.p_detect(pixels, ratio, category)
    return priors.miss_table(p), {'p_detect': round(p, 4), 'pixels': round(pixels, 1),
                                  'zoom_ratio': round(ratio, 3), 'category': category, 'model': model.version}


def looks(taxonomy):
    """[(entity id, capture id, pixels, zoom ratio, category before, found)] from the store."""
    with connections[DB].cursor() as cur:
        cur.execute(LOOKS_SQL, {'taxonomy': taxonomy, 'coverage': priors.MISS_COVERAGE,
                                'min_pixels': priors.MISS_MIN_PIXELS})
        return cur.fetchall()


def _design(rows, categories):
    index = {c: i for i, c in enumerate(categories)}
    x = np.zeros((len(rows), 4 + len(categories)))
    for i, (_, _, pixels, ratio, category, _) in enumerate(rows):
        x[i, :4] = features(pixels, ratio)
        if category in index:
            x[i, 4 + index[category]] = 1.0
    return x


def _newton(x, y, l2, iters=80):
    """Penalised logistic regression: the intercept is free, the three slopes nearly so."""
    w = np.zeros(x.shape[1])
    pen = np.full(x.shape[1], float(l2))
    pen[0] = 0.0
    pen[1:4] = l2 * 0.01
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-np.clip(x @ w, -30, 30)))
        grad = x.T @ (p - y) + pen * w
        hess = (x * (p * (1 - p))[:, None]).T @ x + np.diag(pen) + 1e-9 * np.eye(x.shape[1])
        step = np.linalg.solve(hess, grad)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w


def _log_loss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def fit(rows, *, l2=3.0, folds=5, seed=0):
    """(coefficients, metrics) from ``looks`` rows. Raises ValueError when the record is too thin."""
    y = np.array([1.0 if r[5] else 0.0 for r in rows])
    if len(rows) < MIN_LOOKS or y.min() == y.max():
        raise ValueError(f'{len(rows)} looks is too few to fit (need {MIN_LOOKS} with both outcomes)')
    counts = {}
    for r in rows:
        counts[r[4]] = counts.get(r[4], 0) + 1
    categories = sorted(c for c, n in counts.items() if n >= MIN_CATEGORY_LOOKS)
    x = _design(rows, categories)

    # Held-out captures: every look of a capture is in the same fold.
    groups = np.array([r[1] for r in rows])
    captures = np.unique(groups)
    np.random.default_rng(seed).shuffle(captures)
    held, base = np.zeros(len(y)), np.zeros(len(y))
    for part in np.array_split(captures, min(folds, len(captures))):
        test = np.isin(groups, part)
        if test.all() or not test.any():
            continue
        w = _newton(x[~test], y[~test], l2)
        held[test] = 1.0 / (1.0 + np.exp(-np.clip(x[test] @ w, -30, 30)))
        base[test] = y[~test].mean()
    held = np.clip(held, priors.P_FALSE_ALARM, priors.P_DETECT_MAX)
    calibration = []
    for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
        m = (held >= lo) & (held < lo + 0.2 + (1e-9 if lo == 0.8 else 0))
        if m.any():
            calibration.append({'lo': lo, 'hi': round(lo + 0.2, 1), 'n': int(m.sum()),
                                'predicted': round(float(held[m].mean()), 3),
                                'found': round(float(y[m].mean()), 3)})
    w = _newton(x, y, l2)
    coefficients = {
        'intercept': round(float(w[0]), 4), 'log2_pixels': round(float(w[1]), 4),
        'coarser': round(float(w[2]), 4), 'finer': round(float(w[3]), 4),
        'category': {c: round(float(v), 4) for c, v in zip(categories, w[4:])},
    }
    metrics = {
        'n_looks': len(rows), 'n_captures': int(len(captures)), 'found_rate': round(float(y.mean()), 4),
        'l2': l2, 'folds': int(min(folds, len(captures))),
        'log_loss': {'fitted': round(_log_loss(held, y), 4), 'found_rate': round(_log_loss(base, y), 4),
                     'fixed': round(_log_loss(np.full(len(y), priors.P_DETECT), y), 4)},
        'calibration': calibration,
        'looks_by_category': dict(sorted(counts.items(), key=lambda kv: -kv[1])),
    }
    return coefficients, metrics


def store(taxonomy, coefficients, metrics):
    """Save a fit as the active model for ``taxonomy``; older fits stay as inactive rows."""
    last = DetectionModel.objects.filter(taxonomy=taxonomy).order_by('-version').first()
    DetectionModel.objects.filter(taxonomy=taxonomy, active=True).update(active=False)
    row = DetectionModel.objects.create(taxonomy=taxonomy, version=(last.version + 1) if last else 1,
                                        active=True, coefficients=coefficients,
                                        n_looks=metrics['n_looks'], metrics=metrics)
    forget()
    return row
