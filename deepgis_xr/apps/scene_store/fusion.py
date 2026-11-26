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

Evidence is dated in world time: a capture's factors carry the date its
imagery was acquired when the page reports one, not the moment the view
was taken. Looking again at the same imagery therefore adds detector
evidence at the same instant instead of pretending time has passed, and
that evidence is pooled: the captures of one image are one look and send
an entity one message, through what the image shows (see ``looks``).

``run_local_bp`` without ``at`` gives each entity's belief as last seen:
at its own newest evidence, with no decay after it. That is what entities
cache. With ``at`` it is the time-travel query: only factors observed and
valid by then, decayed to then (``at`` = now answers "is it still there").
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
from shapely.affinity import scale as shapely_scale
from shapely.geometry import Polygon as ShPolygon
from shapely.validation import make_valid

from deepgis_xr.apps.web.world_sampler_api.urban_taxonomy import taxonomy_by_name

from . import detection_model, inference, looks, priors
from .models import (
    Association, BeliefSnapshot, Capture, Claim, Detection, Entity, Factor, Feedback, KernelRun, Pose, Potential,
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


def _metric(shp):
    """(area m², perimeter m, compactness 4πA/P²) on a local equirectangular plane."""
    c = shp.centroid
    m = shapely_scale(shp, xfact=111320 * math.cos(math.radians(c.y)), yfact=111320, origin=c)
    area, perim = m.area, m.length
    return area, perim, (4 * math.pi * area / perim ** 2 if perim > 0 else 0.0)


def _parse_time(value, fallback):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt_timezone.utc)
    parsed = None
    if isinstance(value, str):
        try:
            parsed = parse_datetime(value) or datetime.fromisoformat(value.strip())  # also a bare date
        except ValueError:
            parsed = None
    if parsed is None:
        return fallback
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt_timezone.utc)


IMAGERY_EARLIEST = datetime(1990, 1, 1, tzinfo=dt_timezone.utc)
IMAGERY_VIEW_SLACK_S = 2 * 86400


def imagery_record(raw, viewed_at):
    """What a capture's pixels showed, from the page's ``viewport.imagery``.

    Returns ``source`` (layer ids joined by '+', e.g. 'bing:Aerial'), ``start`` / ``end``
    (the acquisition window, or None), ``observed_at`` (its middle, or None) and ``detail``
    (the cleaned record that is stored). Dates that are missing, reversed, before 1990 or
    after the view are dropped: the evidence is then dated when the view was taken.
    """
    out = {'source': '', 'start': None, 'end': None, 'observed_at': None, 'detail': {}}
    if not isinstance(raw, dict):
        return out
    layers = []
    for layer in (raw.get('layers') or [])[:8]:
        if isinstance(layer, dict) and layer.get('id'):
            row = {'id': str(layer['id'])[:60]}
            if isinstance(layer.get('alpha'), (int, float)):
                row['alpha'] = round(float(layer['alpha']), 2)
            layers.append(row)
    out['source'] = str(raw.get('source') or '+'.join(row['id'] for row in layers))[:120]
    detail = {'layers': layers}
    dates = raw.get('dates') if isinstance(raw.get('dates'), dict) else {}
    start, end = _parse_time(dates.get('start'), None), _parse_time(dates.get('end'), None)
    for key in ('zoom', 'points'):
        if isinstance(dates.get(key), (int, float)):
            detail[key] = int(dates[key])
    for key in ('method', 'looked_up_at'):
        if dates.get(key):
            detail[key] = str(dates[key])[:40]
    if 'uniform' in dates:
        detail['uniform'] = bool(dates['uniform'])
    if start and end and IMAGERY_EARLIEST <= start <= end and \
            (end - viewed_at).total_seconds() <= IMAGERY_VIEW_SLACK_S:
        out.update(start=start, end=end, observed_at=start + (end - start) / 2)
    elif start or end:
        detail['rejected_dates'] = [str(dates.get('start'))[:40], str(dates.get('end'))[:40]]
    out['detail'] = detail
    return out


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


def label_of(tax, post):
    """The category to show: the argmax, or unknown when no category is likely enough."""
    post = np.asarray(post, dtype=float)
    if post.max() < priors.LOW_CONFIDENCE and 'unknown' in tax.categories:
        return 'unknown'
    return tax.name_of(int(np.argmax(post)))


def _log_probs(p, eps=1e-6):
    p = np.clip(np.asarray(p, dtype=float), eps, None)
    return np.log(p / p.sum())


_ENTITY_COLUMNS = {
    'posterior': 'float8[]', 'category': 'varchar', 'score': 'float8', 'p_exists': 'float8',
    'n_hits': 'int', 'n_misses': 'int', 'last_seen': 'timestamptz', 'first_seen': 'timestamptz',
    'sources': 'varchar[]', 'geom': 'geometry',
}


