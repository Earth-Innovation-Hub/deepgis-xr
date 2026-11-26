"""Spatiotemporal scene-graph store: association, existence, time travel, feedback."""

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest import mock

import numpy as np
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone

from django.core.management.base import CommandError

from deepgis_xr.apps.scene_store import (
    assess, detection_model, field_evidence, fusion, layers, looks, priors, traits, zone_views, zonemap,
)
from deepgis_xr.apps.scene_store.models import (
    BeliefSnapshot, Capture, Detection, DetectionModel, Entity, Factor, Feedback, FieldLink, ImageryCheck,
    LayerSample, LayerScene, Pose, Zone,
)
from deepgis_xr.apps.web.models import FieldReading
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


def _imagery(start='2023-03-01', end='2023-09-01'):
    """What the page sends for a view of Bing aerial imagery acquired in that window."""
    return {'source': 'bing:Aerial', 'layers': [{'id': 'bing:Aerial', 'alpha': 1}],
            'dates': {'start': start, 'end': end, 'uniform': True, 'zoom': 19, 'points': 5,
                      'method': 'bing_metadata'}}


IMAGED = datetime(2023, 6, 1, tzinfo=dt_timezone.utc)  # the middle of that window


def _scene(at, *, with_car=True, shift_m=0.0, imagery=None):
    nodes = [_node('b', 'building', _square(-40 + shift_m, 0, 15)),
             _node('r', 'road', _square(10 + shift_m, 0, 6))]
    if with_car:
        nodes.append(_node('v', 'vehicle', _square(10 + shift_m, 2, 1.5)))
    return {
        'viewport': {'image_size': [1000, 800], 'capture_metadata': {
            'world_corners': [p[:2] for p in _square(0, 0, 100)[:4]],
            'camera': {'lon': LON, 'lat': LAT, 'alt': 700}, 'captured_at': at.isoformat(),
            'imagery': imagery}},
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


class LookTests(SimpleTestCase):
    @staticmethod
    def _p(tables):
        absent, present = looks.exists_message(tables)
        return 1 / (1 + np.exp(absent - present))

    @staticmethod
    def _reading(category, p):
        post = np.full(URBAN_V1.n, (1 - p) / (URBAN_V1.n - 1))
        post[URBAN_V1.index_of(category)] = p
        return np.log(post)

    def test_one_image_can_only_prove_so_much(self):
        low, high = looks.exists_limits()
        one, two, six = (self._p([priors.HIT_TABLE] * n) for n in (1, 2, 6))
        self.assertTrue(0.85 < one < two < six < high < 0.96)
        self.assertAlmostEqual(six, high, places=4)
        # Even a single detection is doubted twice: by the detector, and by the image.
        self.assertLess(one, priors.P_DETECT / (priors.P_DETECT + priors.P_FALSE_ALARM))
        self.assertAlmostEqual(self._p([priors.miss_table(0.98)] * 6), low, places=3)
        # Found twice and missed once at a zoom that finds half: the image shows it.
        self.assertGreater(self._p([priors.HIT_TABLE, priors.HIT_TABLE, priors.miss_table(0.5)]), 0.93)
        # Two different images multiply.
        both = looks.exists_message([priors.HIT_TABLE]) * 2
        self.assertGreater(1 / (1 + np.exp(both[0] - both[1])), high)

    def test_agreeing_readings_are_one_reading(self):
        house, building = self._reading('house', 0.4), self._reading('building', 0.4)
        np.testing.assert_allclose(looks.category_message([house]), house)
        np.testing.assert_allclose(looks.category_message([house] * 4), house, atol=1e-9)
        # Readings that differ in strength but not in what they name: their mean, once.
        strong = self._reading('house', 0.6)
        np.testing.assert_allclose(looks.category_message([house, strong]), (house + strong) / 2, atol=1e-9)

        def post(readings):
            m = looks.category_message(readings)
            p = np.exp(m - m.max())
            return p / p.sum()

        h, b = URBAN_V1.index_of('house'), URBAN_V1.index_of('building')
        split = post([house, building])  # one reading each way: the image is ambiguous
        self.assertAlmostEqual(split[h], split[b], places=9)
        self.assertLess(split[h], 0.4)
        self.assertGreater(split[h] + split[b], 0.4)
        outvoted = post([house, house, building])  # the odd one out is a misreading
        self.assertAlmostEqual(outvoted[h], 0.4, delta=0.01)


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
        self.assertGreater(then['beliefs'][car.id]['p_exists'], 0.85)  # one detection on one image
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
        layers._stats_cache.clear()

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
                                 'find_entities', 'get_entity', 'world_changes', 'area_histogram', 'trait_map',
                                 'assess_point', 'field_readings', 'entity_looks', 'belief_history',
                                 'entity_beliefs'})
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
        self.assertIn('p_exists', car['now'])
        self.assertEqual(car['field_readings']['n_readings'], 0)
        self.assertEqual(car['layers'], [])
        # two captures whose imagery is not identified are two looks
        self.assertEqual((car['support']['n_looks'], [k['identified'] for k in car['support']['looks']]),
                         (2, [False, False]))
        here = self._tool('assess_point', lat=LAT, lon=LON - 40 * M / np.cos(np.radians(LAT)))
        self.assertEqual((here['fused']['category'], here['looked_at']['n_captures'], here['looked_at']['n_looks']),
                         ('building', 2, 2))
        self.assertEqual(here['objects'][0]['support']['n_found'], 2)
        self.assertTrue(self._tool('assess_point', lat=LAT)['isError'])
        self.assertTrue(self._tool('assess_point', lat=LAT, lon=LON, taxonomy='nope')['isError'])
        stats = self._tool('world_stats')
        self.assertEqual((stats['layers'], stats['imagery_checks']['n_to_recapture']), ([], 0))
        self.assertIn('imagery', graphs['captures'][0])
        changes = self._tool('world_changes', lat=LAT, lon=LON, since=(self.t1 - timedelta(days=1)).date().isoformat())
        self.assertEqual(changes['appeared']['n'], 3)
        self.assertEqual((changes['basis'], len(changes['imagery'])), ('imagery', 1))
        self.assertTrue(self._tool('world_changes', lat=LAT, lon=LON, since='2026', basis='orbit')['isError'])
        self.assertEqual(self._tool('world_stats')['detection_models'], {})
        self.assertEqual(self._tool('area_histogram', lat=LAT, lon=LON)['n'], 3)
        self.assertEqual(self._tool('world_stats')['n_captures'], 2)
        self.assertTrue(self._tool('find_entities', lat=95, lon=LON)['isError'])
        tm = self._tool('trait_map', lat=LAT, lon=LON, category='building')
        self.assertEqual((tm['n_points'], tm['gp'], tm['grid']), (1, None, None))
        self.assertTrue(self._tool('trait_map', lat=LAT, lon=LON, trait='height')['isError'])

    def test_the_queries_that_needed_sql(self):
        bld = Entity.objects.get(category='building')
        sg = _scene(self.t1 + timedelta(minutes=40))
        sg['nodes'] = [n for n in sg['nodes'] if n['id'] != 'b']
        fusion.ingest_scene_graph(sg, session_id='s3', taxonomy_name='urban_v1')

        looks = self._tool('entity_looks', entity_id=bld.id)
        by = {c['session_id']: c for c in looks['captures']}
        self.assertEqual((by['s1']['found'], by['s2']['found'], by['s3']['found']), (True, True, False))
        self.assertGreater(by['s1']['pixels'], priors.MISS_MIN_PIXELS)
        self.assertTrue(self._tool('entity_looks', entity_id=10 ** 9)['isError'])

        hist = self._tool('belief_history', entity_id=bld.id, limit=1)
        self.assertEqual((hist['n_returned'], hist['history'][0]['cause'] != ''), (1, True))
        self.assertGreater(hist['n'], 1)
        rest = self._tool('belief_history', entity_id=bld.id, after_id=hist['next_after_id'])
        self.assertNotIn(hist['history'][0]['id'], [r['id'] for r in rest['history']])
        self.assertEqual(hist['n_returned'] + rest['n_returned'], hist['n'])

        page = self._tool('entity_beliefs', taxonomy='urban_v1', limit=2)
        self.assertEqual((page['n_returned'], page['next_after_id']), (2, page['entities'][-1]['id']))
        self.assertGreaterEqual(page['n_entities'], 3)
        nxt = self._tool('entity_beliefs', taxonomy='urban_v1', after_id=page['next_after_id'])
        self.assertFalse({e['id'] for e in page['entities']} & {e['id'] for e in nxt['entities']})
        self.assertTrue(self._tool('entity_beliefs', taxonomy='nope')['isError'])

        FieldReading.objects.create(
            vehicle_id='rv', captured_usec=1, captured=self.t1,
            spectrum={'indices': {'nir_red': 0.3}, 'integration_ms': 100, 'clipped_pct': 0,
                      'acquisition': {'source': 'default'}},
            analysis={'image': 'a hedge beside the house'})
        survey = self._tool('field_readings', since=self.t1.date().isoformat(), until=self.t1.date().isoformat())
        self.assertEqual((survey['n_readings'], survey['n_with_position'], survey['n_with_index']), (1, 0, 1))
        self.assertEqual(survey['by_day'][0]['nir_red_median'], 0.3)
        self.assertEqual(survey['by_day'][0]['green_share'], 1.0)
        self.assertEqual((survey['image_notes']['hedge or shrub'], survey['image_notes']['roof or house']), (1, 1))
        self.assertEqual(survey['acquisition'].get('default'), 1)

        def names(obj):
            found = set()
            if isinstance(obj, dict):
                found.update(obj)
                for v in obj.values():
                    found |= names(v)
            elif isinstance(obj, list):
                for v in obj:
                    found |= names(v)
            return found

        self.assertTrue(names(survey).isdisjoint(
            {'camera', 'target', 'heading_deg', 'lat', 'lon', 'vehicle_id', 'image'}))


