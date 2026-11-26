"""Say why each stored detection was in its capture, and what each capture told the store.

    python manage.py backfill_causes --taxonomy urban_v1            # dry run: report, roll back
    python manage.py backfill_causes --taxonomy urban_v1 --apply

Ingest records this as captures arrive (``fusion.first_sighting``, ``fusion.capture_reward``).
For captures stored before it did, this command goes through them in the order they were
stored and

  1. marks every live hit with its cause: new ground, newly resolvable, re-found, or a re-look
     at a finer or the same zoom;
  2. gives an entity first found on pixels an earlier capture had resolved that capture's
     miss, the factor ingest now writes, and re-infers those entities (snapshot cause
     ``retro_miss``);
  3. replays the captures with ``run_local_bp(through_capture=...)`` and stores each one's
     reward in ``summary['ingest']['reward']``, marked ``replayed``: the beliefs are those
     today's rules give from the captures up to that one, not the ones held at the time.

Nothing is deleted and no stored table is changed: hits gain a ``cause`` in their metadata and
the misses are new factors. Running it again adds nothing.
"""

import time
from collections import Counter

import numpy as np
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F

from deepgis_xr.apps.scene_store import detection_model, fusion
from deepgis_xr.apps.scene_store.models import Capture, Detection, Entity, Factor
from deepgis_xr.apps.web.world_sampler_api.urban_taxonomy import taxonomy_by_name

DB = fusion.DB
QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)


class Rollback(Exception):
    pass


def _q(values):
    return [round(float(v), 3) for v in np.quantile(np.asarray(values, dtype=float), QUANTILES)] if len(values) else []


