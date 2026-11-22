"""Incremental fusion of SceneGraphs into the spatiotemporal factor graph.

``ingest_scene_graph`` stores one capture, associates its detections with
existing entities (IoU, then centroid distance for small objects), writes
perceptual / existence / context factors, and re-runs loopy BP over the
touched entities only. Entities outside that neighbourhood that share a
factor enter as fixed priors (their stored posterior), so the cost of an
update scales with the capture, not with the size of the world.

Category is static per entity. Existence is a Markov chain: every stored
hit / miss / existence-feedback factor on ``x<id>`` is placed on its own
state at its ``observed_at``, and consecutive states are linked by a
transition that forgets toward 0.5 with the category's half-life. Those
temporal links are derived from timestamps at inference time rather than
stored, so late-arriving captures and as-of queries need no rewiring.

``run_local_bp`` is also the time-travel query: with ``at`` in the past it
uses only factors observed and valid then.
"""

import hashlib
import math
import time
from datetime import datetime, timezone as dt_timezone

import numpy as np
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, Point, Polygon
from django.db import connections, transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from shapely import STRtree
from shapely import wkb as shapely_wkb
from shapely.geometry import Polygon as ShPolygon
from shapely.validation import make_valid

from deepgis_xr.apps.web.world_sampler_api.urban_taxonomy import taxonomy_by_name

from . import inference, priors
from .models import (
    Association, BeliefSnapshot, Capture, Claim, Detection, Entity, Factor, Feedback, KernelRun, Potential,
)

DB = 'observations'
SNAPSHOT_DELTA = 0.02


def enabled():
    return DB in settings.DATABASES


def cvar(entity_id):
    return f'c{entity_id}'


def xvar(entity_id):
    return f'x{entity_id}'


def _shape(ring):
    """A clean shapely polygon from a [(lon, lat), ...] ring, or None."""
    if not ring or len(ring) < 3:
        return None
    try:
        shp = ShPolygon([(float(p[0]), float(p[1])) for p in ring])
    except Exception:
        return None
    if not shp.is_valid:
        shp = make_valid(shp)
    if shp.geom_type != 'Polygon':
        parts = [g for g in getattr(shp, 'geoms', []) if g.geom_type == 'Polygon']
        shp = max(parts, key=lambda g: g.area) if parts else None
    if shp is None or shp.is_empty or shp.area <= 0:
        return None
    return shp


def _geos(shp):
    return GEOSGeometry(shp.wkt, srid=4326)


def _from_geos(geom):
    return shapely_wkb.loads(bytes(geom.wkb))


def _iou(a, b):
    if not a.intersects(b):
        return 0.0
    inter = a.intersection(b).area
    return inter / (a.area + b.area - inter) if inter > 0 else 0.0


def _centroid_dist_m(a, b):
    ca, cb = a.centroid, b.centroid
    k = math.cos(math.radians((ca.y + cb.y) / 2))
    return math.hypot((ca.x - cb.x) * 111320 * k, (ca.y - cb.y) * 111320)


def _parse_time(value, fallback):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt_timezone.utc)
    parsed = parse_datetime(value) if isinstance(value, str) else None
    if parsed is None:
        return fallback
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt_timezone.utc)


def _posterior_vector(raw, tax):
    """kernelcal writes ``[{category, p}, ...]``; accept that, a dict, or a plain list."""
    if isinstance(raw, dict):
        vec = [raw.get(c) or 0.0 for c in tax.categories]
    elif isinstance(raw, list) and raw and isinstance(raw[0], dict):
        by_cat = {str(d.get('category')): d.get('p') or 0.0 for d in raw}
        vec = [by_cat.get(c, 0.0) for c in tax.categories]
    elif isinstance(raw, list) and len(raw) == tax.n:
        vec = raw
    else:
        return None
    vec = np.asarray(vec, dtype=float)
    return vec if np.isfinite(vec).all() and vec.sum() > 0 else None


def _log_probs(p, eps=1e-6):
    p = np.clip(np.asarray(p, dtype=float), eps, None)
    return np.log(p / p.sum())


