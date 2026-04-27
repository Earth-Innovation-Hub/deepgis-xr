# sam-api

Remote Segment Anything (classic SAM v1) service for DeepGIS-XR viewport
segmentation.

| Service | Port | Default model | GPU | Notes |
| --- | ---: | --- | ---: | --- |
| `sam-api` | 5010 | `vit_b` | 0 | Supports `vit_b`, `vit_l`, `vit_h` via `model_type` |

Checkpoints are mounted from `./checkpoints` and are intentionally not baked
into the Docker image:

- `sam_vit_b_01ec64.pth`
- `sam_vit_l_0b3195.pth`
- `sam_vit_h_4b8939.pth`

The container is configured for low idle VRAM:

- `SAM_EAGER_WARMUP=false`
- `SAM_UNLOAD_AFTER_PREDICT=true`
- `SAM_EMPTY_CACHE_AFTER_PREDICT=true`

Useful endpoints:

```bash
curl -fsS http://localhost:5010/health | jq .
curl -fsS http://localhost:5010/api/models | jq .
curl -X POST http://localhost:5010/api/unload | jq .
```
