# maskrcnn-litter

Sibling of [`../maskrcnn-rocks`](../maskrcnn-rocks).

| Service | Port | Default checkpoint | Classes |
|---|---|---|---|
| `maskrcnn-litter-api` | 5005 | `litter_dynamics_hero_e0008` | 2: `[background, litter]` |

## Default model

`litter_dynamics_hero_e0008` — `/mnt/22tb-hdd/maskrcnn/terrestrial/deepgis_litter_dynamics/epoch_0008.param`. Temporal-litter detection run.

Sibling families also reachable as `model_id`s without rebuild:

- `agu_litter_hero_e0008` — AGU demo litter run
- `agu_litter_raw_hero_e0008` — AGU demo litter, raw imagery

All three are pre-labeled with `[background, litter]` via the `MASKRCNN_LABELS_*` env block.

## Running on tesseract

```bash
cd /home/jdas/deepgis-xr/services/maskrcnn-litter
docker compose up -d
curl -fsS http://localhost:5005/health | jq .
```