_ENTITY_COLUMNS = {
    'posterior': 'float8[]', 'category': 'varchar', 'score': 'float8', 'p_exists': 'float8',
    'n_hits': 'int', 'n_misses': 'int', 'last_seen': 'timestamptz', 'first_seen': 'timestamptz',
    'sources': 'varchar[]', 'geom': 'geometry',
}


def _update_entities(entities, fields):
    """One ``UPDATE ... FROM (VALUES ...)``; Django's bulk_update builds a CASE per row and field."""
    if not entities:
        return
    from psycopg2.extras import execute_values

    def value(e, f):
        v = getattr(e, f)
        return v.ewkt if f == 'geom' else v

    sets = ', '.join(
        f"{f} = ST_GeomFromEWKT(v.{f})" if f == 'geom' else f"{f} = v.{f}::{_ENTITY_COLUMNS[f]}"
        for f in fields)
    sql = (f"UPDATE sg_entity e SET {sets}, updated_at = now() "
           f"FROM (VALUES %s) AS v(id, {', '.join(fields)}) WHERE e.id = v.id")
    with connections[DB].cursor() as cur:
        execute_values(cur.cursor, sql, [(e.id, *(value(e, f) for f in fields)) for e in entities],
                       page_size=1000)


def _new_factor(kind, entity_ids, table, at, **kw):
    """``table`` is an inline array or a shared :class:`Potential`."""
    variables = kw.pop('variables')
    shared = table if isinstance(table, Potential) else None
    return Factor(
        kind=kind, variables=variables, entity_ids=list(entity_ids),
        log_table=None if shared else np.asarray(table, dtype=float).tolist(), potential=shared,
        valid=DateTimeTZRange(at, None), observed_at=at, **kw,
    )


