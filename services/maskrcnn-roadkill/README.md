# maskrcnn-roadkill

Sibling of [`../maskrcnn-rocks`](../maskrcnn-rocks).

| Service | Port | Default checkpoint | Classes |
|---|---|---|---|
| `maskrcnn-roadkill-api` | 5006 | `roadkill__sarah_e0004` | 2: `[background, roadkill]` |

## Default model

`roadkill__sarah_e0004` — `/mnt/22tb-hdd/maskrcnn/terrestrial/deepgis_roadkill/roadkill_epoch_0004_sarah.param`. Sarah's roadkill-on-roads run, only 4 epochs — preview-quality, not production. Treat results as candidate detections to be re-verified.

## Running on tesseract

```bash
cd /home/jdas/deepgis-xr/services/maskrcnn-roadkill
docker compose up -d
curl -fsS http://localhost:5006/health | jq .
```
