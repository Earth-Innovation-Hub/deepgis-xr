"""Spatiotemporal scene-graph store: association, existence, time travel, feedback."""

import hashlib
import json
from datetime import timedelta

import numpy as np
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone

from deepgis_xr.apps.scene_store import fusion, priors
from deepgis_xr.apps.scene_store.models import Detection, Entity, Factor, Feedback, Pose
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


class GeometryPriorTests(SimpleTestCase):
    def test_size_and_shape_penalties(self):
        v, r, u = (URBAN_V1.index_of(c) for c in ('vehicle', 'road', 'unknown'))
        self.assertIsNone(priors.geometry_table(URBAN_V1, 0))
        car = priors.geometry_table(URBAN_V1, 9.0, 0.78)
        self.assertEqual(car[v], 0.0)
        self.assertLess(car[URBAN_V1.index_of('parking_lot')], 0)  # 9 m² is too small for a lot
        blob = priors.geometry_table(URBAN_V1, 27634.0, 0.78)
        self.assertEqual(blob[v], priors.GEOMETRY_FLOOR)
        self.assertEqual(blob[r], priors.ROAD_BLOB_PENALTY)
        self.assertEqual(blob[u], 0.0)
        thin_road = priors.geometry_table(URBAN_V1, 27634.0, 0.05)
        self.assertEqual(thin_road[r], 0.0)


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
        self.assertEqual(r.json()['candidates'][0]['category'], r.json()['entity']['best_guess']['category'])
        self.assertLessEqual(len(r.json()['candidates']), 3)

    def test_areas_are_geodesic_and_entities_take_the_median(self):
        self._ingest('s1', self.t1)
        self.assertAlmostEqual(self._entity('vehicle').area_m2, 9.0, delta=0.1)
        self.assertAlmostEqual(self._entity('building').area_m2, 900.0, delta=5)
        big = _scene(self.t2)
        big['nodes'][2]['region']['geo_polygon'] = _square(10, 2, 1.6)
        fusion.ingest_scene_graph(big, session_id='s2', taxonomy_name='urban_v1')
        big['viewport']['capture_metadata']['captured_at'] = self.t3.isoformat()
        big['nodes'][2]['region']['geo_polygon'] = _square(10, 2, 1.7)
        fusion.ingest_scene_graph(big, session_id='s3', taxonomy_name='urban_v1')
        self.assertAlmostEqual(self._entity('vehicle').area_m2, 3.2 ** 2, delta=0.1)

    def test_histogram_api(self):
        self._ingest('s1', self.t1)
        bbox = f'{LON - 0.002},{LAT - 0.002},{LON + 0.002},{LAT + 0.002}'
        url = '/webclient/sampler/world/histogram'
        r = self.client.get(url, {'bbox': bbox, 'category': 'vehicle', 'bin_m2': 2, 'max_m2': 20}).json()
        self.assertEqual((r['level'], r['n'], r['overflow'], len(r['bins'])), ('entity', 1, 0, 10))
        self.assertEqual([b['n'] for b in r['bins']].index(1), 4)  # 9 m² lands in [8, 10)
        r = self.client.get(url, {'bbox': bbox, 'bin_m2': 100, 'max_m2': 500}).json()
        self.assertEqual((r['n'], r['overflow']), (3, 1))
        r = self.client.get(url, {'capture': 'latest', 'source': 'sam3', 'label': 'vehicle', 'bin_m2': 1}).json()
        self.assertEqual((r['level'], r['capture']['session_id'], r['n']), ('detection', 's1', 1))
        self.assertEqual(r['stats']['median'], r['stats']['max'])
        r = self.client.get(url, {'bbox': bbox}).json()
        self.assertEqual((r['n'], r['bin_m2']), (3, 50.0))  # p99 ~870 m² / 25 -> 50 m² bins
        self.assertEqual([fusion.nice_bin(s) for s in (0.04, 9, 25, 120, 0)], [0.002, 0.5, 1.0, 5.0, 1.0])
        self.assertEqual(self.client.get(url, {'capture': 'nope'}).status_code, 404)
        self.assertEqual(self.client.get(url, {'bbox': bbox, 'bin_m2': 0}).status_code, 400)
        self.assertEqual(self.client.get(url).status_code, 400)

    def test_frame_sized_region_is_stored_but_not_evidence(self):
        sg = _scene(self.t1)
        sg['nodes'].append(_node('f', 'road', _square(0, 0, 90)))  # 81% of the 200 m footprint
        out = fusion.ingest_scene_graph(sg, session_id='s1', taxonomy_name='urban_v1')
        self.assertEqual((out['n_detections'], out['n_gated'], out['n_new_entities']), (4, 1, 3))
        self.assertEqual(Detection.objects.get(node_id='f').gate, 'frame')
        self.assertEqual(Entity.objects.count(), 3)

    def test_geometry_factor_turns_a_giant_car_away_from_vehicle(self):
        sg = _scene(self.t1)
        sg['nodes'][2]['region']['geo_polygon'] = _square(10, 2, 30)  # 3,600 m² "vehicle"
        fusion.ingest_scene_graph(sg, session_id='s1', taxonomy_name='urban_v1')
        self.assertFalse(Entity.objects.filter(category='vehicle').exists())
        car = Detection.objects.get(node_id='v')
        geo = Factor.objects.get(kind='geometry', detection=car)
        self.assertAlmostEqual(geo.log_table[URBAN_V1.index_of('vehicle')], -2 * np.log(30), places=2)
        self.assertAlmostEqual(geo.metadata['area_m2'], 3600, delta=5)

    def test_misses_need_the_resolution_to_see_the_object(self):
        self._ingest('s1', self.t1)
        coarse = _scene(self.t2, with_car=False)
        coarse['viewport']['image_size'] = [100, 80]  # ~2.2 m pixels: a 9 m² car is ~2 pixels
        out = fusion.ingest_scene_graph(coarse, session_id='s2', taxonomy_name='urban_v1')
        self.assertEqual(out['n_missed'], 0)
        self.assertAlmostEqual(out['gsd_m'], 2.24, delta=0.05)
        self.assertEqual(self._ingest('s3', self.t3, with_car=False)['n_missed'], 1)

    def test_capture_pose_is_recorded_with_uncertainty(self):
        self._ingest('s1', self.t1)
        pose = Pose.objects.get()
        self.assertEqual((pose.source, pose.alt_m, pose.sigma_h_m), ('virtual_camera', 700,
                                                                     priors.VIRTUAL_CAMERA_SIGMA_H_M))
        self.assertAlmostEqual(pose.position.x, LON)

    def test_retire_and_restore_round_trip(self):
        self._ingest('s1', self.t1)
        car, road = self._entity('vehicle'), self._entity('road')
        live = Factor.objects.filter(superseded_at__isnull=True).count()
        out = fusion.retire_entities([car.id], 'test')
        self.assertEqual((out['n_retired'], out['n_neighbours']), (1, 1))
        bbox = (LON - 0.002, LAT - 0.002, LON + 0.002, LAT + 0.002)
        self.assertEqual({e['category'] for e in fusion.entities_in_bbox(bbox)[0]}, {'building', 'road'})
        self.assertFalse(Factor.objects.filter(entity_ids__overlap=[car.id], superseded_at__isnull=True).exists())
        self.assertEqual(self._ingest('s2', self.t2)['n_new_entities'], 1)  # a fresh sighting is a new entity
        self.assertEqual(fusion.restore_entities([car.id])['n_restored'], 1)
        car.refresh_from_db()
        self.assertIsNone(car.retired_at)
        self.assertTrue(Factor.objects.filter(entity_ids__overlap=[car.id, road.id], kind='context',
                                              superseded_at__isnull=True).exists())
        self.assertGreater(Factor.objects.filter(superseded_at__isnull=True).count(), live)

    def test_low_confidence_entity_is_unknown_with_a_best_guess(self):
        sg = _scene(self.t1)
        sg['nodes'][2] = _node('v', 'vehicle', _square(10, 2, 1.5), p=1 / URBAN_V1.n)  # uniform: no label
        fusion.ingest_scene_graph(sg, session_id='s1', taxonomy_name='urban_v1')
        car = Entity.objects.get(associations__detection__node_id='v')
        self.assertLess(car.score, priors.LOW_CONFIDENCE)
        self.assertEqual(car.category, 'unknown')
        self.assertEqual(fusion.entity_to_dict(car)['best_guess']['category'], 'vehicle')
        self.assertEqual(self._entity('building').category, 'building')
        self.assertEqual(fusion.label_of(URBAN_V1, np.full(URBAN_V1.n, 1 / URBAN_V1.n)), 'unknown')

    def test_captures_api(self):
        self._ingest('s1', self.t1)
        self._ingest('s2', self.t2)
        url = '/webclient/sampler/world/captures'
        r = self.client.get(url, {'bbox': f'{LON - 0.01},{LAT - 0.01},{LON + 0.01},{LAT + 0.01}'}).json()
        self.assertEqual((r['n_captures'], [c['session_id'] for c in r['captures']]), (2, ['s2', 's1']))
        self.assertEqual(r['captures'][0]['n_detections'], 3)
        self.assertEqual(set(r['captures'][0]['categories']), {'building', 'road', 'vehicle'})
        self.assertEqual(len(r['captures'][0]['footprint']), 5)
        far = self.client.get(url, {'bbox': f'{LON + 1},{LAT + 1},{LON + 1.01},{LAT + 1.01}'}).json()
        self.assertEqual((far['n_captures'], far['captures'], far['first']), (0, [], None))
        self.assertEqual(self.client.get(url, {'bbox': f'{LON},{LAT},{LON + 1},{LAT + 1}'}).status_code, 400)
        self.assertEqual(self.client.get(url).status_code, 400)
        d = self.client.get(f'{url}/s2').json()
        self.assertEqual(len(d['detections']), 3)
        self.assertTrue(all(det['entity_id'] for det in d['detections']))
        entities = {det['entity_id'] for det in d['detections']}
        self.assertTrue(d['links'] and all(set(link['entities']) <= entities for link in d['links']))
        self.assertEqual(self.client.get(f'{url}/nope').status_code, 404)
        gsd = (200 * 200 / (1000 * 800)) ** 0.5
        self.assertAlmostEqual(r['captures'][0]['gsd_m'], gsd, places=2)
        self.assertAlmostEqual(r['captures'][0]['min_object_m2'], priors.MISS_MIN_PIXELS * gsd ** 2, delta=0.2)
        self.assertEqual(r['captures'][0]['pose']['source'], 'virtual_camera')

    def test_summary_lists_best_guesses_behind_unknown(self):
        sg = _scene(self.t1)
        sg['nodes'][2] = _node('v', 'vehicle', _square(10, 2, 1.5), p=1 / URBAN_V1.n)
        fusion.ingest_scene_graph(sg, session_id='s1', taxonomy_name='urban_v1')
        bbox = f'{LON - 0.01},{LAT - 0.01},{LON + 0.01},{LAT + 0.01}'
        r = self.client.get('/webclient/sampler/world/summary', {'bbox': bbox}).json()
        self.assertEqual((r['n'], r['n_unknown']), (3, 1))
        self.assertEqual(r['unknown_best_guess'][0]['category'], 'vehicle')
        self.assertEqual(sum(b['n'] for b in r['confidence_bins']), 3)
        sure = self.client.get('/webclient/sampler/world/entities', {'bbox': bbox, 'min_score': 0.5}).json()
        self.assertNotIn('unknown', [e['category'] for e in sure['entities']])
        self.assertEqual(sure['n_entities'], 2)

    def test_changes_since(self):
        self._ingest('s1', self.t1)
        self._ingest('s2', self.t2, with_car=False)
        self._ingest('s3', self.t3, with_car=False)
        box = (LON - 0.01, LAT - 0.01, LON + 0.01, LAT + 0.01)
        later = fusion.world_changes(box, self.t1 + timedelta(minutes=1))
        self.assertEqual(later['appeared']['n'], 0)
        self.assertEqual(later['gone']['by_category'], {'vehicle': 1})
        self.assertEqual(later['n_captures'], 2)
        everything = fusion.world_changes(box, self.t1 - timedelta(minutes=1))
        self.assertEqual(everything['appeared']['n'], 3)
        url = '/webclient/sampler/world/changes'
        bbox = ','.join(map(str, box))
        since = (self.t1 - timedelta(days=1)).strftime('%Y-%m-%d')
        r = self.client.get(url, {'bbox': bbox, 'since': since}).json()
        self.assertEqual((r['appeared']['n'], r['gone']['n']), (3, 1))
        self.assertEqual(self.client.get(url, {'bbox': bbox, 'since': 'april'}).status_code, 400)
        self.assertEqual(self.client.get(url, {'bbox': bbox, 'since': '2026-05', 'until': '2026-04'}).status_code, 400)

    def test_retire_api_is_superuser_only_and_undoable(self):
        self._ingest('s1', self.t1)
        car = self._entity('vehicle')
        url, body = '/webclient/sampler/world/retire', json.dumps({'entity_ids': [car.id], 'reason': 'test'})
        self.assertEqual(self.client.post(url, body, content_type='application/json').status_code, 401)
        users = get_user_model().objects
        self.client.force_login(users.create_user('pat', password='x', phone_number='+14805550111'))
        self.assertEqual(self.client.post(url, body, content_type='application/json').status_code, 403)
        self.client.force_login(users.create_superuser('root', email='r@example.org', password='x',
                                                       phone_number='+14805550112'))
        r = self.client.post(url, body, content_type='application/json').json()
        self.assertEqual(r['n_retired'], 1)
        self.assertIsNotNone(Entity.objects.get(id=car.id).retired_at)
        self.assertEqual(self.client.post(url, json.dumps({'entity_ids': list(range(1, 60))}),
                                          content_type='application/json').status_code, 400)
        r = self.client.post('/webclient/sampler/world/restore', json.dumps({'entity_ids': [car.id]}),
                             content_type='application/json').json()
        self.assertEqual(r['n_restored'], 1)
        self.assertIsNone(Entity.objects.get(id=car.id).retired_at)