def _shared_potential(name, table):
    table = np.round(np.asarray(table, dtype=float), 9)
    digest = hashlib.sha1(table.tobytes() + str(table.shape).encode()).hexdigest()[:16]
    pot, _ = Potential.objects.get_or_create(key=f'{name}:{digest}', defaults={'log_table': table.tolist()})
    return pot


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def ingest_scene_graph(sg, *, session_id, taxonomy_name, user_id=None, artifact_path='',
                       kernel_meta=None, captured_at=None, infer=True):
    """Store one SceneGraph dict and fold it into the world model."""
    t0 = time.perf_counter()
    if Capture.objects.filter(session_id=session_id).exists():
        return {'status': 'exists', 'session_id': session_id}
    tax = taxonomy_by_name(taxonomy_name)
    viewport = sg.get('viewport') or {}
    meta = viewport.get('capture_metadata') or {}
    at = _parse_time(captured_at or meta.get('captured_at'), timezone.now())

    corners = meta.get('world_corners')
    footprint = _shape(corners) if corners else None
    if footprint is None and viewport.get('bbox_geo'):
        w, s, e, n = viewport['bbox_geo']
        footprint = ShPolygon([(w, n), (e, n), (e, s), (w, s)])
    if footprint is None:
        return {'status': 'skipped', 'reason': 'no viewport footprint'}

    dets = []
    for node in sg.get('nodes') or []:
        shp = _shape((node.get('region') or {}).get('geo_polygon'))
        post = _posterior_vector(node.get('category_posterior'), tax)
        if shp is None or post is None:
            continue
        dets.append((node, shp, post / post.sum()))

    cam = meta.get('camera') or {}
    fm = sg.get('fusion_metadata') or {}
    sources = sorted({s for node, _, _ in dets for s in (node.get('sources') or [])})

    with transaction.atomic(using=DB):
        cap = Capture.objects.create(
            session_id=session_id, captured_at=at, user_id=user_id, taxonomy=tax.name,
            footprint=_geos(footprint),
            camera=Point(float(cam['lon']), float(cam['lat']), srid=4326) if 'lon' in cam and 'lat' in cam else None,
            camera_alt_m=cam.get('alt'), camera_pose=cam,
            image_size=list(viewport.get('image_size') or [])[:2] or None,
            sources=sources, artifact_path=artifact_path or '',
            summary={'per_kernel_claim_counts': fm.get('per_kernel_claim_counts') or {}},
        )
        counts = fm.get('per_kernel_claim_counts') or {}
        KernelRun.objects.bulk_create([
            KernelRun(capture=cap, kernel_kind=kind, n_claims=int(n or 0),
                      model=str((kernel_meta or {}).get(kind, {}).get('model') or ''),
                      params=(kernel_meta or {}).get(kind, {}).get('params') or {})
            for kind, n in counts.items()
        ])

        det_rows = Detection.objects.bulk_create([
            Detection(capture=cap, node_id=str(node.get('id') or ''), observed_at=at, geom=_geos(shp),
                      category=tax.name_of(int(np.argmax(post))), posterior=post.tolist(),
                      score=float(post.max()), sources=list(node.get('sources') or []))
            for node, shp, post in dets
        ])
        claims = []
        for (node, _, _), row in zip(dets, det_rows):
            for c in node.get('claims') or []:
                cshp = _shape(c.get('geo_polygon'))
                claims.append(Claim(detection=row, source_id=str(c.get('source_id') or ''),
                                    native_label=str(c.get('native_label') or '')[:80],
                                    score=float(c.get('score') or 0.0),
                                    geom=_geos(cshp) if cshp is not None else None))
        Claim.objects.bulk_create(claims, batch_size=500)

        # Data association against entities already under this footprint.
        cands = list(Entity.objects.filter(taxonomy=tax.name, geom__intersects=cap.footprint))
        cand_shp = {e.id: _from_geos(e.geom) for e in cands}
        cand_tree = STRtree([cand_shp[e.id] for e in cands]) if cands else None
        pad = priors.ASSOC_CENTROID_M / 111320.0 * 2
        pairs = []
        for di, (_, shp, _) in enumerate(dets):
            near = cand_tree.query(shp.buffer(pad)) if cand_tree is not None else []
            for ci in near:
                e = cands[int(ci)]
                es = cand_shp[e.id]
                iou = _iou(shp, es)
                if iou >= priors.ASSOC_IOU:
                    pairs.append((iou, 'iou', di, e.id))
                elif max(shp.area, es.area) <= 4 * min(shp.area, es.area) and \
                        _centroid_dist_m(shp, es) <= priors.ASSOC_CENTROID_M:
                    pairs.append((0.0, 'centroid', di, e.id))
        pairs.sort(key=lambda p: (p[1] != 'iou', -p[0]))
        det_entity, used = {}, set()
        for iou, method, di, eid in pairs:
            if di in det_entity or eid in used:
                continue
            det_entity[di] = (eid, iou, method)
            used.add(eid)

        by_id = {e.id: e for e in cands}
        new_dis = [di for di in range(len(dets)) if di not in det_entity]
        new_rows = Entity.objects.bulk_create([
            Entity(taxonomy=tax.name, category=det_rows[di].category, posterior=det_rows[di].posterior,
                   score=det_rows[di].score, p_exists=0.5, geom=det_rows[di].geom,
                   first_seen=at, last_seen=at, n_hits=1, sources=det_rows[di].sources)
            for di in new_dis
        ])
        for di, e in zip(new_dis, new_rows):
            det_entity[di] = (e.id, None, 'new')
            by_id[e.id] = e

        factors, assocs = [], []
        for di, (eid, iou, method) in det_entity.items():
            row, post = det_rows[di], dets[di][2]
            e = by_id[eid]
            assocs.append(Association(entity_id=eid, detection=row, iou=iou, method=method))
            factors.append(_new_factor('perceptual', [eid], _log_probs(post), at, variables=[cvar(eid)],
                                       capture=cap, detection=row,
                                       metadata={'score': row.score, 'sources': row.sources}))
            factors.append(_new_factor('hit', [eid], priors.HIT_TABLE, at, variables=[xvar(eid)],
                                       decays=False, capture=cap, detection=row))
            if method != 'new':
                e.n_hits += 1
                if at >= e.last_seen:
                    e.last_seen, e.geom = at, row.geom
                e.first_seen = min(e.first_seen, at)
                e.sources = sorted(set(e.sources) | set(row.sources))

        # Misses: covered by this footprint, previously seen by a kernel that ran here, not matched now.
        missed = []
        for e in cands:
            if e.id in used or not set(e.sources) & set(sources):
                continue
            es = cand_shp[e.id]
            if es.intersection(footprint).area < priors.MISS_COVERAGE * es.area:
                continue
            factors.append(_new_factor('miss', [e.id], priors.MISS_TABLE, at, variables=[xvar(e.id)],
                                       decays=False, capture=cap))
            e.n_misses += 1
            missed.append(e.id)

        # Context (adjacency) and containment between this capture's entities, once per pair.
        node_entity = {str(dets[di][0].get('id')): det_entity[di][0] for di in det_entity}
        touched = {eid for eid, _, _ in det_entity.values()}
        have = {(f.kind, tuple(f.entity_ids)) for f in
                Factor.objects.filter(kind__in=['context', 'contains'], entity_ids__overlap=list(touched))
                .only('kind', 'entity_ids')}
        ctx = _shared_potential(f'context:{tax.name}', priors.context_table(tax))
        inside = _shared_potential(f'contains:{tax.name}', priors.contains_table(tax))
        edges = sorted(sg.get('edges') or [],
                       key=lambda e: (e.get('attributes') or {}).get('centroid_distance', 1.0))
        degree = {}
        for edge in edges:
            a, b = node_entity.get(str(edge.get('source'))), node_entity.get(str(edge.get('target')))
            if a is None or b is None or a == b:
                continue
            if degree.get(a, 0) >= priors.CONTEXT_DEGREE_CAP or degree.get(b, 0) >= priors.CONTEXT_DEGREE_CAP:
                continue
            key = ('context', tuple(sorted((a, b))))
            if key in have:
                continue
            have.add(key)
            degree[a], degree[b] = degree.get(a, 0) + 1, degree.get(b, 0) + 1
            factors.append(_new_factor('context', key[1], ctx, at, variables=[cvar(i) for i in key[1]],
                                       decays=False, capture=cap))
        det_tree = STRtree([shp for _, shp, _ in dets]) if dets else None
        for pi, (_, pshp, _) in enumerate(dets):
            for ci in det_tree.query(pshp, predicate='intersects'):
                ci = int(ci)
                cshp = dets[ci][1]
                if pi == ci or cshp.area > 0.5 * pshp.area:
                    continue
                if pshp.intersection(cshp).area < 0.8 * cshp.area:
                    continue
                parent, child = det_entity[pi][0], det_entity[ci][0]
                key = ('contains', (parent, child))
                if parent == child or key in have:
                    continue
                have.add(key)
                factors.append(_new_factor('contains', key[1], inside, at,
                                           variables=[cvar(parent), cvar(child)], decays=False, capture=cap))

        Association.objects.bulk_create(assocs)
        Factor.objects.bulk_create(factors, batch_size=500)
        new_ids = {e.id for e in new_rows}
        _update_entities([by_id[eid] for eid in (touched | set(missed)) - new_ids],
                         ['n_hits', 'n_misses', 'last_seen', 'first_seen', 'geom', 'sources'])

        bp = run_local_bp(touched | set(missed), cause='capture', capture=cap) if infer else None

    summary = {
        'status': 'ok', 'capture_id': cap.id, 'n_detections': len(det_rows),
        'n_new_entities': len(new_rows), 'n_matched': len(det_rows) - len(new_rows),
        'n_missed': len(missed), 'n_factors': len(factors),
        'elapsed_ms': int((time.perf_counter() - t0) * 1000), 'bp': bp,
    }
    Capture.objects.filter(id=cap.id).update(summary=dict(cap.summary, ingest=summary))
    return summary


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def _active_factors(entity_ids, at):
    return Factor.objects.filter(
        Q(superseded_at__isnull=True) | Q(superseded_at__gt=at),
        entity_ids__overlap=list(entity_ids), valid__contains=at, observed_at__lte=at,
    )


