# maskrcnn-rocks-api

A REST service that serves every rock-focused Mask R-CNN checkpoint in
`/mnt/22tb-hdd/maskrcnn/terrestrial/`, patterned on the `groundingdino-api`
container already running on tesseract (`jdas@192.168.0.232:5000`).

> **Flagship model:** `bishop_hero_e0004` — `bishop_jezero_field/epoch_0004.param`
> (168 MB, June 2020, md5 `c5d06109`).  This is the Bishop / Jezero-analog
> rock detector from a training run separate from the 17-variant ablation
> sweep also exposed by this service.

## Why this exists

| Container            | Port | Task                           | Prompt style     |
|----------------------|------|--------------------------------|------------------|
| `groundingdino-api`  | 5000 | Open-vocab 2D detection        | free-text        |
| `groundedsam2-api`   | 5001 | Open-vocab detection + masks   | free-text        |
| **`maskrcnn-rocks-api`** | **5002** | **Rock instance segmentation**  | `model_id`     |

All three expose the *same* REST shape so the deepgis-xr frontend can route
to any of them by switching a dropdown and an env var.

## REST contract

```
GET  /                  demo page
GET  /health            {status, device, cuda_available, num_models}
GET  /api/info          service + active default
GET  /api/models        full registry (every .param auto-discovered)
POST /api/predict       multipart or JSON → JSON with boxes/scores/masks/vis
GET  /api/result/<f>    fetch a saved annotated JPEG
```

### `POST /api/predict`

Either multipart form with `file`, or JSON `{image: "<base64>", filename: "..."}`.

Common form fields / JSON keys:

| field            | default              | notes                                      |
|------------------|----------------------|--------------------------------------------|
| `model_id`       | `$DEFAULT_MODEL_ID`  | any id returned by `GET /api/models`       |
| `score_threshold`| `0.5`                | detection confidence                       |
| `mask_threshold` | `0.5`                | binarize `mask > mask_threshold`           |
| `max_detections` | `200`                | cap (also bounded by head config)          |
| `return_annotated`| `true`              | include base64 JPEG + `result_url`         |

Response (abridged):

```json
{
  "success": true,
  "model_id": "bishop_hero_e0004",
  "model": {"family": "bishop", "variant": "hero", "...": "..."},
  "inference_ms": 412,
  "image_size": {"width": 1920, "height": 1080},
  "predictions": {
    "count": 37,
    "boxes":      [[x1,y1,x2,y2], ...],
    "boxes_norm": [[x1,y1,x2,y2], ...],
    "scores":     [0.97, 0.93, ...],
    "labels":     ["rock", "rock", ...],
    "masks_rle":  [{"size":[H,W], "counts":"..."}, ...],
    "areas":      [ 1820, 2010, ...]
  },
  "annotated_image": "data:image/jpeg;base64,...",
  "result_url":      "/api/result/result_xxxxx.jpg"
}
```

## Multi-channel inputs

Zhiang's training recipe supports inputs beyond RGB (4/5/6/8-channel).  For
RGB-only models (`*_rgb_*`, `bishop_hero_e0004`, `gobabeb_hero_e0011`) just
POST a JPG/PNG — the server handles it.  For multi-channel ablation models
(`*_rgbd1_*`, `*_rgbd3_*`, `*_mult_*`, `*_dem*_*`, `*_rgb_re_nir_*`), POST a
`.npy` file whose last axis matches the model's `input_channel` (auto-detected
from the checkpoint's `backbone.body.conv1.weight.shape[1]`).

## Build & run (on tesseract)

```bash
# from ~/maskrcnn-rocks/ on jdas@192.168.0.232:
docker compose build
docker compose up -d
docker logs -f maskrcnn-rocks-api
curl -s http://localhost:5002/health | jq
curl -s http://localhost:5002/api/models | jq '.count, .default_model_id'
```

Canonical test from deepgis-xr:

```bash
python scripts/client.py --health
python scripts/client.py --list | head -20
python scripts/client.py --image /mnt/22tb-hdd/datasets/terrestrial/bishop_jezero_field/zhiang_bishop/bishop2019.jpg \
                        --model bishop_hero_e0004 \
                        --output /tmp/bishop_annotated.jpg
```

## Integration with deepgis-xr

One env var and one router branch in
`deepgis_xr/apps/web/world_sampler_api.py` — mirrors the existing
`_analyze_viewport_grounding_dino` path.

```python
MASKRCNN_ROCKS_API_URL = os.environ.get(
    "MASKRCNN_ROCKS_API_URL", "http://192.168.0.232:5002")
```

and

```python
elif analysis_type == "maskrcnn_rocks":
    return _analyze_viewport_maskrcnn_rocks(image_pil, request_data, ...)
```

## Files

| file                    | purpose                                                     |
|-------------------------|-------------------------------------------------------------|
| `Dockerfile`            | `pytorch:2.3.0-cuda12.1-cudnn8-runtime` + Flask stack       |
| `docker-compose.yml`    | GPU reservation, RO bind-mount of the maskrcnn archive      |
| `requirements.txt`      | pinned deps (matches grounding-dino container's versions)   |
| `app.py`                | Flask routes: `/health /api/info /api/models /api/predict`  |
| `model.py`              | torchvision Mask R-CNN factory (ported from Zhiang's repo)  |
| `inference.py`          | image → tensor → post-process → annotate                    |
| `registry.py`           | auto-walk `WEIGHTS_ROOT`, build id→metadata map             |
| `templates/index.html`  | minimal web UI for smoke-testing                            |
| `scripts/client.py`     | CLI client (sibling of `grounding_dino_api_client.py`)      |
| `scripts/sanity_check_registry.py` | standalone registry dump                         |
| `tests/test_registry.py`| pytest on the filename parser                                |