ENTITY_AREA_SQL = """
UPDATE sg_entity e SET area_m2 = m.area
FROM (SELECT a.entity_id, percentile_cont(0.5) WITHIN GROUP (ORDER BY d.area_m2) AS area
      FROM sg_association a JOIN sg_detection d ON d.id = a.detection_id
      WHERE a.entity_id = ANY(%s) AND d.gate = ''
      GROUP BY a.entity_id) m
WHERE e.id = m.entity_id
"""

ENTITY_GEOM_SQL = """
UPDATE sg_entity e SET geom = latest.geom
FROM (SELECT DISTINCT ON (a.entity_id) a.entity_id, d.geom
      FROM sg_association a JOIN sg_detection d ON d.id = a.detection_id
      WHERE a.entity_id = ANY(%s) AND d.gate = ''
      ORDER BY a.entity_id, d.observed_at DESC) latest
WHERE e.id = latest.entity_id
"""


# Sighting count and world-time span from the detections that are still evidence.
ENTITY_SPAN_SQL = """
UPDATE sg_entity e SET n_hits = s.n, first_seen = s.first, last_seen = s.last
FROM (SELECT a.entity_id, count(*) AS n, min(d.observed_at) AS first, max(d.observed_at) AS last
      FROM sg_association a JOIN sg_detection d ON d.id = a.detection_id
      WHERE a.entity_id = ANY(%s) AND d.gate = ''
      GROUP BY a.entity_id) s
WHERE e.id = s.entity_id
"""


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
    """Store one SceneGraph dict and fold it into the world model.

    ``at`` is when the view was taken; ``obs`` is when the ground looked like that (the
    imagery's acquisition date when ``capture_metadata['imagery']`` gives one) and dates
    every detection and factor.
    """
    t0 = time.perf_counter()
    if Capture.objects.filter(session_id=session_id).exists():
        return {'status': 'exists', 'session_id': session_id}
    tax = taxonomy_by_name(taxonomy_name)
    viewport = sg.get('viewport') or {}
    meta = viewport.get('capture_metadata') or {}
    at = _parse_time(captured_at or meta.get('captured_at'), timezone.now())
    imagery = imagery_record(meta.get('imagery'), at)
    obs = imagery['observed_at'] or at

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

    footprint_m2 = _metric(footprint)[0]
    image_size = list(viewport.get('image_size') or [])[:2] or None
    gsd = math.sqrt(footprint_m2 / (image_size[0] * image_size[1])) \
        if image_size and len(image_size) == 2 and image_size[0] > 0 and image_size[1] > 0 else None
    shape = [_metric(shp) for _, shp, _ in dets]
    min_fragment_m2 = priors.FRAGMENT_MIN_PIXELS * gsd ** 2 if gsd else 0.0
    gates = ['frame' if footprint_m2 > 0 and area > priors.GATE_FOOTPRINT_FRAC * footprint_m2
             else 'fragment' if area < min_fragment_m2 else ''
             for area, _, _ in shape]
    live = [di for di in range(len(dets)) if not gates[di]]

    cam = meta.get('camera') or {}
    fm = sg.get('fusion_metadata') or {}
    sources = sorted({s for node, _, _ in dets for s in (node.get('sources') or [])})

    with transaction.atomic(using=DB):
        cap = Capture.objects.create(
            session_id=session_id, captured_at=at, user_id=user_id, taxonomy=tax.name,
            footprint=_geos(footprint),
            camera=Point(float(cam['lon']), float(cam['lat']), srid=4326) if 'lon' in cam and 'lat' in cam else None,
            camera_alt_m=cam.get('alt'), camera_pose=cam, image_size=image_size, gsd_m=gsd,
            sources=sources, artifact_path=artifact_path or '',
            summary={'per_kernel_claim_counts': fm.get('per_kernel_claim_counts') or {}},
            imagery_source=imagery['source'], imagery_start=imagery['start'], imagery_end=imagery['end'],
            imagery=imagery['detail'], observed_at=imagery['observed_at'],
        )
        if cap.camera is not None:
            Pose.objects.create(
                capture=cap, source='virtual_camera', at=at, position=cap.camera, alt_m=cam.get('alt'),
                heading_deg=cam.get('heading'), pitch_deg=cam.get('pitch'), roll_deg=cam.get('roll'),
                sigma_h_m=priors.VIRTUAL_CAMERA_SIGMA_H_M, sigma_v_m=priors.VIRTUAL_CAMERA_SIGMA_V_M,
                sigma_rot_deg=0.0)
        counts = fm.get('per_kernel_claim_counts') or {}
        KernelRun.objects.bulk_create([
            KernelRun(capture=cap, kernel_kind=kind, n_claims=int(n or 0),
                      model=str((kernel_meta or {}).get(kind, {}).get('model') or ''),
                      params=(kernel_meta or {}).get(kind, {}).get('params') or {})
            for kind, n in counts.items()
        ])

        det_rows = Detection.objects.bulk_create([
            Detection(capture=cap, node_id=str(node.get('id') or ''), observed_at=obs, geom=_geos(shp),
                      category=tax.name_of(int(np.argmax(post))), posterior=post.tolist(),
                      score=float(post.max()), sources=list(node.get('sources') or []), gate=gate)
            for (node, shp, post), gate in zip(dets, gates)
        ])
        with connections[DB].cursor() as cur:
            cur.execute('UPDATE sg_detection SET area_m2 = ST_Area(geom::geography) WHERE capture_id = %s', [cap.id])
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
        cands = list(Entity.objects.filter(taxonomy=tax.name, retired_at__isnull=True,
                                           geom__intersects=cap.footprint))
        cand_shp = {e.id: _from_geos(e.geom) for e in cands}
        cand_tree = STRtree([cand_shp[e.id] for e in cands]) if cands else None
        pad = priors.ASSOC_CENTROID_M / 111320.0 * 2
        pairs = []
        for di in live:
            shp = dets[di][1]
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
        new_dis = [di for di in live if di not in det_entity]
        new_rows = Entity.objects.bulk_create([
            Entity(taxonomy=tax.name, category=label_of(tax, det_rows[di].posterior),
                   posterior=det_rows[di].posterior,
                   score=det_rows[di].score, p_exists=0.5, geom=det_rows[di].geom,
                   first_seen=obs, last_seen=obs, n_hits=1, sources=det_rows[di].sources)
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
            factors.append(_new_factor('perceptual', [eid], _log_probs(post), obs, variables=[cvar(eid)],
                                       capture=cap, detection=row,
                                       metadata={'score': row.score, 'sources': row.sources}))
            area, _, compact = shape[di]
            geo = priors.geometry_table(tax, area, compact)
            if geo is not None:
                factors.append(_new_factor('geometry', [eid], geo, obs, variables=[cvar(eid)],
                                           capture=cap, detection=row,
                                           metadata={'area_m2': round(area, 2), 'compactness': round(compact, 3)}))
            factors.append(_new_factor('hit', [eid], priors.HIT_TABLE, obs, variables=[xvar(eid)],
                                       decays=False, capture=cap, detection=row))
            if method != 'new':
                e.n_hits += 1
                if obs >= e.last_seen:
                    e.last_seen, e.geom = obs, row.geom
                e.first_seen = min(e.first_seen, obs)
                e.sources = sorted(set(e.sources) | set(row.sources))

        # Misses: covered by this footprint, previously seen by a kernel that ran here, not matched
        # now, and large enough at this capture's resolution to have been seen. How much a miss
        # weighs is the fitted chance that this look would have found the entity (detection_model).
        min_miss_m2 = priors.MISS_MIN_PIXELS * gsd ** 2 if gsd else 0.0
        missed = []
        for e in cands:
            if e.id in used or not set(e.sources) & set(sources):
                continue
            es = cand_shp[e.id]
            if es.intersection(footprint).area < priors.MISS_COVERAGE * es.area:
                continue
            if (e.area_m2 if e.area_m2 is not None else _metric(es)[0]) < min_miss_m2:
                continue
            missed.append(e.id)
        model = detection_model.active(tax.name) if missed else None
        first_gsd = detection_model.first_gsd(missed) if model else {}
        for eid in missed:
            e = by_id[eid]
            table, why = detection_model.miss_evidence(
                model, area_m2=e.area_m2 if e.area_m2 is not None else _metric(cand_shp[eid])[0],
                gsd_m=gsd, first_gsd_m=first_gsd.get(eid), category=e.category)
            factors.append(_new_factor('miss', [eid], table, obs, variables=[xvar(eid)],
                                       decays=False, capture=cap, metadata=why))
            e.n_misses += 1

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
            factors.append(_new_factor('context', key[1], ctx, obs, variables=[cvar(i) for i in key[1]],
                                       decays=False, capture=cap))
        det_tree = STRtree([shp for _, shp, _ in dets]) if dets else None
        for pi in live:
            pshp = dets[pi][1]
            for ci in det_tree.query(pshp, predicate='intersects'):
                ci = int(ci)
                cshp = dets[ci][1]
                if pi == ci or ci not in det_entity or cshp.area > 0.5 * pshp.area:
                    continue
                if pshp.intersection(cshp).area < 0.8 * cshp.area:
                    continue
                parent, child = det_entity[pi][0], det_entity[ci][0]
                key = ('contains', (parent, child))
                if parent == child or key in have:
                    continue
                have.add(key)
                factors.append(_new_factor('contains', key[1], inside, obs,
                                           variables=[cvar(parent), cvar(child)], decays=False, capture=cap))

        Association.objects.bulk_create(assocs)
        with connections[DB].cursor() as cur:
            cur.execute(ENTITY_AREA_SQL, [sorted(touched)])
        Factor.objects.bulk_create(factors, batch_size=500)
        new_ids = {e.id for e in new_rows}
        _update_entities([by_id[eid] for eid in (touched | set(missed)) - new_ids],
                         ['n_hits', 'n_misses', 'last_seen', 'first_seen', 'geom', 'sources'])

        bp = run_local_bp(touched | set(missed), cause='capture', capture=cap) if infer else None

    summary = {
        'status': 'ok', 'capture_id': cap.id, 'n_detections': len(det_rows),
        'n_gated': len(det_rows) - len(live), 'n_fragments': gates.count('fragment'),
        'gsd_m': round(gsd, 3) if gsd else None,
        'observed_at': obs.isoformat(), 'imagery_source': imagery['source'] or None,
        'imagery_dated': imagery['observed_at'] is not None,
        'n_new_entities': len(new_rows), 'n_matched': len(live) - len(new_rows),
        'n_missed': len(missed), 'n_factors': len(factors),
        'elapsed_ms': int((time.perf_counter() - t0) * 1000), 'bp': bp,
    }
    Capture.objects.filter(id=cap.id).update(summary=dict(cap.summary, ingest=summary))
    return summary


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def _active_factors(entity_ids, at, known=None):
    """Factors about the world up to ``at`` (world time) that the store stands by at ``known``
    (record time, default now). The two clocks differ: evidence imaged in 2023 can be recorded,
    and later withdrawn, in 2026."""
    known = known or timezone.now()
    return Factor.objects.filter(
        Q(superseded_at__isnull=True) | Q(superseded_at__gt=known),
        entity_ids__overlap=list(entity_ids), valid__contains=at, observed_at__lte=at,
    )


def run_local_bp(entity_ids, *, at=None, cause='refresh', capture=None, feedback=None, write=True,
                 max_iter=30, damping=0.5, tol=1e-4, pool_looks=True):
    """Inference over ``entity_ids`` with every factor touching them.

    Category: loopy BP over unary + pairwise factors. Existence: exact
    forward filter along each entity's chain.

    Detections are pooled by look first (``looks``): the captures of one image send an entity
    one message through what that image shows, instead of one each. ``pool_looks=False``
    multiplies every detection in as its own observation, the rule before looks, for
    comparison only.

    Without ``at`` each entity's belief is as last seen: its category evidence is aged to
    its newest category evidence and its existence chain ends at its newest existence
    evidence, so nothing decays after the last look. Field readings count in full but are not
    a look: they do not move that time. With ``at`` (world time) only evidence up to then
    counts and everything is decayed to then.

    Neighbours reached only through a pairwise factor are boundary
    variables: their prior is their stored belief and nothing else.
    Returns diagnostics, plus ``beliefs`` when ``write`` is False.
    """
    t0 = time.perf_counter()
    ids = set(int(i) for i in entity_ids)
    if not ids:
        return {'n_entities': 0}
    now = timezone.now()
    last_seen = at is None
    factors = list(_active_factors(ids, at or now, known=now))
    newest_c, newest_x = {}, {}
    if last_seen:
        for f in factors:
            # A field reading answers one yes/no question about the surface. It is not a new look
            # at what the object is, so it does not make the imagery's answer any older.
            if len(f.entity_ids) == 1 and f.kind != 'field':
                newest = newest_x if f.variables[0].startswith('x') else newest_c
                eid = f.entity_ids[0]
                if eid not in newest or f.observed_at > newest[eid]:
                    newest[eid] = f.observed_at
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
    pool = looks.Pool(looks.keys(f.capture_id for f in factors) if pool_looks else {})
    for f in factors:
        if any(i not in ents for i in f.entity_ids):
            continue
        table = shared[f.potential_id] if f.potential_id else np.asarray(f.log_table, dtype=float)
        if pool.add(f, table):
            continue
        if f.variables[0].startswith('x'):
            if f.entity_ids[0] in existence:
                by_time = existence[f.entity_ids[0]]
                by_time[f.observed_at] = by_time.get(f.observed_at, 0.0) + table
            continue
        if f.decays:
            ref = at or (newest_c.get(f.entity_ids[0], now) if len(f.entity_ids) == 1 else now)
            age_h = (ref - f.observed_at).total_seconds() / 3600.0
            table = table * priors.decay_weight(age_h, priors.PERCEPTUAL_HALF_LIFE_H)
        if len(f.entity_ids) == 1:
            unary[index[f.entity_ids[0]]] += table
        else:
            pa.append(index[f.entity_ids[0]])
            pb.append(index[f.entity_ids[1]])
            ptables.append(table)
    # One message per look: its hits and misses on the existence chain at the look's date, its
    # detections' readings on the category, aged like any other perceptual evidence.
    for eid, _, seen, message, _ in pool.exists_messages():
        by_time = existence[eid]
        by_time[seen] = by_time.get(seen, 0.0) + message
    for eid, _, seen, message, _ in pool.category_messages():
        age_h = ((at or newest_c.get(eid, now)) - seen).total_seconds() / 3600.0
        unary[index[eid]] += message * priors.decay_weight(age_h, priors.PERCEPTUAL_HALF_LIFE_H)

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
            sorted(existence[eid].items()), at or newest_x.get(eid, now),
            lambda dt: priors.persistence_table(dt, half_life))
        beliefs[eid] = {
            'posterior': post, 'category': label_of(tax, post),
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
            snaps.append(BeliefSnapshot(entity=e, at=now, category=e.category, posterior=e.posterior,
                                        p_exists=e.p_exists, cause=cause, capture=capture, feedback=feedback))
    _update_entities(updated, ['posterior', 'category', 'score', 'p_exists'])
    BeliefSnapshot.objects.bulk_create(snaps)
    out['n_snapshots'] = len(snaps)
    return out


def _sig(v, digits=3):
    return float(f'{float(v):.{digits}g}')


def support_many(entities, include_field=False):
    """{entity id: what its belief rests on}.

    ``looks`` has one row per image the entity was captured on, newest first: how many captures
    showed it, how often it was found and missed, and what that look says on its own from an
    even prior (``exists``, ``category``). However many captures a look has, it counts once.
    ``other`` counts the evidence that is not a look: people's corrections, days of field
    readings, links to neighbours."""
    ents = {e.id: e for e in entities}
    if not ents:
        return {}
    factors = list(Factor.objects.filter(entity_ids__overlap=list(ents), superseded_at__isnull=True))
    caps = {c.id: c for c in Capture.objects.filter(id__in={f.capture_id for f in factors if f.capture_id})
            .only('id', 'imagery_source', 'imagery_start', 'imagery_end', 'captured_at')}
    look_of = {cid: looks.key_of(cid, c.imagery_source, c.imagery_start, c.imagery_end) for cid, c in caps.items()}
    first_cap = {}
    for cid in sorted(caps):
        first_cap.setdefault(look_of[cid], caps[cid])
    pool = looks.Pool(look_of)
    out = {eid: {'looks': {}, 'other': {}} for eid in ents}
    corrections = set()
    for f in factors:
        if f.log_table is not None and pool.add(f, f.log_table):
            continue
        if f.kind == 'field' and not include_field:
            continue
        if f.kind == 'feedback':  # one correction can hold two factors, on existence and on category
            if f.feedback_id in corrections:
                continue
            corrections.add(f.feedback_id)
        for eid in f.entity_ids:
            if eid in out:
                out[eid]['other'][f.kind] = out[eid]['other'].get(f.kind, 0) + 1

    def row(eid, look, seen):
        cap = first_cap[look]
        dated = not look.startswith('capture:')
        return out[eid]['looks'].setdefault(look, {
            'source': cap.imagery_source or None, 'identified': dated,
            'start': cap.imagery_start.isoformat() if dated else None,
            'end': cap.imagery_end.isoformat() if dated else None,
            'observed_at': seen.isoformat(), 'n_captures': 0, 'n_found': 0, 'n_missed': 0})

    for eid, look, seen, message, members in pool.exists_messages():
        r = row(eid, look, seen)
        odds = math.exp(float(message[1] - message[0]))
        r.update(n_captures=len({m[3] for m in members}), n_found=sum(m[2] == 'hit' for m in members),
                 n_missed=sum(m[2] == 'miss' for m in members),
                 exists={'p': round(odds / (1 + odds), 4), 'odds': _sig(odds)})
    for eid, look, seen, message, readings in pool.category_messages():
        tax = taxonomy_by_name(ents[eid].taxonomy)
        post = np.exp(message - message.max())
        post /= post.sum()
        best = int(np.argmax(post))
        row(eid, look, seen)['category'] = {
            'category': tax.name_of(best), 'p': round(float(post[best]), 4), 'n_readings': len(readings),
            'n_agree': sum(int(np.argmax(t)) == best for t in readings)}
    lo, hi = looks.exists_limits()
    for eid, s in out.items():
        s['looks'] = sorted(s['looks'].values(), key=lambda r: r['observed_at'], reverse=True)
        s['n_looks'] = len(s['looks'])
        s['one_look_p_exists'] = [round(lo, 3), round(hi, 3)]
    return out


def support(entity, include_field=False):
    return support_many([entity], include_field)[entity.id]


# ---------------------------------------------------------------------------
# Feedback, queries
# ---------------------------------------------------------------------------

def apply_feedback(entity_id, kind, *, category='', user_id=None, note='', observed_at=None):
    """A person's correction, as evidence dated ``observed_at`` in world time.

    The default is the entity's ``last_seen``: someone judging a label on the map is looking
    at the imagery the entity was last seen in, and says nothing about the ground since.
    Pass the time of the look for a correction made on the ground or on newer imagery.
    """
    entity = Entity.objects.get(id=entity_id)
    tax = taxonomy_by_name(entity.taxonomy)
    if kind not in ('confirm', 'relabel', 'reject'):
        raise ValueError(f'unknown feedback kind {kind!r}')
    if kind == 'relabel' and category not in tax.categories:
        raise ValueError(f'{category!r} is not a {tax.name} category')
    now = timezone.now()
    seen = min(observed_at or entity.last_seen, now)
    with transaction.atomic(using=DB):
        old = Feedback.objects.filter(entity=entity, user_id=user_id, superseded_at__isnull=True)
        Factor.objects.filter(feedback__in=old, superseded_at__isnull=True).update(superseded_at=now)
        old.update(superseded_at=now)
        fb = Feedback.objects.create(entity=entity, user_id=user_id, kind=kind,
                                     category=category if kind == 'relabel' else entity.category, note=note)
        rows = [_new_factor('feedback', [entity.id], priors.feedback_exists_table(kind != 'reject'), seen,
                            variables=[xvar(entity.id)], decays=False, feedback=fb)]
        if kind != 'reject':
            rows.append(_new_factor('feedback', [entity.id], priors.feedback_category_table(tax, fb.category), seen,
                                    variables=[cvar(entity.id)], decays=False, feedback=fb))
        Factor.objects.bulk_create(rows)
        bp = run_local_bp([entity.id], cause='feedback', feedback=fb)
    entity.refresh_from_db()
    return fb, entity, bp


def _neighbours(ids, factors):
    return {i for f in factors for i in f.entity_ids} - set(ids)


def _bp_by_taxonomy(ids, *, cause, chunk=1500):
    by_tax = {}
    for eid, name in Entity.objects.filter(id__in=ids, retired_at__isnull=True).values_list('id', 'taxonomy'):
        by_tax.setdefault(name, []).append(eid)
    for name, group in by_tax.items():
        for i in range(0, len(group), chunk):
            run_local_bp(group[i:i + chunk], cause=cause)
    return sum(len(g) for g in by_tax.values())


def retire_entities(entity_ids, reason, *, infer=True):
    """Take entities out of the world model without erasing them.

    Every factor touching them is superseded at one instant, which is also stamped on the
    entity, so ``restore_entities`` can undo exactly this retirement. Neighbours that
    shared a pairwise factor are re-inferred.
    """
    now = timezone.now()
    ids = list(Entity.objects.filter(id__in=list(entity_ids), retired_at__isnull=True).values_list('id', flat=True))
    if not ids:
        return {'n_retired': 0, 'n_neighbours': 0}
    with transaction.atomic(using=DB):
        factors = Factor.objects.filter(entity_ids__overlap=ids, superseded_at__isnull=True)
        neighbours = _neighbours(ids, factors.only('entity_ids'))
        n_factors = factors.update(superseded_at=now)
        Entity.objects.filter(id__in=ids).update(retired_at=now, retired_reason=reason[:120])
        n_bp = _bp_by_taxonomy(neighbours, cause='retire') if infer else 0
    return {'n_retired': len(ids), 'n_factors': n_factors, 'n_neighbours': n_bp, 'at': now.isoformat()}


def restore_entities(entity_ids, *, infer=True):
    """Undo ``retire_entities``: revive the factors superseded at each entity's retirement."""
    ents = list(Entity.objects.filter(id__in=list(entity_ids), retired_at__isnull=False))
    if not ents:
        return {'n_restored': 0}
    n_factors, ids = 0, [e.id for e in ents]
    with transaction.atomic(using=DB):
        for at in {e.retired_at for e in ents}:
            group = [e.id for e in ents if e.retired_at == at]
            n_factors += Factor.objects.filter(entity_ids__overlap=group, superseded_at=at).update(superseded_at=None)
        Entity.objects.filter(id__in=ids).update(retired_at=None, retired_reason='')
        touched = set(ids) | _neighbours(ids, Factor.objects.filter(entity_ids__overlap=ids,
                                                                    superseded_at__isnull=True).only('entity_ids'))
        n_bp = _bp_by_taxonomy(touched, cause='restore') if infer else 0
    return {'n_restored': len(ids), 'n_factors': n_factors, 'n_inferred': n_bp}


def entity_to_dict(e, belief=None):
    b = belief or {}
    post = b.get('posterior', e.posterior)
    best = int(np.argmax(post))
    return {
        'id': e.id, 'taxonomy': e.taxonomy,
        'category': b.get('category', e.category), 'score': round(float(b.get('score', e.score)), 4),
        'best_guess': {'category': taxonomy_by_name(e.taxonomy).name_of(best), 'p': round(float(post[best]), 4)},
        'p_exists': round(float(b.get('p_exists', e.p_exists)), 4),
        'posterior': [round(float(p), 4) for p in post],
        'first_seen': e.first_seen.isoformat(), 'last_seen': e.last_seen.isoformat(),
        'n_hits': e.n_hits, 'n_misses': e.n_misses, 'sources': e.sources,
        'area_m2': round(e.area_m2, 2) if e.area_m2 is not None else None,
        'geo_polygon': [list(p) for p in e.geom.coords[0]],
        'retired': {'at': e.retired_at.isoformat(), 'reason': e.retired_reason} if e.retired_at else None,
    }


def entities_in_bbox(bbox, *, at=None, taxonomy=None, min_p_exists=0.0, min_score=0.0, limit=2000):
    """Entities intersecting ``(west, south, east, north)``; beliefs recomputed at ``at`` if given."""
    qs = Entity.objects.filter(geom__intersects=Polygon.from_bbox(bbox), retired_at__isnull=True)
    if taxonomy:
        qs = qs.filter(taxonomy=taxonomy)
    if min_score > 0 and at is None:
        qs = qs.filter(score__gte=min_score)
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
    return [d for d in out if d['p_exists'] >= min_p_exists and d['score'] >= min_score], bp


def world_summary(bbox, *, taxonomy=None, limit=20000):
    """What the world model holds in a box: counts per category, how sure it is, and what
    the unknown entities most likely are."""
    qs = Entity.objects.filter(geom__intersects=Polygon.from_bbox(bbox), retired_at__isnull=True)
    if taxonomy:
        qs = qs.filter(taxonomy=taxonomy)
    rows = list(qs.values_list('taxonomy', 'category', 'score', 'posterior')[:limit])
    by_cat, guesses, bins = {}, {}, [0, 0, 0, 0]
    for tax_name, category, score, post in rows:
        by_cat[category] = by_cat.get(category, 0) + 1
        bins[min(3, int(score * 4))] += 1
        if category == 'unknown':
            best = int(np.argmax(post))
            name = taxonomy_by_name(tax_name).name_of(best)
            n, total = guesses.get(name, (0, 0.0))
            guesses[name] = (n + 1, total + float(post[best]))
    return {
        'n': len(rows), 'truncated': len(rows) == limit,
        'by_category': dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
        'n_unknown': by_cat.get('unknown', 0),
        'unknown_best_guess': [{'category': c, 'n': n, 'mean_p': round(t / n, 3)}
                               for c, (n, t) in sorted(guesses.items(), key=lambda kv: -kv[1][0])],
        'confidence_bins': [{'lo': i / 4, 'hi': (i + 1) / 4, 'n': n} for i, n in enumerate(bins)],
        'low_confidence': priors.LOW_CONFIDENCE,
    }


FIRST_VIEW_SQL = """
SELECT a.entity_id FROM sg_association a
  JOIN sg_detection d ON d.id = a.detection_id
  JOIN sg_capture c ON c.id = d.capture_id
 WHERE a.entity_id = ANY(%s) AND d.gate = ''
 GROUP BY a.entity_id HAVING min(c.captured_at) >= %s AND min(c.captured_at) < %s
"""


def imagery_dates(captures):
    """The distinct imagery a set of captures showed: [{source, start, end, n_captures}], dated first."""
    seen = {}
    for source, start, end in captures.values_list('imagery_source', 'imagery_start', 'imagery_end'):
        key = (source or None, start, end)
        seen[key] = seen.get(key, 0) + 1
    rows = [{'source': s, 'start': a.isoformat() if a else None, 'end': b.isoformat() if b else None,
             'n_captures': n} for (s, a, b), n in seen.items()]
    return sorted(rows, key=lambda r: (r['start'] is None, r['start'] or '', r['source'] or ''))


def world_changes(bbox, since, until=None, *, taxonomy=None, limit=1000, basis='imagery'):
    """Entities first seen in [since, until), and entities missed then that are believed gone.

    ``basis='imagery'`` reads the window in world time, the date the ground was imaged, so
    looking twice at the same imagery is not a change. ``basis='view'`` reads it by when the
    views were taken, which compares runs of the detector whatever they looked at.
    ``imagery`` lists what the captures here showed; with fewer than two dated acquisitions
    nothing can be said about change on the ground, and ``note`` says so.

    Misses count only where the camera could have resolved the object (see ``ingest``)."""
    if basis not in ('imagery', 'view'):
        raise ValueError("basis must be 'imagery' or 'view'")
    until = until or timezone.now()
    box = Polygon.from_bbox(bbox)
    live = Entity.objects.filter(geom__intersects=box, retired_at__isnull=True)
    captures = Capture.objects.filter(footprint__intersects=box)
    if taxonomy:
        live = live.filter(taxonomy=taxonomy)
        captures = captures.filter(taxonomy=taxonomy)
    misses = Factor.objects.filter(kind='miss', superseded_at__isnull=True, capture__footprint__intersects=box)
    if basis == 'view':
        with connections[DB].cursor() as cur:
            cur.execute(FIRST_VIEW_SQL, [list(live.values_list('id', flat=True)), since, until])
            appeared = live.filter(id__in=[r[0] for r in cur.fetchall()]).order_by('-first_seen')
        misses = misses.filter(capture__captured_at__gte=since, capture__captured_at__lt=until)
        n_captures = captures.filter(captured_at__gte=since, captured_at__lt=until).count()
    else:
        appeared = live.filter(first_seen__gte=since, first_seen__lt=until).order_by('-first_seen')
        misses = misses.filter(observed_at__gte=since, observed_at__lt=until)
        n_captures = captures.filter(
            Q(observed_at__gte=since, observed_at__lt=until)
            | Q(observed_at__isnull=True, captured_at__gte=since, captured_at__lt=until)).count()
    missed_ids = {ids[0] for ids in misses.values_list('entity_ids', flat=True)}
    gone = live.filter(id__in=missed_ids, p_exists__lt=0.5).order_by('p_exists')

    def pack(qs):
        rows = list(qs[:limit])
        counts = {}
        for e in rows:
            counts[e.category] = counts.get(e.category, 0) + 1
        return {'n': qs.count(), 'by_category': dict(sorted(counts.items(), key=lambda kv: -kv[1])),
                'entities': [entity_to_dict(e) for e in rows]}

    imagery = imagery_dates(captures)
    dated = [r for r in imagery if r['start']]
    note = None
    if basis == 'view':
        note = ('Compared by when the views were taken: differences are between runs of the detector '
                'and say nothing about the ground unless the imagery changed too.')
    elif len(dated) == 1 and len(imagery) == 1:
        note = (f"Every capture here shows the same imagery ({dated[0]['source']}, acquired "
                f"{dated[0]['start'][:10]} to {dated[0]['end'][:10]}), so nothing here is change on the ground.")
    elif len(dated) < 2:
        note = ('Fewer than two dated imagery acquisitions cover this area; captures without an '
                'imagery date are placed at the time they were viewed.')
    return {'since': since.isoformat(), 'until': until.isoformat(), 'basis': basis, 'n_captures': n_captures,
            'imagery': imagery, 'note': note, 'appeared': pack(appeared), 'gone': pack(gone)}


def _bits(p):
    p = np.asarray(p, dtype=float)
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum())


def review_queue(bbox, *, taxonomy=None, limit=20, scan=20000):
    """Entities a person's label would tell the store most about, best first.

    The value of a look is the uncertainty it removes: the entropy of the category
    posterior plus that of existence, in bits. Entities someone has already judged are
    left out."""
    qs = Entity.objects.filter(geom__intersects=Polygon.from_bbox(bbox), retired_at__isnull=True)
    if taxonomy:
        qs = qs.filter(taxonomy=taxonomy)
    judged = set(Feedback.objects.filter(superseded_at__isnull=True, entity__in=qs)
                 .values_list('entity_id', flat=True))
    scored = []
    for eid, post, p_exists in qs.values_list('id', 'posterior', 'p_exists')[:scan]:
        if eid in judged:
            continue
        cat = _bits(post)
        scored.append((cat + _bits([p_exists, 1 - p_exists]), cat, eid))
    scored.sort(reverse=True)
    top = scored[:limit]
    ents = {e.id: e for e in Entity.objects.filter(id__in=[t[2] for t in top])}
    out = []
    for value, cat, eid in top:
        d = entity_to_dict(ents[eid])
        d['value_bits'] = round(value, 3)
        d['category_bits'] = round(cat, 3)
        out.append(d)
    return {'n_candidates': len(scored), 'n_judged': len(judged), 'entities': out}


def nice_bin(span, target=25):
    """1, 2 or 5 x 10^k, about ``target`` bins across ``span`` (the panel's WorldSamplerUI.niceBin)."""
    if not span > 0:
        return 1.0
    raw = span / target
    p = 10.0 ** math.floor(math.log10(raw))
    m = raw / p
    return (1 if m <= 1 else 2 if m <= 2 else 5 if m <= 5 else 10) * p


def area_histogram(areas, *, bin_m2=None, max_m2=None):
    """Fixed-width bins from 0 to ``max_m2`` (default: the 99th percentile), plus an overflow count.

    ``bin_m2=None`` picks a round width giving about 25 bins.
    """
    a = np.asarray([v for v in areas if v is not None and np.isfinite(v)], dtype=float)
    if a.size == 0:
        return {'n': 0, 'bin_m2': bin_m2, 'bins': [], 'overflow': 0, 'stats': None}
    top = max_m2 if max_m2 else float(np.percentile(a, 99))
    bin_m2 = bin_m2 or nice_bin(top)
    n_bins = max(1, min(500, int(math.ceil(top / bin_m2))))
    top = n_bins * bin_m2
    counts, edges = np.histogram(a[a < top], bins=n_bins, range=(0.0, top))
    sig = lambda v: float(f'{float(v):.6g}')  # noqa: E731
    return {
        'n': int(a.size), 'bin_m2': sig(bin_m2),
        'bins': [{'lo': sig(lo), 'hi': sig(hi), 'n': int(c)}
                 for lo, hi, c in zip(edges[:-1], edges[1:], counts)],
        'overflow': int((a >= top).sum()),
        'stats': {k: sig(v) for k, v in (
            ('min', a.min()), ('p10', np.percentile(a, 10)), ('median', np.median(a)), ('mean', a.mean()),
            ('p90', np.percentile(a, 90)), ('max', a.max()))},
    }


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