def run_local_bp(entity_ids, *, at=None, cause='refresh', capture=None, feedback=None, write=True,
                 max_iter=30, damping=0.5, tol=1e-4):
    """Inference over ``entity_ids`` with every factor touching them.

    Category: loopy BP over unary + pairwise factors. Existence: exact
    forward filter along each entity's chain, ending at ``at``.

    Neighbours reached only through a pairwise factor are boundary
    variables: their prior is their stored belief and nothing else.
    Returns diagnostics, plus ``beliefs`` when ``write`` is False.
    """
    t0 = time.perf_counter()
    ids = set(int(i) for i in entity_ids)
    if not ids:
        return {'n_entities': 0}
    at = at or timezone.now()
    factors = list(_active_factors(ids, at))
    all_ids = ids | {i for f in factors for i in f.entity_ids}
    ents = {e.id: e for e in Entity.objects.filter(id__in=all_ids)}
    if not ents:
        return {'n_entities': 0}
    tax = taxonomy_by_name(next(iter(ents.values())).taxonomy)

    index = {eid: i for i, eid in enumerate(ents)}
    unary = np.zeros((len(index), tax.n))
    for eid, e in ents.items():
        if eid not in ids:
            unary[index[eid]] = _log_probs(e.posterior)

    shared = {p.id: np.asarray(p.log_table, dtype=float)
              for p in Potential.objects.filter(id__in={f.potential_id for f in factors if f.potential_id})}
    existence = {eid: {} for eid in ids}
    pa, pb, ptables = [], [], []
    for f in factors:
        if any(i not in ents for i in f.entity_ids):
            continue
        table = shared[f.potential_id] if f.potential_id else np.asarray(f.log_table, dtype=float)
        if f.variables[0].startswith('x'):
            if f.entity_ids[0] in existence:
                by_time = existence[f.entity_ids[0]]
                by_time[f.observed_at] = by_time.get(f.observed_at, 0.0) + table
            continue
        if f.decays:
            age_h = (at - f.observed_at).total_seconds() / 3600.0
            table = table * priors.decay_weight(age_h, priors.PERCEPTUAL_HALF_LIFE_H)
        if len(f.entity_ids) == 1:
            unary[index[f.entity_ids[0]]] += table
        else:
            pa.append(index[f.entity_ids[0]])
            pb.append(index[f.entity_ids[1]])
            ptables.append(table)

    post_all, n_iter, converged, delta = inference.category_bp(
        unary, pa, pb, np.asarray(ptables).reshape(len(ptables), tax.n, tax.n),
        max_iter=max_iter, damping=damping, tol=tol)

    beliefs = {}
    for eid in ids:
        if eid not in ents:
            continue
        post = post_all[index[eid]]
        half_life = priors.existence_half_life_h(tax.name_of(int(np.argmax(post))))
        p_exists = inference.existence_marginal(
            sorted(existence[eid].items()), at, lambda dt: priors.persistence_table(dt, half_life))
        beliefs[eid] = {
            'posterior': post, 'category': tax.name_of(int(np.argmax(post))),
            'score': float(post.max()), 'p_exists': p_exists,
        }

    out = {
        'n_entities': len(ids), 'n_boundary': len(all_ids - ids), 'n_factors': len(factors),
        'n_pairwise': len(pa), 'n_iter': n_iter, 'converged': converged, 'max_delta': round(delta, 6),
        'elapsed_ms': int((time.perf_counter() - t0) * 1000),
    }
    if not write:
        out['beliefs'] = beliefs
        return out

    updated, snaps = [], []
    for eid, b in beliefs.items():
        e = ents[eid]
        old = np.asarray(e.posterior, dtype=float)
        moved = old.shape != b['posterior'].shape or \
            float(np.abs(old - b['posterior']).max()) > SNAPSHOT_DELTA or \
            abs(e.p_exists - b['p_exists']) > SNAPSHOT_DELTA
        e.posterior, e.category = b['posterior'].tolist(), b['category']
        e.score, e.p_exists = b['score'], b['p_exists']
        updated.append(e)
        if moved or cause == 'feedback':
            snaps.append(BeliefSnapshot(entity=e, at=at, category=e.category, posterior=e.posterior,
                                        p_exists=e.p_exists, cause=cause, capture=capture, feedback=feedback))
    _update_entities(updated, ['posterior', 'category', 'score', 'p_exists'])
    BeliefSnapshot.objects.bulk_create(snaps)
    out['n_snapshots'] = len(snaps)
    return out