class Command(BaseCommand):
    help = 'Record why each detection was in its capture and what each capture told the store (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--taxonomy', default='urban_v1')
        parser.add_argument('--chunk', type=int, default=1500)
        parser.add_argument('--apply', action='store_true', help='commit (default: report and roll back)')

    def handle(self, *args, taxonomy, chunk, apply, **opts):
        if not fusion.enabled():
            raise CommandError('observations database is not configured')
        t0 = time.perf_counter()
        tax = taxonomy_by_name(taxonomy)
        caps = list(Capture.objects.filter(taxonomy=taxonomy).order_by('id'))
        if not caps:
            self.stdout.write(f'no {taxonomy} captures')
            return
        live = Entity.objects.filter(taxonomy=taxonomy, retired_at__isnull=True)
        w = self.stdout.write
        try:
            with transaction.atomic(using=DB):
                absent = live.filter(p_exists__lt=0.5).count()
                causes, retro = self._causes(caps, taxonomy)
                w(f'{taxonomy}: {len(caps)} captures, {live.count()} live entities')
                w('live detections by cause: ' + ', '.join(f'{c} {causes[c]}' for c in fusion.CAUSES if causes[c]))
                ids = sorted({eid for eid, _ in retro})
                was = dict(live.filter(id__in=ids).values_list('id', 'p_exists'))
                fusion._bp_by_taxonomy(ids, cause='retro_miss', chunk=chunk)
                now = dict(live.filter(id__in=ids).values_list('id', 'p_exists'))
                w(f'misses put on earlier captures: {len(retro)} on {len(ids)} entities; '
                  f"their chance of a find, 5th to 95th percentile: {_q([p for _, p in retro])}")
                w(f'P(exists) of those entities: {_q(list(was.values()))} -> {_q(list(now.values()))}')
                w(f'  believed absent among them: {sum(p < 0.5 for p in was.values())} -> '
                  f'{sum(p < 0.5 for p in now.values())}; in the whole taxonomy: {absent} -> '
                  f'{live.filter(p_exists__lt=0.5).count()}')
                self._rewards(caps, tax, chunk)
                if not apply:
                    raise Rollback
        except Rollback:
            pass
        w(f"{'applied' if apply else 'dry run, rolled back'} in {time.perf_counter() - t0:.1f} s")

    def _causes(self, caps, taxonomy):
        """Tag hits and add the misses; returns (Counter of causes, [(entity id, p_detect)] of new misses)."""
        model = detection_model.active(taxonomy)
        have = set()
        for ids, cap_id in Factor.objects.filter(kind='miss', superseded_at__isnull=True, metadata__retro=True) \
                .values_list('entity_ids', 'capture_id'):
            have.add((ids[0], cap_id))
        counts, retro = Counter(), []
        for cap in caps:
            earlier = fusion.earlier_captures(cap)
            dets = list(Detection.objects.filter(capture=cap, gate='', association__entity__retired_at__isnull=True)
                        .select_related('association'))
            finest = fusion.finest_looks([d.association.entity_id for d in dets if d.association.method != 'new'],
                                         cap.id)
            hits = {f.detection_id: f for f in
                    Factor.objects.filter(kind='hit', capture=cap, superseded_at__isnull=True)}
            tagged, misses, extra = [], [], Counter()
            for d in dets:
                eid = d.association.entity_id
                if d.association.method == 'new':
                    shp = fusion._from_geos(d.geom)
                    area = fusion._metric(shp)[0]
                    cause, resolved = fusion.first_sighting(shp, area, set(d.sources), earlier)
                    for q in resolved:
                        if (eid, q.id) in have:
                            continue
                        table, why = detection_model.miss_evidence(
                            model, area_m2=area, gsd_m=q.gsd, first_gsd_m=cap.gsd_m, category=d.category)
                        misses.append(fusion._new_factor(
                            'miss', [eid], table, q.at, variables=[fusion.xvar(eid)], decays=False,
                            capture_id=q.id, metadata=dict(why, retro=True, found_by=cap.id)))
                        have.add((eid, q.id))
                        extra[eid] += 1
                        retro.append((eid, why['p_detect']))
                else:
                    cause = fusion.relook_cause(cap.gsd_m, finest.get(eid))
                counts[cause] += 1
                hit = hits.get(d.id)
                if hit is not None and hit.metadata.get('cause') != cause:
                    hit.metadata = dict(hit.metadata, cause=cause)
                    tagged.append(hit)
            Factor.objects.bulk_update(tagged, ['metadata'], batch_size=500)
            Factor.objects.bulk_create(misses, batch_size=500)
            by_n = {}
            for eid, n in extra.items():
                by_n.setdefault(n, []).append(eid)
            for n, eids in by_n.items():
                Entity.objects.filter(id__in=eids).update(n_misses=F('n_misses') + n)
        return counts, retro

    def _beliefs(self, ids, chunk, through):
        out = {}
        for i in range(0, len(ids), chunk):
            got = fusion.run_local_bp(ids[i:i + chunk], write=False, through_capture=through).get('beliefs', {})
            out.update({eid: (b['posterior'], b['p_exists']) for eid, b in got.items()})
        return out

    def _rewards(self, caps, tax, chunk):
        """Replay the captures in stored order and keep each one's reward."""
        total, starts, n_done = Counter(), {c: [] for c in fusion.FIRST_SIGHTINGS}, 0
        bits = {c: 0.0 for c in fusion.CAUSES}
        previous, new, again = 0, 0.0, 0.0
        for cap in caps:
            ingest = dict(cap.summary.get('ingest') or {})
            if ingest.get('reward') and not ingest['reward'].get('replayed'):
                previous = cap.id  # recorded when it was ingested
                continue
            causes, n_retro = {}, 0
            for kind, ids, meta in Factor.objects.filter(capture=cap, kind__in=('hit', 'miss'),
                                                         superseded_at__isnull=True) \
                    .values_list('kind', 'entity_ids', 'metadata'):
                if kind == 'hit':
                    causes[ids[0]] = meta.get('cause') or 'relook_same'
                elif not meta.get('retro'):
                    causes.setdefault(ids[0], 'missed')
            chances = {}
            for ids, meta in Factor.objects.filter(kind='miss', superseded_at__isnull=True,
                                                   metadata__found_by=cap.id).values_list('entity_ids', 'metadata'):
                chances.setdefault(ids[0], []).append(meta.get('p_detect') or 0.0)
            n_retro = sum(len(ps) for ps in chances.values())
            ids = sorted(causes)
            known = [eid for eid in ids if causes[eid] not in fusion.FIRST_SIGHTINGS]
            before = self._beliefs(known, chunk, previous)
            after = self._beliefs(ids, chunk, cap.id)
            reward = fusion.capture_reward(
                tax.n, causes, before, after, n_retro_misses=n_retro,
                second_try={eid: fusion.seen_before(ps) for eid, ps in chances.items()},
                ground_ha=fusion.ground_read(fusion._from_geos(cap.footprint), cap.gsd_m, cap.sources,
                                             fusion.earlier_captures(cap)))
            reward['replayed'] = True
            ingest['reward'] = reward
            Capture.objects.filter(id=cap.id).update(summary=dict(cap.summary, ingest=ingest))
            for eid, cause in causes.items():
                if cause in starts and eid in after:
                    starts[cause].append(after[eid][1])
            for cause, row in reward['by_cause'].items():
                total[cause] += row['n']
                bits[cause] += row['bits']
            new += reward['bits_new']
            again += reward['by_cause'].get('re_found', {}).get('expected_before', 0.0)
            n_done += 1
            previous = cap.id
        w = self.stdout.write
        w(f'rewards replayed for {n_done} captures (category bits by cause):')
        all_bits = sum(bits.values()) or 1.0
        for cause in fusion.CAUSES:
            if total[cause]:
                w(f'  {cause:17s} {total[cause]:6d} objects  {bits[cause]:9.1f} bits  {bits[cause] / all_bits:6.1%}')
        w(f'  of the re-found objects an earlier look should have found {again:.0f}; '
          f'bits earlier captures could not be expected to give: {new:.1f} ({new / all_bits:.1%})')
        w('P(exists) at the first sighting, 5th to 95th percentile:')
        for cause, values in starts.items():
            if values:
                w(f'  {cause:17s} {_q(values)}  (n {len(values)})')
