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
| `scripts/port_shim.py`  | backward-compat proxy for legacy 5003-5009 ports (see below) |
| `nginx-port-shims.conf` | reference-only sketch for an nginx-based shim (use the python one) |

## Unified-service rollout (consolidating ports 5003-5009)

This image was originally deployed eight times — one container per
family, each with its own `DEFAULT_MODEL_ID` env var, on ports
5002-5009. The web container (`deepgis-xr/web`) had a matching
`MASKRCNN_*_API_URL` env var per family.

Because every instance ran the **same image** with the **same
registry** (the registry walks `WEIGHTS_ROOT` and discovers all
checkpoints), running eight copies wastes ~8x GPU memory for nothing.
Consolidation runs **one** container with all weight bundles mounted
and lets the per-request `model_id` form field select the family.

### Web-side (this repo)

Already done. The deepgis-xr analyzer dispatch
(`deepgis_xr/apps/web/world_sampler_api/analyzers/_maskrcnn_remote.py::resolve_remote_maskrcnn_url`)
prefers `MASKRCNN_API_URL` over `MASKRCNN_*_API_URL` and injects the
family default `model_id` automatically. To use it:

```bash
# .env
MASKRCNN_API_URL=http://192.168.0.232:5002
# Optional: drop per-family URLs as each family is migrated.
# MASKRCNN_HYPOLITH_API_URL=
# ...
```

The per-family URLs take precedence when set, so rollout can be
gradual: leave them all set, set `MASKRCNN_API_URL` too, then drop
them one by one once the unified container has been verified for
each family in production.

### Server-side rollout on `192.168.0.232`

1. **Bring up the unified container** on 5002 with all eight family
   weight bundles bind-mounted, and no `DEFAULT_MODEL_ID` (the
   container falls back to the registry default — typically the rocks
   flagship — but every family is selectable via `model_id`):

   ```bash
   docker run -d --name maskrcnn-unified \
       --gpus all -p 5002:8000 \
       -v /mnt/22tb-hdd/maskrcnn:/weights:ro \
       maskrcnn-rocks:latest
   ```

2. **Verify the registry**:

   ```bash
   curl http://192.168.0.232:5002/api/models | jq '.models | length'
   # Expect 50+ entries spanning all eight families.
   curl -F 'file=@viewport.jpg' \
        -F 'model_id=gobabeb_hero_e0011' \
        http://192.168.0.232:5002/api/predict | jq '.predictions.count'
   ```

3. **Shim the legacy ports** for non-Django direct clients (operator
   curls, external scripts) using `scripts/port_shim.py`. One process
   per legacy port, all proxying to 5002:

   ```bash
   for port in 5003 5004 5005 5006 5007 5008 5009; do
     SHIM_LISTEN_PORT=$port \
     SHIM_UPSTREAM=http://127.0.0.1:5002 \
     systemd-run --unit=maskrcnn-shim-$port \
       /usr/bin/python3 /opt/deepgis-xr/scripts/port_shim.py
   done
   ```

   Or as a systemd template unit; see `port_shim.py` docstring.

4. **Stop the per-family containers** one at a time, verifying the
   shim picks up traffic for that port:

   ```bash
   docker stop maskrcnn-hypolith-api && docker rm $_
   curl -F 'file=@viewport.jpg' http://192.168.0.232:5004/api/predict
   #   ^ now goes through the shim; should still return hypolith
   #   detections because the shim injects model_id=gobabeb_hero_e0011.
   ```

5. **Set `MASKRCNN_API_URL` on the deepgis-xr web container** and
   restart it. From this point on, the web client routes directly to
   :5002 (skipping the shims entirely):

   ```bash
   # .env on 192.168.0.186
   MASKRCNN_API_URL=http://192.168.0.232:5002
   docker compose up -d --no-deps web celery_worker
   ```

6. **Retire the shims** once production traffic confirms no client
   is hitting 5003-5009 directly. Drop the per-family
   `MASKRCNN_*_API_URL` lines from the deepgis-xr `.env` last.

### Family default model_ids (the "single contract")

These three lists must stay in lockstep:

  * `default_model_id=` in
    `deepgis_xr/apps/web/world_sampler_api/analyzers/maskrcnn_*.py`
  * `_DEFAULT_MODEL_ID_*` constants in `maskrcnn_rocks.py` /
    `maskrcnn_house.py`
  * `FAMILY_DEFAULTS` dict in `services/maskrcnn-rocks/scripts/port_shim.py`
  * `map $server_port $family_default_model_id` in
    `services/maskrcnn-rocks/nginx-port-shims.conf`

If you change a family's canonical checkpoint, update all four.

| port | family            | default `model_id`                              |
|------|-------------------|--------------------------------------------------|
| 5002 | rocks             | `bishop_hero_e0004`                              |
| 5003 | house             | `tornado_detector_eureka_aug_mult_e0039`         |
| 5004 | hypolith          | `gobabeb_hero_e0011`                             |
| 5005 | litter            | `litter_dynamics_hero_e0008`                     |
| 5006 | roadkill          | `roadkill__sarah_e0004`                          |
| 5007 | newlife           | `new_life_hero_e0008`                            |
| 5008 | brent moon craters| `moon_craters_brent_brent_e0009`                 |
| 5009 | harish moon craters | `hanand_stragglers_download.openuas.us_e0099` |
