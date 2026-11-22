"""Spatiotemporal scene-graph store: association, existence, time travel, feedback."""

import json
from datetime import timedelta

import numpy as np
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone

from deepgis_xr.apps.scene_store import fusion
from deepgis_xr.apps.scene_store.models import Entity, Factor, Feedback
from deepgis_xr.apps.web.world_sampler_api.urban_taxonomy import URBAN_V1
from deepgis_xr.db_router import FieldReadingRouter

LON, LAT = -111.9435, 33.4260
M = 1 / 111320.0


def _square(cx_m, cy_m, half_m):
    k = 1 / np.cos(np.radians(LAT))
    x0, y0 = LON + cx_m * M * k, LAT + cy_m * M
    hx, hy = half_m * M * k, half_m * M
    return [[x0 - hx, y0 + hy], [x0 + hx, y0 + hy], [x0 + hx, y0 - hy], [x0 - hx, y0 - hy], [x0 - hx, y0 + hy]]


def _node(nid, category, ring, p=0.8):
    post = np.full(URBAN_V1.n, (1 - p) / (URBAN_V1.n - 1))
    post[URBAN_V1.index_of(category)] = p
    posterior = [{'category': c, 'p': float(v)} for c, v in zip(URBAN_V1.categories, post)]
    return {'id': nid, 'category': category, 'category_posterior': posterior, 'sources': ['sam3'],
            'region': {'geo_polygon': ring},
            'claims': [{'source_id': 'sam3', 'native_label': category, 'score': p, 'geo_polygon': ring}]}


def _scene(at, *, with_car=True, shift_m=0.0):
    nodes = [_node('b', 'building', _square(-40 + shift_m, 0, 15)),
             _node('r', 'road', _square(10 + shift_m, 0, 6))]
    if with_car:
        nodes.append(_node('v', 'vehicle', _square(10 + shift_m, 2, 1.5)))
    return {
        'viewport': {'image_size': [1000, 800], 'capture_metadata': {
            'world_corners': [p[:2] for p in _square(0, 0, 100)[:4]],
            'camera': {'lon': LON, 'lat': LAT, 'alt': 700}, 'captured_at': at.isoformat()}},
        'nodes': nodes,
        'edges': [{'source': 'v', 'target': 'r', 'relation': 'adjacent'}] if with_car else [],
        'fusion_metadata': {'per_kernel_claim_counts': {'sam3': len(nodes)}},
    }


class RouterTests(SimpleTestCase):
    def test_scene_store_only_migrates_on_observations(self):
        r = FieldReadingRouter()
        self.assertTrue(r.allow_migrate('observations', 'scene_store', 'entity'))
        self.assertFalse(r.allow_migrate('default', 'scene_store', 'entity'))
        self.assertFalse(r.allow_migrate('observations', 'web', 'scenegraph'))
        self.assertIsNone(r.allow_migrate('default', 'web', 'scenegraph'))


class InferenceTests(SimpleTestCase):
    def test_vectorised_bp_matches_kernelcal(self):
        from kernelcal.distinction_game.factor_graph import Factor as KcFactor, FactorGraph, loopy_bp
        from deepgis_xr.apps.scene_store.inference import category_bp

        rng = np.random.default_rng(0)
        n, k = 12, 5
        unary = rng.normal(size=(n, k))
        edges = [(i, j) for i in range(n) for j in range(i + 1, n) if rng.random() < 0.3]
        tables = rng.normal(scale=0.5, size=(len(edges), k, k))
        g = FactorGraph()
        for i in range(n):
            g.add_variable(i, k)
            g.add_factor(KcFactor(variables=(i,), log_table=unary[i]))
        for (i, j), t in zip(edges, tables):
            g.add_factor(KcFactor(variables=(i, j), log_table=t))
        ref = loopy_bp(g, max_iter=50, tol=1e-8)
        post, *_ = category_bp(unary, [e[0] for e in edges], [e[1] for e in edges], tables, max_iter=50, tol=1e-8)
        for i in range(n):
            np.testing.assert_allclose(post[i], ref.posteriors[i], atol=1e-6)


