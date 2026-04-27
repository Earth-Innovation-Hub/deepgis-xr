# maskrcnn-brent-moon-craters

Sibling of [`../maskrcnn-rocks`](../maskrcnn-rocks). Lunar LROC-NAC crater detector trained against Brent's labels.

| Service | Port | Default checkpoint | Body | Author | Classes |
|---|---|---|---|---|---|
| `maskrcnn-brent-moon-craters-api` | 5008 | `moon_craters_brent_brent_e0009` | Moon | Brent | 2: `[background, crater]` |

## Default model

`moon_craters_brent_brent_e0009` — `/mnt/22tb-hdd/maskrcnn/deployable-self-contained/moon_craters_brent/weights/brent_epoch_0009.param` (2021-03). Trained against the same LROC-NAC tile catalog as the longer `lroc_nacr_hero_e0551` run (served by the future `maskrcnn-craters-moon` service); kept as its own kernel so distinction-game-fit can compare the two on the same input.

## Running on tesseract

```bash
cd /home/jdas/deepgis-xr/services/maskrcnn-brent-moon-craters
docker compose up -d
curl -fsS http://localhost:5008/health | jq .
```