@override_settings(SCENE_MCP_TOKENS=hashlib.sha256(b'secret').hexdigest())
class McpTests(TransactionTestCase):
    databases = {'default', 'observations'}

    def setUp(self):
        self.t1 = timezone.now() - timedelta(hours=1)
        fusion.ingest_scene_graph(_scene(self.t1), session_id='s1', taxonomy_name='urban_v1')
        fusion.ingest_scene_graph(_scene(self.t1 + timedelta(minutes=20)), session_id='s2', taxonomy_name='urban_v1')

    def _rpc(self, method, params=None, token='secret', mid=1):
        msg = {'jsonrpc': '2.0', 'method': method, 'params': params or {}}
        if mid is not None:
            msg['id'] = mid
        return self.client.post('/api/v1/mcp', json.dumps(msg), content_type='application/json',
                                HTTP_AUTHORIZATION=f'Bearer {token}')

    def _tool(self, name, **args):
        r = self._rpc('tools/call', {'name': name, 'arguments': args}).json()['result']
        return r if r['isError'] else json.loads(r['content'][0]['text'])

    def test_protocol(self):
        self.assertEqual(self._rpc('ping', token='wrong').status_code, 401)
        self.assertEqual(self.client.get('/api/v1/mcp').status_code, 405)
        init = self._rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                        'clientInfo': {'name': 't', 'version': '0'}}).json()['result']
        self.assertEqual((init['protocolVersion'], init['serverInfo']['name']), ('2025-06-18', 'deepgis-scene-graph'))
        self.assertEqual(self._rpc('notifications/initialized', mid=None).status_code, 202)
        tools = {t['name'] for t in self._rpc('tools/list').json()['result']['tools']}
        self.assertEqual(tools, {'world_stats', 'list_scene_graphs', 'get_scene_graph', 'world_summary',
                                 'find_entities', 'get_entity', 'world_changes', 'area_histogram'})
        self.assertEqual(self._rpc('nope').json()['error']['code'], -32601)
        self.assertEqual(self._rpc('tools/call', {'name': 'nope'}).json()['error']['code'], -32602)

    def test_entities_and_graphs(self):
        found = self._tool('find_entities', lat=LAT, lon=LON, radius_m=300)
        self.assertEqual([e['category'] for e in found['entities']], ['road', 'vehicle', 'building'])
        self.assertAlmostEqual(found['entities'][2]['distance_m'], 40, delta=1)
        self.assertNotIn('polygon', found['entities'][0])
        self.assertEqual(found['entities'][0]['candidates'][0]['category'], 'road')
        self.assertEqual(len(self._tool('find_entities', lat=LAT, lon=LON, category='vehicle')['entities']), 1)
        self.assertEqual(self._tool('find_entities', lat=LAT, lon=LON, radius_m=1e6)['area']['radius_m'],
                         self._tool('world_summary', lat=LAT, lon=LON, radius_m=1e6)['area']['radius_m'])

        graphs = self._tool('list_scene_graphs')
        self.assertEqual([c['session_id'] for c in graphs['captures']], ['s2', 's1'])
        self.assertNotIn('footprint', graphs['captures'][0])
        g = self._tool('get_scene_graph', session_id='s2')
        self.assertEqual((g['n_nodes'], len(g['nodes'])), (3, 3))
        self.assertTrue(g['links'])
        self.assertTrue(self._tool('get_scene_graph', session_id='missing')['isError'])

        car = self._tool('get_entity', entity_id=found['entities'][1]['id'])
        self.assertEqual((car['entity']['category'], car['n_sightings']), ('vehicle', 2))
        changes = self._tool('world_changes', lat=LAT, lon=LON, since=(self.t1 - timedelta(days=1)).date().isoformat())
        self.assertEqual(changes['appeared']['n'], 3)
        self.assertEqual(self._tool('area_histogram', lat=LAT, lon=LON)['n'], 3)
        self.assertEqual(self._tool('world_stats')['n_captures'], 2)
        self.assertTrue(self._tool('find_entities', lat=95, lon=LON)['isError'])