# ---------------------------------------------------------------------------
# Feedback, queries
# ---------------------------------------------------------------------------

def apply_feedback(entity_id, kind, *, category='', user_id=None, note=''):
    entity = Entity.objects.get(id=entity_id)
    tax = taxonomy_by_name(entity.taxonomy)
    if kind not in ('confirm', 'relabel', 'reject'):
        raise ValueError(f'unknown feedback kind {kind!r}')
    if kind == 'relabel' and category not in tax.categories:
        raise ValueError(f'{category!r} is not a {tax.name} category')
    now = timezone.now()
    with transaction.atomic(using=DB):
        old = Feedback.objects.filter(entity=entity, user_id=user_id, superseded_at__isnull=True)
        Factor.objects.filter(feedback__in=old, superseded_at__isnull=True).update(superseded_at=now)
        old.update(superseded_at=now)
        fb = Feedback.objects.create(entity=entity, user_id=user_id, kind=kind,
                                     category=category if kind == 'relabel' else entity.category, note=note)
        rows = [_new_factor('feedback', [entity.id], priors.feedback_exists_table(kind != 'reject'), now,
                            variables=[xvar(entity.id)], decays=False, feedback=fb)]
        if kind != 'reject':
            rows.append(_new_factor('feedback', [entity.id], priors.feedback_category_table(tax, fb.category), now,
                                    variables=[cvar(entity.id)], decays=False, feedback=fb))
        Factor.objects.bulk_create(rows)
        bp = run_local_bp([entity.id], at=now, cause='feedback', feedback=fb)
    entity.refresh_from_db()
    return fb, entity, bp


