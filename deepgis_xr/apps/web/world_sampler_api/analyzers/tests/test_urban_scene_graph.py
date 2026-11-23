"""urban_v1 taxonomy, Q_s lifting and the ultralytics SceneGraph adapter."""

import numpy as np
from django.test import SimpleTestCase
from kernelcal.distinction_game import PHX_URBAN_V0, default_q_s_table

from deepgis_xr.apps.web.world_sampler_api.scene_graph_adapters import adapt_kernel_result
from deepgis_xr.apps.web.world_sampler_api.urban_taxonomy import (
    UNMAPPED_PROMPT,
    URBAN_V1,
    pick_taxonomy,
    q_s_table_for,
)

CORNERS = [(-111.9459, 33.4274), (-111.9411, 33.4274), (-111.9411, 33.4246), (-111.9459, 33.4246)]


def _result(model, detections, family=None):
    return {'yolo_model': model, 'family': family, 'image_size': [1000, 800], 'detections': detections}


def _det(label, ring=None, bbox=(100, 100, 200, 180)):
    return {'detection_id': 0, 'class_name': label, 'confidence': 0.8, 'bbox': list(bbox),
            'mask_polygons_norm': [ring] if ring else []}


class UrbanTaxonomyTests(SimpleTestCase):
    def test_every_q_s_is_column_stochastic(self):
        for sid, cm in q_s_table_for(URBAN_V1).items():
            m = np.asarray(cm.matrix)
            self.assertEqual(m.shape[1], URBAN_V1.n, sid)
            np.testing.assert_allclose(m.sum(axis=0), 1.0, err_msg=sid)

    def test_lifted_child_matches_parent_column(self):
        v0 = np.asarray(default_q_s_table(taxonomy=PHX_URBAN_V0)['osm'].matrix)
        v1 = np.asarray(q_s_table_for(URBAN_V1)['osm'].matrix)
        np.testing.assert_allclose(v1[:, URBAN_V1.index_of('house')], v0[:, PHX_URBAN_V0.index_of('building')])
        np.testing.assert_allclose(v1[:, URBAN_V1.index_of('pool')], v0[:, PHX_URBAN_V0.index_of('water')])

    def test_pool_prompt_favours_pool_over_water(self):
        cm = q_s_table_for(URBAN_V1)['sam3']
        row = np.asarray(cm.matrix)[cm.native_labels.index('swimming pool')]
        self.assertGreater(row[URBAN_V1.index_of('pool')], row[URBAN_V1.index_of('water')])

    def test_mr_rocks_rock_points_at_unknown_not_debris(self):
        for tax in (PHX_URBAN_V0, URBAN_V1):
            cm = q_s_table_for(tax)['mr_rocks']
            m = np.asarray(cm.matrix)
            np.testing.assert_allclose(m.sum(axis=0), 1.0)
            row = m[list(cm.native_labels).index('rock')]
            self.assertEqual(int(np.argmax(row)), tax.index_of('unknown'), tax.name)
            self.assertLessEqual(row[tax.index_of('debris')], row[tax.index_of('pavement')] + 1e-9, tax.name)
            self.assertAlmostEqual(row[tax.index_of('building')], 0.45, places=6)

    def test_pick_taxonomy(self):
        self.assertIs(pick_taxonomy(None, ['osm', 'mr_rocks']), PHX_URBAN_V0)
        self.assertIs(pick_taxonomy(None, ['osm', 'sam3']), URBAN_V1)
        self.assertIs(pick_taxonomy('phx_urban_v0', ['sam3']), PHX_URBAN_V0)


class UltralyticsAdapterTests(SimpleTestCase):
    def test_source_id_follows_served_model(self):
        ring = [[0.1, 0.1], [0.3, 0.1], [0.3, 0.3], [0.1, 0.3], [0.1, 0.1]]
        cases = [('sam3', None, 'sam3'), ('yoloe-26l-seg', 'yoloe', 'yoloe'), ('yolo26x-seg', 'yolo', 'yolo26')]
        for model, family, expected in cases:
            claims = adapt_kernel_result('yolov8', _result(model, [_det('car', ring)], family), corners_lonlat=CORNERS)
            self.assertEqual([c.source_id for c in claims], [expected], model)
            self.assertIsNotNone(claims[0].geo_polygon)

    def test_prompts_map_to_native_labels(self):
        claims = adapt_kernel_result('sam3', _result('sam3', [_det('Swimming Pool'), _det('mailbox')]),
                                     corners_lonlat=CORNERS)
        self.assertEqual([c.native_label for c in claims], ['swimming pool', UNMAPPED_PROMPT])

    def test_every_native_label_has_a_q_s_row(self):
        table = q_s_table_for(URBAN_V1)
        claims = adapt_kernel_result('yolov8', _result('yolo26x-seg', [_det('car'), _det('person')]),
                                     corners_lonlat=CORNERS)
        for claim in claims:
            self.assertIn(claim.native_label, table['yolo26'].native_labels)
