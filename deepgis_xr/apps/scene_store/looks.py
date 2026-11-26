"""Looks: evidence that shares an image is pooled before it counts.

A look is one image of the ground: one acquisition by one sensor. Several captures can show
the same look (the basemap serves one vintage however often it is viewed), and a detector run
again on the same pixels repeats its own mistakes. Multiplying those detections together as if
each were a new observation is the error this module removes.

The factor graph gets one hidden variable per entity and look, "what this image shows here":

    world (exists x, category c)  --  what the image shows (a)  --  detection 1, detection 2, ...

Detections are evidence about the image; only the image is evidence about the world, and one
image can be trusted only so far. The hidden variable is summed out when beliefs are computed,
so each look sends the entity one message however many times it was captured. Stored factors
are not touched: a hit, a miss and a detection's posterior stay as the detector delivered
them, and the grouping is derived from each factor's capture at inference time.

Existence. ``a`` is whether the image shows an object here. The stored hit and miss tables are
read as P(detection | a); that is what the fitted miss weights measure (how often a later
look at the same pixels finds the object again). ``priors.LOOK_SHOWS_IF_ABSENT`` and
``LOOK_HIDES_IF_PRESENT`` tie ``a`` to the world. More captures of one image make ``a``
certain and no more: the message saturates at what one image can prove
(``exists_limits``). A single detection is doubted twice, by the detector and by the image,
so it says a little less than it did when it was taken as a direct observation of the world.

Category. ``a`` is the category the image reads as. A detection's table (its posterior plus
the geometry prior) is P(image reads as that | category); repeated detections are copies of
one reading with a small chance of differing (``priors.LOOK_REREAD_ERROR``). When they agree
the message is one reading, not their product; when they disagree it is a mixture weighted by
how many detections back each reading.

Different looks are independent and their messages add in log space, as before. A capture
whose imagery is not identified is a look of its own.
"""

import math

import numpy as np

from . import priors


def key_of(capture_id, source, start, end):
    """Name of the look a capture shows: the imagery and its acquisition window, else the capture."""
    if source and start and end:
        return f'{source}|{start.isoformat()}|{end.isoformat()}'
    return f'capture:{capture_id}'


def keys(capture_ids):
    """{capture id: look key}."""
    from .models import Capture

    ids = [i for i in set(capture_ids) if i]
    if not ids:
        return {}
    return {cid: key_of(cid, source, start, end) for cid, source, start, end in
            Capture.objects.filter(id__in=ids).values_list('id', 'imagery_source', 'imagery_start', 'imagery_end')}


def _lse(a, axis):
    m = np.max(a, axis=axis, keepdims=True)
    return np.squeeze(m, axis=axis) + np.log(np.sum(np.exp(a - m), axis=axis))


def exists_message(tables):
    """log P(this look's hits and misses | absent, present).

    ``tables`` are the look's stored hit / miss tables, each log P(detection | the image does
    not show it, shows it)."""
    seen = np.sum(np.asarray(tables, dtype=float).reshape(-1, 2), axis=0)
    s, h = priors.LOOK_SHOWS_IF_ABSENT, priors.LOOK_HIDES_IF_PRESENT
    shows = np.log([[1 - s, s], [h, 1 - h]])  # rows: absent, present; columns: not shown, shown
    return _lse(shows + seen[None, :], axis=1)


def exists_limits():
    """(lowest, highest) P(present) one look can give from an even prior."""
    s, h = priors.LOOK_SHOWS_IF_ABSENT, priors.LOOK_HIDES_IF_PRESENT
    return h / (h + 1 - s), (1 - h) / (1 - h + s)


def category_message(readings):
    """log P(this look's detections | category), up to a constant.

    ``readings`` is one log table per detection. Detections naming the same top category are
    one reading (their mean); each distinct reading is weighted by the chance that the others
    are misreadings of it."""
    r = np.asarray(readings, dtype=float)
    if r.ndim == 1:
        return r
    n, k = r.shape
    if n == 1:
        return r[0]
    top = r.argmax(axis=1)
    e = priors.LOOK_REREAD_ERROR
    agree, differ = math.log(1 - e), math.log(e / max(k - 1, 1))
    means, weights = [], []
    for label in np.unique(top):
        members = r[top == label]
        means.append(members.mean(axis=0))
        weights.append(len(members) * agree + (n - len(members)) * differ)
    weights = np.asarray(weights)
    weights = weights - _lse(weights, axis=0)
    return _lse(np.asarray(means) + weights[:, None], axis=0)


class Pool:
    """Collects the unary factors of some entities by look, then hands back one message per look.

    ``add`` returns False for a factor that is not part of a look (feedback, field readings,
    pairwise priors): the caller counts it directly, as before."""

    def __init__(self, look_of):
        self.look_of = look_of
        self.exists = {}     # (entity, look) -> [(observed_at, table, kind, capture id)]
        self.category = {}   # (entity, look) -> {detection id: [observed_at, table]}

    def add(self, f, table):
        if len(f.entity_ids) != 1 or not f.capture_id:
            return False
        look = self.look_of.get(f.capture_id)
        if look is None:
            return False
        key = (f.entity_ids[0], look)
        if f.kind in ('hit', 'miss'):
            self.exists.setdefault(key, []).append((f.observed_at, np.asarray(table, dtype=float), f.kind, f.capture_id))
            return True
        if f.kind in ('perceptual', 'geometry') and f.detection_id:
            slot = self.category.setdefault(key, {}).setdefault(f.detection_id, [f.observed_at, 0.0])
            slot[0] = max(slot[0], f.observed_at)
            slot[1] = slot[1] + np.asarray(table, dtype=float)
            return True
        return False

    def exists_messages(self):
        """[(entity, look, observed_at, message, rows)]."""
        return [(eid, look, max(r[0] for r in rows), exists_message([r[1] for r in rows]), rows)
                for (eid, look), rows in self.exists.items()]

    def category_messages(self):
        """[(entity, look, observed_at, message, readings)]."""
        out = []
        for (eid, look), dets in self.category.items():
            readings = [t for _, t in dets.values()]
            out.append((eid, look, max(at for at, _ in dets.values()), category_message(readings), readings))
        return out
