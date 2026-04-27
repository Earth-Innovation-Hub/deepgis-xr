# maskrcnn-newlife

Sibling of [`../maskrcnn-rocks`](../maskrcnn-rocks).

| Service | Port | Default checkpoint | Classes |
|---|---|---|---|
| `maskrcnn-newlife-api` | 5007 | `new_life_hero_e0008` | 2: `[background, organism]` |

## Default model

`new_life_hero_e0008` — `/mnt/22tb-hdd/maskrcnn/terrestrial/deepgis_new_life/epoch_0008.param`. DeepGIS biology / "new life" ground-imagery run. The original taxonomy isn't carried in the state-dict, so we expose a coarse `organism` class. Override via:

```yaml
environment:
  - MASKRCNN_LABELS_NEW_LIFE=background,plant,microbe,...
```

once the source labels are recovered.

## Running on tesseract

```bash
cd /home/jdas/deepgis-xr/services/maskrcnn-newlife
docker compose up -d
curl -fsS http://localhost:5007/health | jq .
```
