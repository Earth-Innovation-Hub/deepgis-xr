"""The YOLO branch proxies to ultralytics-api and draws one polygon per ring."""

import json
import tempfile
from pathlib import Path
from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings
from PIL import Image

from deepgis_xr.apps.web.world_sampler_api.analyzers import yolov8

LOCATION = {'lat': 33.42, 'lon': -111.93, 'alt': 300}
SQUARE = [[0.1, 0.1], [0.3, 0.1], [0.3, 0.3], [0.1, 0.3], [0.1, 0.1]]
SECOND = [[0.6, 0.6], [0.7, 0.6], [0.7, 0.7], [0.6, 0.6]]


def _service_reply(status=200, **body):
    reply = mock.Mock(status_code=status)
    reply.json.return_value = body
    return reply


class YoloRemoteTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(yolov8, 'RESULTS_ROOT', Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.image = Image.new('RGB', (200, 100), (90, 90, 90))

    def _run(self, model='yolo26x-seg', classes=''):
        response = yolov8._analyze_viewport_yolov8(self.image, LOCATION, 0.25, model, classes, None)
        return response.status_code, json.loads(response.content)

    @override_settings(ULTRALYTICS_API_URL='')
    def test_unset_url_degrades(self):
        status, body = self._run()
        self.assertEqual(status, 200)
        self.assertTrue(body['degraded'])
        self.assertEqual(body['unavailable_reason'], 'not_configured')

    @override_settings(ULTRALYTICS_API_URL='http://ultralytics-api:5000')
    def test_refused_connection_degrades(self):
        with mock.patch('requests.post', side_effect=requests.exceptions.ConnectionError('refused')):
            status, body = self._run()
        self.assertEqual(status, 200)
        self.assertEqual(body['unavailable_reason'], 'connection_error')

    @override_settings(ULTRALYTICS_API_URL='http://ultralytics-api:5000')
    def test_missing_sam3_weights_degrades(self):
        reply = _service_reply(503, success=False, reason='weights_missing', error='sam3.pt is not here')
        with mock.patch('requests.post', return_value=reply):
            status, body = self._run(model='sam3', classes='building')
        self.assertEqual(status, 200)
        self.assertEqual(body['unavailable_reason'], 'weights_missing')

    @override_settings(ULTRALYTICS_API_URL='http://ultralytics-api:5000')
    def test_bad_request_is_an_error(self):
        reply = _service_reply(400, success=False, error='yoloe-26l-seg needs a list of things to find')
        with mock.patch('requests.post', return_value=reply):
            status, body = self._run(model='yoloe-26l-seg')
        self.assertEqual(status, 400)
        self.assertEqual(body['status'], 'error')
        self.assertIn('needs a list', body['message'])

    @override_settings(ULTRALYTICS_API_URL='http://ultralytics-api:5000')
    def test_masks_become_one_feature_per_ring(self):
        reply = _service_reply(
            success=True, model='yoloe-26l-seg', family='yoloe', classes=['building'],
            unknown_classes=[], device='cuda:0', cuda_available=True, gpu_name='RTX 2080 Ti',
            inference_ms=120,
            detections=[
                {'detection_id': 1, 'class_id': 0, 'class_name': 'building', 'confidence': 0.8,
                 'bbox': [20, 10, 140, 70], 'area': 900, 'mask_polygons_norm': [SQUARE, SECOND]},
                {'detection_id': 2, 'class_id': 0, 'class_name': 'building', 'confidence': 0.5,
                 'bbox': [150, 50, 190, 90], 'area': 1600, 'mask_polygons_norm': []},
            ],
        )
        with mock.patch('requests.post', return_value=reply) as post:
            status, body = self._run(model='yoloe-26l-seg', classes='building')
        self.assertEqual(status, 200)
        self.assertEqual(post.call_args.kwargs['data']['model'], 'yoloe-26l-seg')
        self.assertEqual(post.call_args.kwargs['data']['classes'], 'building')
        features = body['geojson']['features']
        self.assertEqual(len(features), 3)
        self.assertEqual([f['properties']['has_mask'] for f in features], [True, True, False])
        self.assertEqual(body['num_detections'], 2)
        self.assertEqual(body['yolo_model'], 'yoloe-26l-seg')
        self.assertTrue(body['device_info']['cuda_available'])
        session = Path(self.tmp.name) / body['saved_to']['session_dir']
        self.assertTrue((session / 'detections.geojson').exists())
        self.assertTrue((session / 'query_image.png').exists())