class FusionTests(TransactionTestCase):
    databases = {'default', 'observations'}

    def setUp(self):
        self.t1 = timezone.now() - timedelta(hours=1)
        self.t2 = self.t1 + timedelta(minutes=20)
        self.t3 = self.t1 + timedelta(minutes=40)

    def _ingest(self, name, at, **kw):
        return fusion.ingest_scene_graph(_scene(at, **kw), session_id=name, taxonomy_name='urban_v1')

    def _entity(self, category):
        return Entity.objects.get(category=category)

    def test_repeat_capture_associates_instead_of_duplicating(self):
        first = self._ingest('s1', self.t1)
        second = self._ingest('s2', self.t2, shift_m=0.5)
        self.assertEqual(first['n_new_entities'], 3)
        self.assertEqual((second['n_new_entities'], second['n_matched']), (0, 3))
        self.assertEqual(Entity.objects.count(), 3)
        self.assertEqual(self._entity('building').n_hits, 2)
        self.assertEqual(self._ingest('s2', self.t2)['status'], 'exists')

    def test_missing_car_loses_existence_but_building_keeps_it(self):
        self._ingest('s1', self.t1)
        out = self._ingest('s2', self.t2, with_car=False)
        self.assertEqual(out['n_missed'], 1)
        after_one = self._entity('vehicle').p_exists
        self._ingest('s3', self.t3, with_car=False)
        car, bld = self._entity('vehicle'), self._entity('building')
        self.assertLess(car.p_exists, after_one)
        self.assertLess(car.p_exists, 0.5)
        self.assertGreater(bld.p_exists, 0.9)

    def test_late_capture_is_slotted_into_the_chain(self):
        self._ingest('s1', self.t1)
        self._ingest('s3', self.t3, with_car=False)
        self._ingest('s2', self.t2, with_car=False)
        self.assertLess(self._entity('vehicle').p_exists, 0.5)

    def test_time_travel_recovers_the_car_before_it_left(self):
        self._ingest('s1', self.t1)
        self._ingest('s2', self.t2, with_car=False)
        self._ingest('s3', self.t3, with_car=False)
        car = self._entity('vehicle')
        then = fusion.run_local_bp([car.id], at=self.t1 + timedelta(minutes=1), write=False)
        self.assertGreater(then['beliefs'][car.id]['p_exists'], 0.9)
        self.assertLess(car.p_exists, 0.5)

    def test_vehicle_evidence_fades_faster_than_building_evidence(self):
        self._ingest('s1', self.t1)
        ids = list(Entity.objects.values_list('id', flat=True))
        later = fusion.run_local_bp(ids, at=self.t1 + timedelta(days=2), write=False)['beliefs']
        car, bld = self._entity('vehicle'), self._entity('building')
        self.assertLess(abs(later[car.id]['p_exists'] - 0.5), 0.05)
        self.assertGreater(later[bld.id]['p_exists'], 0.8)

    def test_context_and_containment_factors(self):
        self._ingest('s1', self.t1)
        kinds = set(Factor.objects.values_list('kind', flat=True))
        self.assertTrue({'perceptual', 'hit', 'context', 'contains'} <= kinds)
        self._ingest('s2', self.t2)
        self.assertEqual(Factor.objects.filter(kind='context').count(), 1)
        self.assertTrue(Factor.objects.filter(kind='context', log_table__isnull=True, potential__isnull=False).exists())

    def test_feedback_relabels_and_supersedes(self):
        self._ingest('s1', self.t1)
        bld = self._entity('building')
        _, e, _ = fusion.apply_feedback(bld.id, 'relabel', category='house', user_id=7)
        self.assertEqual(e.category, 'house')
        _, e, _ = fusion.apply_feedback(bld.id, 'relabel', category='pool', user_id=7)
        self.assertEqual(e.category, 'pool')
        self.assertEqual(Feedback.objects.filter(entity=bld, superseded_at__isnull=True).count(), 1)
        _, e, _ = fusion.apply_feedback(bld.id, 'reject', user_id=8)
        self.assertGreater(e.p_exists, 0.5)  # two users disagree: their corrections cancel
        _, e, _ = fusion.apply_feedback(bld.id, 'reject', user_id=7)
        self.assertLess(e.p_exists, 0.1)
        with self.assertRaises(ValueError):
            fusion.apply_feedback(bld.id, 'relabel', category='spaceship', user_id=7)

    def test_api(self):
        self._ingest('s1', self.t1)
        bbox = f'{LON - 0.002},{LAT - 0.002},{LON + 0.002},{LAT + 0.002}'
        r = self.client.get('/webclient/sampler/world/entities', {'bbox': bbox, 'min_p_exists': 0.5})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['n_entities'], 3)
        r = self.client.get('/webclient/sampler/world/entities', {'bbox': bbox, 'at': self.t1.isoformat()})
        self.assertEqual(r.json()['n_entities'], 3)
        bld = self._entity('building')
        body = json.dumps({'entity_id': bld.id, 'kind': 'confirm'})
        self.assertEqual(self.client.post('/webclient/sampler/world/feedback', body,
                                          content_type='application/json').status_code, 401)
        user = get_user_model().objects.create_user('sg_tester', password='x')
        self.client.force_login(user)
        r = self.client.post('/webclient/sampler/world/feedback', body, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        r = self.client.post('/webclient/sampler/world/preferences', json.dumps({'sam3_prompts': 'tree, pool'}),
                             content_type='application/json')
        self.assertEqual(r.json()['preferences'], {'sam3_prompts': 'tree, pool'})
        r = self.client.get(f'/webclient/sampler/world/entities/{bld.id}')
        self.assertEqual(r.json()['factor_counts']['feedback'], 2)
