# maskrcnn-house

REST service that serves Zhiang Chen's tornado-damage Mask R-CNN detectors
out of the same image as [`../maskrcnn-rocks`](../maskrcnn-rocks). It is a
sibling deployment: identical code, identical Dockerfile, identical archive
mount; only the **default checkpoint** and the **class-label table** differ.

| Service | Port | Default checkpoint | Classes |
|---|---|---|---|
| `maskrcnn-rocks-api` | 5002 | `bishop_ntl_rgb_e0049` | 2: `[background, rock]` |
| `maskrcnn-house-api` | 5003 | `tornado_detector_eureka_aug_mult_e0039` | 6: `[background, house_undamaged, house_damage_0..3]` |

Both run on `tesseract` (jdas@192.168.0.232) alongside `groundingdino-api`
(:5000) and `groundedsam2-api` (:5001).

## Why is this a separate compose file instead of a multi-service one?

The two services share an image but have different lifecycles — we expect
to swap the rocks default among the bishop / gobabeb / hypolith family as
new datasets land, while the house service stays pinned to whichever
Eureka head we are currently calibrating. Keeping them in separate compose
files lets each restart without touching the other, and lets ops scale or
constrain GPU access per service.

## Default model

`tornado_detector_eureka_aug_mult_e0039.param` (Zhiang Chen, Dec 2022,
augmented multi-class head, 39 epochs, 176 MB).

* Architecture: torchvision Mask R-CNN, ResNet-50 FPN, 3-channel RGB input,
  44.0M params (sibling of the rocks model — same backbone family).
* Eureka taxonomy from `mask_rcnn_pytorch/eureka_train.py`:
  ```
  background, nd, d0, d1, d2, d3
  ```
  i.e. background + non-damaged + 4 ordinal damage levels (`d0` = lowest,
  `d3` = most severe), trained on Tipton KS 2018/2019 tornado orthomosaics
  (`Brummer_House`, `Melvin_House.files`, `TreeDamage`, …).
* Source: `/mnt/12tb-hdd-B/dreamslab-hdd-bkup/sarah/Zhiang_mask_rcnn/`
* Curated bundle: `/mnt/22tb-hdd/maskrcnn/deployable-self-contained/tornado_eureka_damage/`
* Companion GP classifier: `…/tornado_eureka_damage/gp_classifier/model_save.pth`

## Switching heads without rebuilding

The image's `_label_config()` resolves the per-family label table from env
vars (`MASKRCNN_LABELS_<FAMILY>`), and the registry already exposes all
four Eureka checkpoints. To swap to the binary head:

```yaml
environment:
  - DEFAULT_MODEL_ID=tornado_detector_eureka_aug_bin_e0031
  - MASKRCNN_LABELS_TORNADO=background,house_undamaged,house_damaged
  - DEFAULT_LABEL_NAME=house
```

then `docker compose up -d --force-recreate`. No rebuild required.

Available heads in the live registry:

| Registry id | num_classes | Notes |
|---|---|---|
| `tornado_detector_eureka_aug_mult_e0039` | 6 | augmented + multi-class, longest trained — **current default** |
| `tornado_detector_eureka_mult_e0031` | 6 | non-augmented + multi-class |
| `tornado_detector_eureka_aug_bin_e0031` | 3 | augmented + binary damage |
| `tornado_detector_eureka_bin_e0031` | 3 | non-augmented + binary damage |

## Running

From this directory on tesseract:

```bash
docker compose up -d
docker compose logs -f maskrcnn-house
curl -fsS http://localhost:5003/health | jq .
curl -fsS http://localhost:5003/api/info | jq .
```

`/api/predict` accepts the same body shape as `maskrcnn-rocks` — see
[`../maskrcnn-rocks/app.py`](../maskrcnn-rocks/app.py).

## Why the "house" name when the head outputs damage classes?

This is exactly the §3 / §0 caveat #7 setup from
`/home/jdas/kernelcal/docs/distinction-game-design.md`: the kernel
`k_MR_eureka` is a *distinction operator* that lights up on built
structures (and trees, in some imagery); the per-region label is fitted
through `Q_s` from the head's logits. We name the container after what
the kernel actually distinguishes (houses) rather than the head's
literal label slots, so we can re-fit `Q_s` later (R1 in §8.1 — relabel
only) without renaming the deployment.