class TraitTests(TransactionTestCase):
    databases = {'default', 'observations'}

    def test_gp_recovers_a_smooth_field(self):
        rng = np.random.default_rng(1)
        xy = rng.uniform(-200, 200, size=(150, 2))
        z = np.sin(xy[:, 0] / 60) + rng.normal(0, 0.1, 150)
        grid = np.array([[0.0, 0.0], [60 * np.pi / 2, 0.0], [5000.0, 5000.0]])
        gp = traits.fit_gp(xy, z, grid)
        self.assertAlmostEqual(gp['mean'][0], 0, delta=0.15)
        self.assertAlmostEqual(gp['mean'][1], 1, delta=0.15)
        self.assertGreater(gp['explained'][0], 0.9)
        self.assertLess(gp['explained'][2], 0.01)  # far from every point: back to the prior
        self.assertLess(gp['noise_share'], 0.2)

    def test_trait_map_view(self):
        nodes = [_node(f'h{i}', 'building', _square(-150 + 30 * (i % 10), -60 + 30 * (i // 10), 4 + i % 10))
                 for i in range(30)]
        sg = _scene(timezone.now() - timedelta(hours=1))
        sg['nodes'], sg['edges'] = nodes, []
        fusion.ingest_scene_graph(sg, session_id='t', taxonomy_name='urban_v1')
        box = [LON - 0.003, LAT - 0.002, LON + 0.003, LAT + 0.002]
        r = self.client.get('/webclient/sampler/world/trait_map',
                            {'bbox': ','.join(map(str, box)), 'category': 'building'}).json()
        self.assertEqual(r['status'], 'success')
        b = next(c for c in r['categories'] if c['category'] == 'building')
        self.assertEqual(b['stats']['n'], r['n_points'])
        self.assertGreaterEqual(r['n_points'], 25)
        self.assertTrue(b['hist']['log'])
        self.assertEqual(sum(x['n'] for x in b['hist']['bins']), b['stats']['n'])
        g = r['grid']
        self.assertEqual(len(g['value']), g['nx'] * g['ny'])
        self.assertTrue(all(0 <= e <= 1 for e in g['explained']))
        self.assertGreater(r['gp']['lengthscale_m'], 0)
        lo, hi = r['gp']['value_range']
        self.assertTrue(b['stats']['min'] <= lo <= hi <= b['stats']['max'])
        bad = self.client.get('/webclient/sampler/world/trait_map', {'bbox': ','.join(map(str, box)), 'trait': 'x'})
        self.assertEqual(bad.status_code, 400)


class DetectionModelTests(SimpleTestCase):
    """The fitted chance that a later look finds an entity again."""

    def _rows(self, n=4000):
        rng = np.random.default_rng(3)
        rows = []
        for i in range(n):
            pixels = float(2 ** rng.uniform(6, 16))
            ratio = float(rng.choice([0.5, 1.0, 2.0, 4.0]))
            category = 'house' if i % 2 else 'road'
            z = np.log2(ratio)
            s = 0.5 + 0.4 * (np.log2(pixels) - 10) - 2.0 * max(z, 0) - 0.8 * max(-z, 0) \
                + (0.7 if category == 'house' else -0.7)
            rows.append((i, i % 40, pixels, ratio, category, bool(rng.random() < 1 / (1 + np.exp(-s)))))
        return rows

    def test_fit_recovers_the_generating_model(self):
        c, m = detection_model.fit(self._rows())
        self.assertAlmostEqual(c['log2_pixels'], 0.4, delta=0.08)
        self.assertAlmostEqual(c['coarser'], -2.0, delta=0.35)
        self.assertAlmostEqual(c['finer'], -0.8, delta=0.35)
        self.assertAlmostEqual(c['category']['house'] - c['category']['road'], 1.4, delta=0.35)
        self.assertLess(m['log_loss']['fitted'], m['log_loss']['found_rate'])
        self.assertLess(m['log_loss']['fitted'], m['log_loss']['fixed'])
        model = detection_model.Fitted(1, c)
        self.assertGreater(model.p_detect(20000, 1.0, 'house'), model.p_detect(100, 1.0, 'house'))
        self.assertGreater(model.p_detect(2000, 1.0, 'house'), model.p_detect(2000, 4.0, 'house'))
        self.assertTrue(priors.P_FALSE_ALARM <= model.p_detect(1, 64.0, 'road') <= priors.P_DETECT_MAX)

    def test_thin_record_is_not_fitted(self):
        with self.assertRaises(ValueError):
            detection_model.fit(self._rows(50))

    def test_a_miss_weighs_what_the_look_could_have_found(self):
        sure, unsure = priors.miss_table(0.95), priors.miss_table(0.1)
        self.assertLess(sure[1] - sure[0], unsure[1] - unsure[0])  # a miss by a sure look says more
        self.assertAlmostEqual(unsure[1] - unsure[0], np.log(0.9 / (1 - priors.P_FALSE_ALARM)), places=6)
        self.assertEqual(priors.miss_table(1.0), priors.miss_table(priors.P_DETECT_MAX))
        table, why = detection_model.miss_evidence(None, area_m2=9.0, gsd_m=0.2, first_gsd_m=0.2, category='vehicle')
        self.assertEqual((table, why), (priors.MISS_TABLE, {'p_detect': priors.P_DETECT}))

    def test_registration_weight_is_the_share_of_the_target_inside(self):
        from shapely.geometry import Polygon as ShPolygon
        square = ShPolygon(_square(0, 0, 10)[:4])
        k = 1 / np.cos(np.radians(LAT))
        self.assertEqual(field_evidence.registration_weight(square, LON, LAT, 2.0), 1.0)
        self.assertAlmostEqual(field_evidence.registration_weight(square, LON + 10 * M * k, LAT, 2.0), 0.5, delta=0.1)
        self.assertEqual(field_evidence.registration_weight(square, LON + 40 * M * k, LAT, 2.0), 0.0)
        self.assertGreater(field_evidence.target_sigma_m(50), field_evidence.target_sigma_m(5))


class UpgradeTests(TransactionTestCase):
    """Fragments, the fitted miss weight, imagery dates, corrections, field readings."""

    databases = {'default', 'observations'}

    def setUp(self):
        self.t1 = timezone.now() - timedelta(hours=1)
        self.t2 = self.t1 + timedelta(minutes=20)
        self.box = (LON - 0.01, LAT - 0.01, LON + 0.01, LAT + 0.01)
        detection_model.forget()
        self.addCleanup(detection_model.forget)

    def _ingest(self, name, at, **kw):
        return fusion.ingest_scene_graph(_scene(at, **kw), session_id=name, taxonomy_name='urban_v1')

    def _entity(self, category):
        return Entity.objects.get(category=category, retired_at__isnull=True)

    def _with_fragment(self):
        sg = _scene(self.t1)
        sg['nodes'].append(_node('tiny', 'vehicle', _square(60, 60, 0.5)))  # 1 m² is 20 pixels at 22 cm
        return sg

    # -- 1. measured observation model -------------------------------------------------

    def test_fragment_is_stored_but_not_evidence(self):
        out = fusion.ingest_scene_graph(self._with_fragment(), session_id='s1', taxonomy_name='urban_v1')
        self.assertEqual((out['n_detections'], out['n_gated'], out['n_fragments'], out['n_new_entities']),
                         (4, 1, 1, 3))
        tiny = Detection.objects.get(node_id='tiny')
        self.assertEqual(tiny.gate, 'fragment')
        self.assertFalse(Factor.objects.filter(detection=tiny).exists())

    def test_gate_fragments_command_retires_what_only_fragments_held_up(self):
        with mock.patch.object(priors, 'FRAGMENT_MIN_PIXELS', 0):
            fusion.ingest_scene_graph(self._with_fragment(), session_id='s1', taxonomy_name='urban_v1')
        live = Entity.objects.filter(retired_at__isnull=True)
        self.assertEqual(live.count(), 4)
        out = StringIO()
        call_command('gate_fragments', stdout=out)
        self.assertIn('dry run', out.getvalue())
        self.assertEqual((Detection.objects.get(node_id='tiny').gate, live.count()), ('', 4))
        call_command('gate_fragments', '--apply', stdout=out)
        tiny = Detection.objects.get(node_id='tiny')
        self.assertEqual((tiny.gate, live.count()), ('fragment', 3))
        self.assertFalse(Factor.objects.filter(detection=tiny, superseded_at__isnull=True).exists())
        self.assertIn('fragment', Entity.objects.get(retired_at__isnull=False).retired_reason)
        self.assertEqual(self._entity('building').n_hits, 1)

    def test_fitted_model_weighs_a_miss(self):
        coefficients = {'intercept': 0.0, 'log2_pixels': 0.5, 'coarser': -2.0, 'finer': -1.0,
                        'category': {'vehicle': 1.0}}
        row = detection_model.store('urban_v1', coefficients, {'n_looks': 500})
        self._ingest('s1', self.t1)
        self.assertEqual(self._ingest('s2', self.t2, with_car=False)['n_missed'], 1)
        miss, car = Factor.objects.get(kind='miss'), self._entity('vehicle')
        gsd = Capture.objects.get(session_id='s2').gsd_m
        p = detection_model.Fitted(row.version, coefficients).p_detect(car.area_m2 / gsd ** 2, 1.0, 'vehicle')
        self.assertTrue(0.3 < p < 0.6)  # a 180-pixel car: found less often than the fixed 0.8 assumed
        self.assertAlmostEqual(miss.metadata['p_detect'], p, places=3)
        self.assertEqual(miss.metadata['model'], row.version)
        np.testing.assert_allclose(miss.log_table, priors.miss_table(p), atol=1e-3)
        stats = self.client.get('/webclient/sampler/world/stats', {'taxonomy': 'urban_v1'}).json()
        self.assertEqual(stats['detection_models']['urban_v1']['version'], row.version)

    def test_fit_detection_model_command_reweighs_stored_misses(self):
        nodes = [_node(f'h{i}', 'building', _square(-80 + 18 * (i % 10), -30 + 30 * (i // 10), 3 + i % 5))
                 for i in range(30)]
        for k in range(9):  # the first capture sees all 30; each later one misses a different third
            sg = _scene(self.t1 + timedelta(minutes=k))
            sg['nodes'], sg['edges'] = [n for i, n in enumerate(nodes) if k == 0 or (i + k) % 3], []
            fusion.ingest_scene_graph(sg, session_id=f'k{k}', taxonomy_name='urban_v1')
        misses = Factor.objects.filter(kind='miss', superseded_at__isnull=True)
        self.assertEqual(misses.count(), 80)
        out = StringIO()
        call_command('fit_detection_model', stdout=out)
        self.assertFalse(DetectionModel.objects.exists())
        call_command('fit_detection_model', '--apply', stdout=out)
        model = DetectionModel.objects.get(active=True)
        self.assertEqual((model.taxonomy, model.n_looks), ('urban_v1', 240))
        self.assertEqual(misses.count(), 80)
        self.assertTrue(all(f.metadata.get('model') == model.version for f in misses))
        self.assertAlmostEqual(np.mean([f.metadata['p_detect'] for f in misses]), 2 / 3, delta=0.1)
        self.assertIn('held-out', out.getvalue())

    # -- 3. imagery provenance and time ------------------------------------------------

    def test_imagery_dates_the_evidence(self):
        out = self._ingest('s1', self.t1, imagery=_imagery())
        self.assertTrue(out['imagery_dated'])
        cap = Capture.objects.get(session_id='s1')
        self.assertEqual((cap.imagery_source, cap.observed_at, cap.imagery['zoom']), ('bing:Aerial', IMAGED, 19))
        self.assertAlmostEqual((cap.captured_at - self.t1).total_seconds(), 0, delta=1)
        car = self._entity('vehicle')
        self.assertEqual((car.first_seen, car.last_seen), (IMAGED, IMAGED))
        self.assertEqual(set(Factor.objects.values_list('observed_at', flat=True)), {IMAGED})
        self.assertGreater(car.p_exists, 0.85)  # as last seen: nothing has decayed since the imagery

        # A second look at the same imagery without the car is a detector miss at the same instant.
        self._ingest('s2', self.t2, with_car=False, imagery=_imagery())
        car.refresh_from_db()
        self.assertEqual(car.last_seen, IMAGED)
        self.assertGreater(car.p_exists, 0.5)

        # Three years on, a parked car says little and a building still says something.
        bld = self._entity('building')
        now = fusion.run_local_bp([car.id, bld.id], at=timezone.now(), write=False)['beliefs']
        self.assertLess(abs(now[car.id]['p_exists'] - 0.5), 0.01)
        self.assertTrue(0.6 < now[bld.id]['p_exists'] < bld.p_exists)

        recent = fusion.world_changes(self.box, self.t1 - timedelta(days=1))
        self.assertEqual((recent['basis'], recent['appeared']['n']), ('imagery', 0))
        self.assertIn('same imagery', recent['note'])
        self.assertEqual(recent['imagery'][0]['n_captures'], 2)
        self.assertEqual(fusion.world_changes(self.box, self.t1 - timedelta(days=1), basis='view')['appeared']['n'], 3)
        in_2023 = fusion.world_changes(self.box, datetime(2023, 1, 1, tzinfo=dt_timezone.utc),
                                       datetime(2024, 1, 1, tzinfo=dt_timezone.utc))
        self.assertEqual((in_2023['appeared']['n'], in_2023['n_captures']), (3, 2))

        r = self.client.get(f'/webclient/sampler/world/entities/{car.id}').json()
        self.assertLess(abs(r['now']['p_exists'] - 0.5), 0.01)
        self.assertTrue(r['detections'][0]['imagery']['start'].startswith('2023-03-01'))
        self.assertEqual(r['detections'][0]['viewed_at'][:10], cap.captured_at.isoformat()[:10])
        caps = self.client.get('/webclient/sampler/world/captures', {'bbox': ','.join(map(str, self.box))}).json()
        self.assertEqual(caps['captures'][0]['observed_at'], IMAGED.isoformat())

    def test_unusable_imagery_dates_leave_the_view_time(self):
        late = (self.t1 + timedelta(days=30)).date().isoformat()
        out = self._ingest('s1', self.t1, imagery=_imagery(end=late))  # "acquired" after it was viewed
        self.assertFalse(out['imagery_dated'])
        cap = Capture.objects.get(session_id='s1')
        self.assertIsNone(cap.observed_at)
        self.assertEqual(cap.imagery_source, 'bing:Aerial')
        self.assertIn('rejected_dates', cap.imagery)
        self.assertEqual(self._entity('vehicle').first_seen, cap.captured_at)
        self.assertIsNone(fusion.imagery_record(None, self.t1)['observed_at'])
        reversed_window = {'dates': {'start': '2023-09-01', 'end': '2023-03-01'}}
        self.assertIsNone(fusion.imagery_record(reversed_window, self.t1)['observed_at'])

    def test_backfill_imagery_command_moves_evidence_to_the_imagery_date(self):
        self._ingest('s1', self.t1)
        self._ingest('s2', self.t2, with_car=False)
        car = self._entity('vehicle')
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fh:
            json.dump({name: {'source': 'bing:Aerial', 'start': '2023-03-01', 'end': '2023-09-01', 'zoom': 19,
                              'uniform': True, 'method': 'backfill'} for name in ('s1', 's2', 'missing')}, fh)
        self.addCleanup(os.unlink, fh.name)
        out = StringIO()
        call_command('backfill_imagery', '--file', fh.name, stdout=out)
        self.assertIsNone(Capture.objects.get(session_id='s1').observed_at)
        call_command('backfill_imagery', '--file', fh.name, '--apply', stdout=out)
        self.assertIn('captures dated: 2', out.getvalue())
        self.assertEqual(set(Capture.objects.values_list('observed_at', flat=True)), {IMAGED})
        self.assertEqual(set(Detection.objects.values_list('observed_at', flat=True)), {IMAGED})
        self.assertEqual({(f.observed_at, f.valid.lower) for f in Factor.objects.all()}, {(IMAGED, IMAGED)})
        self.assertAlmostEqual((Capture.objects.get(session_id='s1').captured_at - self.t1).total_seconds(), 0, delta=1)
        was = car.p_exists
        car.refresh_from_db()
        self.assertEqual((car.first_seen, car.last_seen), (IMAGED, IMAGED))
        self.assertGreater(car.p_exists, was)  # the miss no longer comes 20 minutes after the hit

    # -- 2. a truth channel ------------------------------------------------------------

    def test_feedback_is_dated_by_what_the_person_saw(self):
        self._ingest('s1', self.t1, imagery=_imagery())
        bld = self._entity('building')
        fb, _, _ = fusion.apply_feedback(bld.id, 'confirm', user_id=987654)
        self.assertEqual(set(Factor.objects.filter(feedback=fb).values_list('observed_at', flat=True)), {IMAGED})

        user = get_user_model().objects.create_user('sg_reviewer', password='x')
        self.client.force_login(user)
        mine = Factor.objects.filter(kind='feedback', superseded_at__isnull=True, feedback__user_id=user.id)

        def post(**body):
            return self.client.post('/webclient/sampler/world/feedback', json.dumps({'entity_id': bld.id, **body}),
                                    content_type='application/json')

        self.assertEqual(post(kind='reject', imagery=_imagery('2025-01-01', '2025-03-01')).status_code, 200)
        self.assertEqual({t.date().isoformat() for t in mine.values_list('observed_at', flat=True)}, {'2025-01-30'})
        self.assertEqual(post(kind='reject', seen='in_person').status_code, 200)
        self.assertTrue(all((timezone.now() - t).total_seconds() < 60 for t in mine.values_list('observed_at', flat=True)))
        # It stood in the 2023 imagery and someone standing there today says it is gone.
        bld.refresh_from_db()
        self.assertLess(bld.p_exists, 0.5)
        then = fusion.run_local_bp([bld.id], at=IMAGED + timedelta(days=1), write=False)['beliefs'][bld.id]
        self.assertGreater(then['p_exists'], 0.9)

    def test_review_queue_asks_about_the_least_certain_first(self):
        sg = _scene(self.t1)
        sg['nodes'][2] = _node('v', 'vehicle', _square(10, 2, 1.5), p=0.3)
        fusion.ingest_scene_graph(sg, session_id='s1', taxonomy_name='urban_v1')
        car = Entity.objects.get(associations__detection__node_id='v')
        queue = fusion.review_queue(self.box)
        self.assertEqual((queue['n_candidates'], queue['n_judged'], queue['entities'][0]['id']), (3, 0, car.id))
        self.assertGreater(queue['entities'][0]['value_bits'], queue['entities'][1]['value_bits'])
        fusion.apply_feedback(car.id, 'relabel', category='vehicle', user_id=987654)
        queue = fusion.review_queue(self.box)
        self.assertEqual((queue['n_candidates'], queue['n_judged']), (2, 1))
        self.assertNotIn(car.id, [e['id'] for e in queue['entities']])
        url = '/webclient/sampler/world/review'
        r = self.client.get(url, {'bbox': ','.join(map(str, self.box)), 'limit': 1})
        self.assertEqual((r.status_code, len(r.json()['entities'])), (200, 1))
        self.assertEqual(self.client.get(url).status_code, 400)

    def _reading(self, x_m, y_m, *, index=0.4, when=None, usec=1):
        k = 1 / np.cos(np.radians(LAT))
        # 19:30 UTC is half past noon in Tempe: the sun is well up on any day of the year
        when = when or (self.t1 - timedelta(days=1)).replace(hour=19, minute=30, second=0, microsecond=0)
        return FieldReading.objects.using('observations').create(
            vehicle_id='rover', captured_usec=int(when.timestamp() * 1e6) + usec, captured=when,
            range_m=10.0, range_valid=True, target=Point(LON + x_m * M * k, LAT + y_m * M, srid=4326),
            spectrum={'footprint': {'diameter_m': 2.0}, 'indices': {'nir_red': index}})

    def test_field_reading_years_after_the_imagery_does_not_age_it(self):
        self._ingest('s1', self.t1, imagery=_imagery())
        road = self._entity('road')
        before = road.score
        # Bare ground under a "road" label, read three years after the imagery, agrees with it.
        self.assertEqual(field_evidence.register_reading(self._reading(10, -3, index=-0.2)), {road.id})
        factor = Factor.objects.get(kind='field', superseded_at__isnull=True)
        self.assertGreater(factor.observed_at, IMAGED + timedelta(days=365))
        road.refresh_from_db()
        self.assertGreater(road.score, before)
        self.assertEqual(road.last_seen, IMAGED)  # a spectrum is not a sighting

    def test_field_reading_votes_once_a_day_on_the_entity_under_its_target(self):
        self._ingest('s1', self.t1)
        bld = self._entity('building')
        before = bld.score
        self.assertEqual(field_evidence.register_reading(self._reading(-40, 0)), {bld.id})
        link = FieldLink.objects.get()
        self.assertEqual((link.entity_id, link.usable, link.signal['green']), (bld.id, True, True))
        self.assertGreater(link.weight, 0.95)
        one = Factor.objects.get(kind='field', superseded_at__isnull=True)
        self.assertEqual(one.variables, [fusion.cvar(bld.id)])
        bld.refresh_from_db()
        self.assertLess(bld.score, before)  # green under a "building" label counts against it
        after_one, p_exists = bld.score, bld.p_exists

        # Five more readings of the same roof on the same day are still one vote.
        for i in range(5):
            field_evidence.register_reading(self._reading(-40 + i, 1, usec=10 + i))
        many = Factor.objects.get(kind='field', superseded_at__isnull=True)
        self.assertEqual(many.metadata['n_readings'], 6)
        np.testing.assert_allclose(many.log_table, one.log_table, atol=1e-6)
        bld.refresh_from_db()
        self.assertAlmostEqual(bld.score, after_one, places=4)
        self.assertAlmostEqual(bld.p_exists, p_exists, places=4)  # a spectrum says nothing about existence

        # At night the index means nothing, and a target off every outline is linked to nothing.
        night = (self.t1 - timedelta(days=2)).replace(hour=8, minute=0, second=0, microsecond=0)
        field_evidence.register_reading(self._reading(-40, 0, when=night, usec=99))
        self.assertFalse(FieldLink.objects.get(observed_at=night).usable)
        field_evidence.register_reading(self._reading(70, 70, usec=100))
        self.assertEqual(FieldLink.objects.count(), 7)
        self.assertEqual(Factor.objects.filter(kind='field', superseded_at__isnull=True).count(), 1)
        self.assertEqual(field_evidence.register_all()[1], set())  # a second pass changes nothing

        # Where a robot has been is shown to signed-in users only.
        url = f'/webclient/sampler/world/entities/{bld.id}'
        r = self.client.get(url).json()
        self.assertNotIn('field', r)
        self.assertNotIn('field', r['factor_counts'])
        self.client.force_login(get_user_model().objects.create_user('sg_field', password='x'))
        r = self.client.get(url).json()
        self.assertEqual((r['field']['n_readings'], r['field']['n_usable'], r['field']['n_green']), (7, 6, 6))
        self.assertEqual(r['factor_counts']['field'], 1)
        self.assertEqual(r['support']['other']['field'], 1)
        self.client.logout()
        self.assertNotIn('field', self.client.get(url).json()['support']['other'])

    # -- looks: the captures of one image count once -----------------------------------

    def test_captures_of_one_image_are_one_look(self):
        self._ingest('s1', self.t1, imagery=_imagery())
        bld = self._entity('building')
        first = (list(bld.posterior), bld.score, bld.p_exists)
        for k in range(2, 6):
            self._ingest(f's{k}', self.t1 + timedelta(minutes=k), imagery=_imagery())
        bld.refresh_from_db()
        low, high = looks.exists_limits()
        self.assertEqual((bld.n_hits, Factor.objects.filter(kind='hit', entity_ids=[bld.id]).count()), (5, 5))
        # Five detections of the same pixels read the same thing: the category is where it was,
        # and existence has gone as far as one image can take it and no further.
        np.testing.assert_allclose(bld.posterior, first[0], atol=1e-6)
        self.assertTrue(first[2] < bld.p_exists < high)
        self.assertAlmostEqual(bld.p_exists, high, places=2)
        before = fusion.run_local_bp([bld.id], write=False, pool_looks=False)['beliefs'][bld.id]
        self.assertGreater(before['p_exists'], 0.999)  # what counting each of them used to give
        self.assertGreater(before['score'], bld.score + 0.01)

        s = fusion.support(bld)
        self.assertEqual((s['n_looks'], s['looks'][0]['n_captures'], s['looks'][0]['n_found']), (1, 5, 5))
        self.assertEqual((s['looks'][0]['category']['category'], s['looks'][0]['category']['n_agree']), ('building', 5))
        self.assertAlmostEqual(s['looks'][0]['exists']['p'], bld.p_exists, places=3)

        # A different image is a new look, and that does add.
        self._ingest('s9', self.t2, imagery=_imagery('2025-01-01', '2025-03-01'))
        bld.refresh_from_db()
        self.assertGreater(bld.p_exists, high)
        self.assertGreater(bld.score, first[1])
        r = self.client.get(f'/webclient/sampler/world/entities/{bld.id}').json()
        self.assertEqual([(k['n_captures'], k['start'][:10]) for k in r['support']['looks']],
                         [(1, '2025-01-01'), (5, '2023-03-01')])
        self.assertEqual(r['support']['one_look_p_exists'], [round(low, 3), round(high, 3)])

    def test_rerun_beliefs_command_applies_the_look_rule_to_stored_beliefs(self):
        for k in range(1, 4):
            self._ingest(f's{k}', self.t1 + timedelta(minutes=k), imagery=_imagery())
        bld = self._entity('building')
        pooled = bld.p_exists
        # As the store was before looks: every detection its own observation.
        fusion.run_local_bp(list(Entity.objects.values_list('id', flat=True)), pool_looks=False)
        bld.refresh_from_db()
        self.assertGreater(bld.p_exists, 0.99)
        out = StringIO()
        call_command('rerun_beliefs', stdout=out)
        bld.refresh_from_db()
        self.assertIn('dry run', out.getvalue())
        self.assertGreater(bld.p_exists, 0.99)
        snapshots = BeliefSnapshot.objects.count()
        call_command('rerun_beliefs', '--apply', stdout=out)
        bld.refresh_from_db()
        self.assertAlmostEqual(bld.p_exists, pooled, places=6)
        self.assertEqual(BeliefSnapshot.objects.filter(cause='looks').count(), BeliefSnapshot.objects.count() - snapshots)
        self.assertTrue(BeliefSnapshot.objects.filter(cause='looks', entity=bld).exists())
        self.assertEqual(Factor.objects.filter(superseded_at__isnull=False).count(), 0)

    def test_point_assessment_composes_the_objects_over_the_point(self):
        self._ingest('s1', self.t1, imagery=_imagery())
        k = 1 / np.cos(np.radians(LAT))
        url = '/webclient/sampler/world/assess'

        def at_m(x, y, **q):
            return self.client.get(url, {'lon': LON + x * M * k, 'lat': LAT + y * M, **q}).json()

        bld, car, road = (self._entity(c) for c in ('building', 'vehicle', 'road'))
        r = at_m(-40, 0)  # the middle of the 30 m building
        top = r['objects'][0]
        self.assertEqual((r['fused']['category'], top['id'], len(r['objects'])), ('building', bld.id, 1))
        self.assertEqual((r['looked_at']['n_captures'], r['looked_at']['n_looks'], r['beliefs']), (1, 1, 'as last seen'))
        self.assertGreater(top['weight'], 0.95)
        self.assertAlmostEqual(top['share'], top['weight'] * bld.p_exists, places=3)
        self.assertAlmostEqual(r['fused']['no_object'], 1 - top['share'], places=3)
        self.assertEqual(top['support'], {'n_looks': 1, 'n_found': 1, 'n_missed': 0, 'n_corrections': 0})
        self.assertIn('one image', r['note'])

        # A well located point on the car is the car; located only to the imagery's 2.5 m it is
        # mostly the road the car stands on. The car, being smaller, lies on top either way.
        sharp = at_m(10, 2, sigma_m=0.5)
        self.assertEqual((sharp['fused']['category'], [o['id'] for o in sharp['objects']]), ('vehicle', [car.id, road.id]))
        loose = at_m(10, 2)
        self.assertEqual((loose['fused']['category'], [o['id'] for o in loose['objects']]), ('road', [road.id, car.id]))
        self.assertTrue(0.1 < loose['objects'][1]['weight'] < 0.35)
        for got in (sharp, loose):
            self.assertAlmostEqual(sum(o['share'] for o in got['objects']) + got['fused']['no_object'], 1, places=3)
        # Three years on the car has probably left and the road has not.
        today = at_m(10, 2, sigma_m=0.5, at=timezone.now().date().isoformat())
        by_id = {o['id']: o for o in today['objects']}
        self.assertEqual(today['beliefs'], 'decayed to at')
        self.assertLess(abs(by_id[car.id]['p_exists'] - 0.5), 0.01)
        self.assertGreater(by_id[road.id]['share'], [o for o in sharp['objects'] if o['id'] == road.id][0]['share'])

        # Looked at and found empty is not the same as never looked at.
        empty = at_m(60, -60)
        self.assertEqual((empty['fused']['category'], empty['fused']['no_object'], empty['objects']), (None, 1.0, []))
        self.assertEqual(empty['looked_at']['n_captures'], 1)
        self.assertIn('no object was found', empty['note'])
        away = at_m(500, 0)
        self.assertEqual((away['looked_at']['n_captures'], away['fused']['no_object']), (0, 1.0))
        self.assertIn('No capture covers', away['note'])
        self.assertEqual(self.client.get(url, {'lon': 'east', 'lat': LAT}).status_code, 400)
        self.assertEqual(self.client.get(url, {'lon': LON, 'lat': LAT, 'taxonomy': 'nope'}).status_code, 400)


def _centre(ring):
    return [sum(p[0] for p in ring[:4]) / 4, sum(p[1] for p in ring[:4]) / 4]


def _pass(item_id, when):
    """A catalogue entry for a satellite pass that covers the test scene."""
    from shapely.geometry import box
    return {'source': 'sentinel-2-l2a', 'layer': 'ndvi', 'item_id': item_id, 'observed_at': when, 'gsd_m': 10.0,
            'look': f's2:{when:%Y-%m-%d}', 'geometry': box(LON - 0.1, LAT - 0.1, LON + 0.1, LAT + 0.1),
            'cloud_cover': 3.0, 'metadata': {'bands': ['green', 'red', 'nir', 'swir16'], 'assets': {}}}


def _green_roofs(cand, bounds_ll, tokens):
    """What a pass reads: 10 m pixels in UTM 12N, vegetation exactly under the two 30 m squares."""
    from affine import Affine
    from pyproj import Transformer

    tf = Transformer.from_crs(4326, 32612, always_xy=True)
    xa, ya = tf.transform(bounds_ll[0], bounds_ll[1])
    xb, yb = tf.transform(bounds_ll[2], bounds_ll[3])
    west, north = np.floor(min(xa, xb) / 10) * 10 - 60, np.ceil(max(ya, yb) / 10) * 10 + 60
    cols, rows = int((max(xa, xb) - west) // 10) + 7, int((north - min(ya, yb)) // 10) + 7
    xs, ys = west + 10 * (np.arange(cols) + 0.5), north - 10 * (np.arange(rows) + 0.5)
    green = np.zeros((rows, cols), dtype=bool)
    for ring in (_square(-40, 0, 15), _square(60, 60, 15)):
        cx, cy = tf.transform(*_centre(ring))
        green |= (np.abs(xs[None, :] - cx) <= 15) & (np.abs(ys[:, None] - cy) <= 15)
    red, nir = np.where(green, 0.05, 0.20), np.where(green, 0.45, 0.25)
    flat = np.full((rows, cols), 0.1)
    return [(layers.Grid(32612, Affine(10, 0, west, 0, -10, north), (rows, cols)), [flat, red, nir, flat],
             np.ones((rows, cols), dtype=bool))]


class FootprintTests(SimpleTestCase):
    """How much of a pixel's signal is an entity's."""

    def setUp(self):
        from affine import Affine
        from shapely.geometry import box
        self.grid = layers.Grid(32612, Affine(10, 0, 0, 0, -10, 200), (20, 20))
        self.big, self.tiny = box(50, 50, 80, 80), box(121, 121, 124, 124)   # 3 x 3 pixels; a tenth of a pixel
        self.values = np.full((20, 20), 0.1)
        self.values[12:15, 5:8] = 0.9   # rows count down from y = 200: the big square's nine pixels

    def test_sharp_sensor_sees_whole_pixels(self):
        fp = layers.coverage([self.big, self.tiny], self.grid, 0.0)
        means, clear, purity, n_px = layers.measure(fp, [self.values], np.ones((20, 20), dtype=bool))
        np.testing.assert_allclose([means[0, 0], purity[0], n_px[0], clear[0]], [0.9, 1.0, 9.0, 1.0], atol=1e-9)
        self.assertAlmostEqual(purity[1], 0.09, delta=0.04)   # one pixel, about nine hundredths of it the object
        self.assertAlmostEqual(means[1, 0], 0.1, places=6)

    def test_blur_mixes_in_the_surroundings_and_says_so(self):
        fp = layers.coverage([self.big, self.tiny], self.grid, 6.0)
        self.assertAlmostEqual(fp.totals[0], 9.0, delta=0.5)   # blurring moves weight; only faint pixels are dropped
        means, clear, purity, _ = layers.measure(fp, [self.values], np.ones((20, 20), dtype=bool))
        self.assertTrue(0.5 < means[0, 0] < 0.85)
        self.assertTrue(layers.MIN_PURITY < purity[0] < 0.9)
        self.assertAlmostEqual(clear[0], 1.0, places=9)
        self.assertFalse(purity[1] >= layers.MIN_PURITY)     # too faint to say anything about
        # Cloud over the western third of the square: about two thirds of its weight is left.
        cloud = np.ones((20, 20), dtype=bool)
        cloud[:, :6] = False
        _, clear, _, _ = layers.measure(fp, [self.values], cloud)
        self.assertTrue(0.55 < clear[0] < 0.8)
        stats, clear, purity, _ = layers.measure_quantiles(fp, self.values, np.ones((20, 20), dtype=bool))
        self.assertAlmostEqual(stats[0, 1], 0.9, places=6)   # the median sits inside the square
        self.assertLess(stats[0, 0], 0.9)                    # the lower quartile is the blurred rim
        fp = layers.coverage([self.big], layers.Grid(32612, self.grid.transform, (10, 20)), 6.0)
        self.assertEqual(fp.weights.nnz, 0)                  # the square lies below a grid of only ten rows
        self.assertAlmostEqual(fp.totals[0], 9.0, delta=0.5)


class LayerTests(TransactionTestCase):
    """Remote-sensing samples on entities, and the basemap re-check."""

    databases = {'default', 'observations'}

    def setUp(self):
        self.t1 = timezone.now() - timedelta(hours=1)
        self.passes = [('T12SVC_a', IMAGED + timedelta(days=2, hours=18)),
                       ('T12SVB_a', IMAGED + timedelta(days=2, hours=18, seconds=14)),   # the same pass, next tile
                       ('T12SVC_b', IMAGED + timedelta(days=400, hours=18))]
        for name, value in (('sentinel2_candidates', lambda *a, **k: [_pass(i, t) for i, t in self.passes]),
                            ('naip_candidates', lambda *a, **k: []), ('lidar_candidates', lambda: [])):
            patch = mock.patch.object(layers, name, side_effect=value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.dict(layers.READERS, {'sentinel-2-l2a': _green_roofs})
        patch.start()
        self.addCleanup(patch.stop)
        layers._stats_cache.clear()

    def _watch(self, *args):
        out = StringIO()
        call_command('watch_layers', '--json', *args, stdout=out)
        return json.loads(out.getvalue())['sources']['sentinel2']

    def test_passes_are_sampled_once_and_change_no_belief(self):
        fusion.ingest_scene_graph(_scene(self.t1, imagery=_imagery()), session_id='s1', taxonomy_name='urban_v1')
        bld = Entity.objects.get(category='building')
        before = (list(bld.posterior), bld.p_exists, Factor.objects.count(), BeliefSnapshot.objects.count())

        dry = self._watch()
        self.assertEqual((dry['scenes_to_read'], dry['scenes_read'], LayerScene.objects.count()), (2, 1, 0))
        rep = self._watch('--apply')
        self.assertEqual((rep['scenes_new'], rep['scenes_read'], rep['failed']), (2, 2, 0))
        # one scene per look: the second tile of the first pass shows the same pixels
        self.assertEqual(sorted(LayerScene.objects.values_list('item_id', flat=True)), ['T12SVB_a', 'T12SVC_b'])
        mine = LayerSample.objects.filter(entity=bld)
        self.assertEqual(mine.count(), 2)
        s = mine.first()
        self.assertTrue(0.4 < s.value < 0.8)                 # 0.8 on the roof, 0.11 around it
        self.assertTrue(layers.MIN_PURITY < s.purity < 0.9)
        self.assertEqual((round(s.clear, 3), len(s.bands)), (1.0, 4))
        # a 3 m car under 10 m pixels is its surroundings: nothing is stored for it
        self.assertFalse(LayerSample.objects.filter(entity__category='vehicle').exists())
        bld.refresh_from_db()
        self.assertEqual((list(bld.posterior), bld.p_exists, Factor.objects.count(), BeliefSnapshot.objects.count()),
                         before)

        again = self._watch('--apply')
        self.assertEqual((again['scenes_to_read'], again['samples']), (0, 0))

        # A second capture adds a building: only it is read from the scenes already known.
        sg = _scene(self.t1 + timedelta(minutes=20), imagery=_imagery())
        sg['nodes'].append(_node('b2', 'building', _square(60, 60, 15)))
        fusion.ingest_scene_graph(sg, session_id='s2', taxonomy_name='urban_v1')
        more = self._watch('--apply')
        self.assertEqual((more['scenes_to_read'], more['entities_to_sample'], more['samples']), (2, 2, 2))
        self.assertEqual(LayerSample.objects.filter(entity=bld).count(), 2)

        d = self.client.get(f'/webclient/sampler/world/entities/{bld.id}').json()
        row, = d['layers']
        self.assertEqual((row['source'], row['layer'], row['n'], row['series_step']), ('sentinel-2-l2a', 'ndvi', 2, 'sample'))
        self.assertEqual([p[0] for p in row['series']], ['2023-06-03', '2024-07-05'])
        self.assertEqual(row['at_last_seen']['n'], 1)        # one pass within a month of the imagery date
        self.assertEqual(row['latest']['value'], row['series'][-1][1])
        stats = self.client.get('/webclient/sampler/world/stats').json()['layers']
        self.assertEqual((stats[0]['n_scenes'], stats[0]['n_entities']), (2, LayerSample.objects.values('entity').distinct().count()))

    def test_a_pass_that_cannot_be_read_is_tried_again(self):
        fusion.ingest_scene_graph(_scene(self.t1, imagery=_imagery()), session_id='s1', taxonomy_name='urban_v1')

        def offline(cand, bounds_ll, tokens):
            raise OSError('connection reset')

        with mock.patch.dict(layers.READERS, {'sentinel-2-l2a': offline}):
            rep = self._watch('--apply')
        self.assertEqual((rep['failed'], rep['samples'], LayerSample.objects.count()), (2, 0, 0))
        self.assertTrue(all('not read' in s.metadata['note'] for s in LayerScene.objects.all()))
        rep = self._watch('--apply')
        self.assertEqual((rep['failed'], rep['scenes_read']), (0, 2))
        self.assertTrue(LayerSample.objects.exists())
        self.assertFalse(any('note' in s.metadata for s in LayerScene.objects.all()))

    def test_basemap_that_moved_on_flags_the_capture_until_it_is_redone(self):
        fusion.ingest_scene_graph(_scene(self.t1, imagery=_imagery()), session_id='s1', taxonomy_name='urban_v1')
        url = '/webclient/sampler/world/imagery_checks'
        box = {'bbox': f'{LON - 0.01},{LAT - 0.01},{LON + 0.01},{LAT + 0.01}'}

        def post(session_id, imagery):
            return self.client.post(url, json.dumps({'checks': [{'session_id': session_id, 'imagery': imagery}]}),
                                    content_type='application/json')

        # The look-up needs the key a page holds: only a signed-in page is asked for it.
        self.assertEqual(self.client.get(url, box).json()['due'], [])
        self.assertEqual(post('s1', _imagery()).status_code, 401)
        self.client.force_login(get_user_model().objects.create_user('sg_watch', password='x'))
        due, = self.client.get(url, box).json()['due']
        self.assertEqual((due['session_id'], len(due['corners']), due['image_size'], due['start'], due['end']),
                         ('s1', 4, [1000, 800], '2023-03-01', '2023-09-01'))

        self.assertEqual(post('s1', {'source': 'host:tiles.example', 'layers': []}).json()['recorded'], 0)
        r = post('s1', _imagery()).json()
        self.assertEqual((r['recorded'], r['flags']), (1, []))
        self.assertEqual(self.client.get(url, box).json()['due'], [])   # looked up moments ago

        r = post('s1', _imagery('2025-01-01', '2025-03-01')).json()
        self.assertEqual([(f['session_id'], f['now']['end']) for f in r['flags']], [('s1', '2025-03-01')])
        chk = ImageryCheck.objects.order_by('-id').first()
        self.assertEqual((chk.changed, chk.newer), (True, True))
        stats = self.client.get('/webclient/sampler/world/stats').json()['imagery_checks']
        self.assertEqual((stats['n_dated_captures'], stats['n_checked_recently'], stats['n_to_recapture']), (1, 1, 1))
        cap = Capture.objects.get(session_id='s1')
        self.assertEqual(cap.imagery_end.date().isoformat(), '2023-09-01')   # the stored evidence keeps its date

        fusion.ingest_scene_graph(_scene(timezone.now(), imagery=_imagery('2025-01-01', '2025-03-01')),
                                  session_id='s2', taxonomy_name='urban_v1')
        self.assertEqual(self.client.get(url, box).json()['flags'], [])


class ZoneMapTests(TransactionTestCase):
    """The fused map of a zone: the point assessment on a grid, drawn, kept current and served."""

    databases = {'default', 'observations'}

    def setUp(self):
        self.t1 = timezone.now() - timedelta(hours=1)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        root = override_settings(OBSERVATIONS_ROOT=self.dir.name)
        root.enable()
        self.addCleanup(root.disable)
        zone_views._latest.clear()
        call_command('add_zone', 'test/site', '--name', 'Test site',
                     f'--bbox={LON - 0.01},{LAT - 0.01},{LON + 0.01},{LAT + 0.01}', stdout=StringIO())
        self.zone = Zone.objects.get(slug='test/site')
        self.base = '/world-model/zones/test/site'

    def _ingest(self, name, at, **kw):
        return fusion.ingest_scene_graph(_scene(at, imagery=_imagery(), **kw), session_id=name, taxonomy_name='urban_v1')

    def _draw(self, *args):
        out = StringIO()
        call_command('render_zone_maps', '--no-backdrop', '--json', *args, stdout=out)
        return json.loads(out.getvalue())['drawn'] if out.getvalue().strip() else []

    def test_every_cell_is_the_point_assessment(self):
        from pyproj import Transformer

        self._ingest('s1', self.t1)
        ents = list(Entity.objects.filter(retired_at__isnull=True))
        feet = [fusion._from_geos(c.footprint) for c in Capture.objects.all()]
        grid = zonemap.frame(self.zone, feet)
        self.assertEqual((grid.epsg, grid.pixel_m), (32612, 2.0))
        fused = zonemap.fuse(ents, grid, URBAN_V1)
        count, finest = zonemap.looked_at([zonemap._project(g, grid.epsg) for g in feet],
                                          [c.gsd_m for c in Capture.objects.all()], grid)
        to_xy = Transformer.from_crs(4326, grid.epsg, always_xy=True)
        k = 1 / np.cos(np.radians(LAT))

        def both(x_m, y_m):
            lon, lat = LON + x_m * M * k, LAT + y_m * M
            col, row = ~grid.transform * to_xy.transform(lon, lat)
            return (int(row), int(col)), assess.assess_point(lon, lat)

        cell, point = both(-40, 0)   # the middle of the building
        bld = Entity.objects.get(category='building')
        self.assertEqual(URBAN_V1.name_of(int(fused.label[cell])), point['fused']['category'])
        self.assertAlmostEqual(float(fused.obj[cell]), 1 - point['fused']['no_object'], delta=0.02)
        self.assertAlmostEqual(float(fused.conf[cell]), max(bld.posterior), delta=0.02)
        self.assertEqual(ents[int(fused.owner[cell])].id, bld.id)
        cell, point = both(10, 2)    # the car: under the imagery's 2.5 m it is mostly the road it stands on
        self.assertEqual((URBAN_V1.name_of(int(fused.label[cell])), point['fused']['category']), ('road', 'road'))
        self.assertAlmostEqual(float(fused.obj[cell]), 1 - point['fused']['no_object'], delta=0.08)
        cell, point = both(60, -60)  # looked at, nothing stored
        self.assertEqual((int(fused.label[cell]), int(fused.owner[cell]), int(count[cell])), (-1, -1, 1))
        self.assertLess(float(fused.obj[cell]), zonemap.SHOW_MIN)
        self.assertAlmostEqual(float(finest[cell]), Capture.objects.get().gsd_m, places=4)
        cell, point = both(180, 0)   # in the frame, beyond the capture
        self.assertEqual((int(count[cell]), point['looked_at']['n_captures']), (0, 0))
        self.assertTrue(np.isinf(finest[cell]))
        # an object believed gone leaves the ground to what lies under it
        Entity.objects.filter(id=bld.id).update(p_exists=0.02)
        gone = zonemap.fuse(list(Entity.objects.filter(retired_at__isnull=True)), grid, URBAN_V1)
        cell, _ = both(-40, 0)
        self.assertEqual(int(gone.label[cell]), -1)

    def test_map_is_drawn_when_the_store_changes_and_served(self):
        # a zone with no map yet says so, and has nothing to download
        page = self.client.get(self.base)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'still being drawn')
        self.assertEqual(self.client.get(self.base + '.pdf').status_code, 404)
        self.assertEqual(self.client.get(self.base + '.json').json()['status'], 'pending')

        self._ingest('s1', self.t1)
        drawn, = self._draw()
        self.assertEqual((drawn['zone'], drawn['why'], drawn['objects'], drawn['captures'], drawn['photograph']),
                         ('test/site', 'no map yet', 3, 1, False))
        root = zonemap.zone_root(self.zone)
        self.assertEqual(root, os.path.join(self.dir.name, 'maps', 'zones', 'test', 'site'))
        for kind, magic in (('pdf', b'%PDF'), ('png', b'\x89PNG'), ('jpg', b'\xff\xd8')):
            with open(zonemap.file_path(self.zone, kind), 'rb') as fh:
                self.assertEqual(fh.read(len(magic)), magic)
        self.assertEqual(self._draw(), [])                        # nothing changed: nothing is drawn
        self.assertEqual(zonemap.due(self.zone), '')              # no photograph, but drawn moments ago
        with mock.patch.object(zonemap, 'RETRY_BACKDROP_S', 0):
            self.assertIn('photograph', zonemap.due(self.zone))
            self.assertEqual(zonemap.due(self.zone, with_backdrop=False), '')

        info = self.client.get(self.base + '.json').json()
        self.assertEqual((info['status'], info['latest'], info['beliefs'], info['backdrop']),
                         ('success', True, 'as last seen', None))
        self.assertEqual((info['objects']['n'], info['looked_at']['n_captures'], info['looked_at']['n_looks']), (3, 1, 1))
        self.assertEqual({r['category']: r['n'] for r in info['objects']['by_category']},
                         {'building': 1, 'road': 1, 'vehicle': 1})
        area = {r['category']: r['area_ha'] for r in info['objects']['by_category']}
        self.assertAlmostEqual(area['building'], 0.09 * Entity.objects.get(category='building').p_exists, delta=0.012)
        self.assertAlmostEqual(info['ground']['viewed_ha'], 4.0, delta=0.15)   # one 200 m capture
        self.assertAlmostEqual(info['ground']['viewed_ha'] + info['ground']['never_viewed_ha'],
                               info['ground']['frame_ha'], delta=0.11)
        self.assertEqual(info['links']['pdf'], self.base + '.pdf')
        self.assertIn('Bing Aerial, 1 Mar to 1 Sep 2023', info['headline'])

        page = self.client.get(self.base)
        self.assertContains(page, 'World model: Test site')
        self.assertContains(page, self.base + '.pdf?download=1')
        self.assertNotContains(page, 'store has changed')
        self.assertContains(self.client.get('/world-model/'), 'Test site')
        self.assertEqual(self.client.get('/world-model/zones/no/where').status_code, 404)
        self.assertEqual(self.client.get(self.base + '.exe').status_code, 404)
        self.assertEqual(self.client.post(self.base).status_code, 405)

        pdf = self.client.get(self.base + '.pdf')
        self.assertEqual((pdf.status_code, pdf['Content-Type'], pdf['Cache-Control']), (200, 'application/pdf', 'no-cache'))
        self.assertEqual(b''.join(pdf.streaming_content)[:4], b'%PDF')
        self.assertTrue(pdf['Content-Disposition'].startswith('inline; filename="deepgis-world-model-test-site-'))
        saved = self.client.get(self.base + '.png', {'download': 1})
        self.assertTrue(saved['Content-Disposition'].startswith('attachment; filename="deepgis-world-model-test-site-'))
        saved.close()
        again = self.client.get(self.base + '.pdf', HTTP_IF_NONE_MATCH=pdf['ETag'])
        self.assertEqual((again.status_code, again['ETag']), (304, pdf['ETag']))

        # The store changes: the page says the map is behind until the next run draws it again.
        sg = _scene(self.t1 + timedelta(minutes=20), imagery=_imagery())
        sg['nodes'].append(_node('b2', 'building', _square(60, 60, 15)))
        fusion.ingest_scene_graph(sg, session_id='s2', taxonomy_name='urban_v1')
        zone_views._latest.clear()
        self.assertFalse(self.client.get(self.base + '.json').json()['latest'])
        self.assertContains(self.client.get(self.base), 'store has changed')
        drawn, = self._draw()
        self.assertEqual((drawn['why'], drawn['objects'], drawn['captures']), ('the store changed', 4, 2))
        zone_views._latest.clear()
        info = self.client.get(self.base + '.json').json()
        self.assertEqual((info['latest'], info['looked_at']['n_looks'], info['state']), (True, 1, drawn['state']))
        self.assertNotEqual(self.client.get(self.base + '.pdf')['ETag'], pdf['ETag'])

    def test_zones_are_named_once(self):
        with self.assertRaises(CommandError):
            call_command('add_zone', 'test/site', '--name', 'Again', '--bbox=0,0,1,1', stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command('add_zone', 'Test Site', '--name', 'Bad slug', '--bbox=0,0,1,1', stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command('add_zone', 'test/two', '--name', 'Two outlines', '--bbox=0,0,1,1', '--census-place', '0473000',
                         stdout=StringIO())
        call_command('add_zone', 'test/site', '--name', 'Renamed', f'--bbox={LON - 0.02},{LAT - 0.01},{LON + 0.01},{LAT + 0.01}',
                     '--replace', stdout=StringIO())
        zone = Zone.objects.get(slug='test/site')
        self.assertEqual((zone.name, zone.area.geom_type, Zone.objects.count()), ('Renamed', 'MultiPolygon', 1))
        self.assertNotEqual(zonemap.fingerprint(zone), zonemap.fingerprint(self.zone))
