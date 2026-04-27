# maskrcnn-hypolith

Sibling of [`../maskrcnn-rocks`](../maskrcnn-rocks). Same image, same Dockerfile, same archive bind; only `DEFAULT_MODEL_ID` and `MASKRCNN_LABELS_<FAMILY>` differ.

| Service | Port | Default checkpoint | Classes |
|---|---|---|---|
| `maskrcnn-hypolith-api` | 5004 | `gobabeb_hero_e0011` | 2: `[background, hypolith]` |

## Default model

`gobabeb_hero_e0011` — `/mnt/22tb-hdd/maskrcnn/terrestrial/gobabeb_namib/epoch_0011.param`. Latest terrestrial trained `.param` in the curated archive (2021-08-03), Gobabeb Namib Research Institute hypolith work. The `gobabeb_*` family also contains 26 ablation siblings (`rock_*`, `c3_*`, `dem_*`) that this same container exposes by `model_id` without rebuild.

## Running on tesseract

```bash
cd /home/jdas/deepgis-xr/services/maskrcnn-hypolith
docker compose up -d
curl -fsS http://localhost:5004/health | jq .
curl -fsS http://localhost:5004/api/info | jq .
```

`/api/predict` accepts the same body shape as the rocks/house siblings.
