# maskrcnn-harish-moon-craters

Sibling of [`../maskrcnn-rocks`](../maskrcnn-rocks). Lunar LROC-NAC crater detector — Harish Anand's `hanand_stragglers` recovery run, promoted "best" from the 100-epoch crater sweep (Sep–Nov 2020).

| Service | Port | Default checkpoint | Body | Author | Classes |
|---|---|---|---|---|---|
| `maskrcnn-harish-moon-craters-api` | 5009 | `hanand_stragglers_download.openuas.us_e0099` | Moon | Harish Anand | 2: `[background, crater]` |

## Default model

`hanand_stragglers_download.openuas.us_e0099` — `/mnt/22tb-hdd/maskrcnn/space/hanand_stragglers/download.openuas.us__epoch_0099.param`. Recovered from openuas.us alongside Harish's DeepGIS LROC-NAC notebook work; epoch 99 is the promoted "best" from the 100-epoch crater training sweep.

Also reachable on this container by `model_id` without rebuild:

- `hanand_stragglers_download.openuas.us_e0011` — early sweep sibling
- `hanand_stragglers_hanand_home___r18fpn_e0008` — **lighter ResNet-18-FPN backbone** (78 MB vs 168 MB), useful for edge / low-VRAM eval. The image's loader auto-detects backbone from `conv1` shape.

## Running on tesseract

```bash
cd /home/jdas/deepgis-xr/services/maskrcnn-harish-moon-craters
docker compose up -d
curl -fsS http://localhost:5009/health | jq .
```