def entity_to_dict(e, belief=None):
    b = belief or {}
    post = b.get('posterior', e.posterior)
    return {
        'id': e.id, 'taxonomy': e.taxonomy,
        'category': b.get('category', e.category), 'score': round(float(b.get('score', e.score)), 4),
        'p_exists': round(float(b.get('p_exists', e.p_exists)), 4),
        'posterior': [round(float(p), 4) for p in post],
        'first_seen': e.first_seen.isoformat(), 'last_seen': e.last_seen.isoformat(),
        'n_hits': e.n_hits, 'n_misses': e.n_misses, 'sources': e.sources,
        'geo_polygon': [list(p) for p in e.geom.coords[0]],
    }


def entities_in_bbox(bbox, *, at=None, taxonomy=None, min_p_exists=0.0, limit=2000):
    """Entities intersecting ``(west, south, east, north)``; beliefs recomputed at ``at`` if given."""
    qs = Entity.objects.filter(geom__intersects=Polygon.from_bbox(bbox))
    if taxonomy:
        qs = qs.filter(taxonomy=taxonomy)
    if at is not None:
        qs = qs.filter(first_seen__lte=at)
    ents = list(qs.order_by('-last_seen')[:limit])
    beliefs, bp = {}, None
    if at is not None and ents:
        by_tax = {}
        for e in ents:
            by_tax.setdefault(e.taxonomy, []).append(e.id)
        bp = {}
        for name, ids in by_tax.items():
            r = run_local_bp(ids, at=at, write=False)
            beliefs.update(r.pop('beliefs', {}))
            bp[name] = r
    out = [entity_to_dict(e, beliefs.get(e.id)) for e in ents]
    return [d for d in out if d['p_exists'] >= min_p_exists], bp


def source_reliability(taxonomy):
    """Counts of (source, native label, user-confirmed category): the Q_s refit signal."""
    rows = (Claim.objects
            .filter(detection__association__entity__feedback__superseded_at__isnull=True,
                    detection__association__entity__feedback__kind__in=['confirm', 'relabel'],
                    detection__association__entity__taxonomy=taxonomy)
            .values_list('source_id', 'native_label', 'detection__association__entity__feedback__category'))
    counts = {}
    for source, label, truth in rows:
        counts.setdefault(source, {}).setdefault(label, {}).setdefault(truth, 0)
        counts[source][label][truth] += 1
    return counts
