"""
Ultralytics vision service for DeepGIS: YOLO26, YOLOE-26 and SAM 3.

    POST /api/predict   multipart: file, model?, classes?, confidence?,
                        imgsz?, max_detections?
    GET  /api/models    model ids, family, and whether the weights are here
    GET  /health

Families:

* ``yolo``  - YOLO26 on the 80 COCO classes. ``classes`` filters by name.
* ``yoloe`` - YOLOE-26, open vocabulary. ``classes`` is the list to find.
* ``sam3``  - SAM 3 concept segmentation. ``classes`` are noun phrases.
              Its weights are gated on Hugging Face and are never
              downloaded here; drop ``sam3.pt`` into the weights dir.

Each detection carries a pixel box and ``mask_polygons_norm``: the outer
contours of its mask in [0, 1] image space, largest first. That is the
shape the maskrcnn-rocks service returns, so the web app draws both the
same way.
"""

from __future__ import annotations

import ctypes
import gc
import logging
import os
import re
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from flask import Flask, jsonify, request

log = logging.getLogger("ultralytics-api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


WEIGHTS_DIR = Path(os.environ.get("WEIGHTS_DIR", "/weights"))
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "yolo26x-seg")
UNLOAD_AFTER_PREDICT = _env_bool("UNLOAD_AFTER_PREDICT", True)
DEFAULT_IMGSZ = int(os.environ.get("DEFAULT_IMGSZ", "1024"))
MAX_IMGSZ = int(os.environ.get("MAX_IMGSZ", "1280"))
MAX_DETECTIONS = int(os.environ.get("MAX_DETECTIONS", "300"))
MAX_RING_POINTS = 200
DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"

WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
# Ultralytics downloads a bare weight name into the working directory.
os.chdir(WEIGHTS_DIR)

# id -> (family, weight file, returns masks)
MODELS: dict[str, tuple[str, str, bool]] = {}
for _size in "nslmx":
    MODELS[f"yolo26{_size}"] = ("yolo", f"yolo26{_size}.pt", False)
    MODELS[f"yolo26{_size}-seg"] = ("yolo", f"yolo26{_size}-seg.pt", True)
    MODELS[f"yoloe-26{_size}-seg"] = ("yoloe", f"yoloe-26{_size}-seg.pt", True)
MODELS["sam3"] = ("sam3", "sam3.pt", True)
LEGACY_IDS = {f"yolov8{_size}": f"yolo26{_size}-seg" for _size in "nslmx"}
NEEDS_CLASSES = ("yoloe", "sam3")

app = Flask(__name__)
_lock = threading.Lock()
_loaded: dict = {"id": None, "model": None, "classes": None}


class WeightsMissing(Exception):
    pass


try:
    _libc = ctypes.CDLL("libc.so.6")
except OSError:
    _libc = None


def _resident_mb() -> int | None:
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") // (1 << 20)
    except (OSError, ValueError, IndexError):
        return None


def _unload() -> None:
    _loaded.update(id=None, model=None, classes=None)
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    # A model's weights pass through host memory on their way to the GPU, and the allocator
    # keeps what Python frees. Without this (and MALLOC_ARENA_MAX=1, so request threads share
    # one arena) the process held several GB more after each load.
    if _libc is not None:
        _libc.malloc_trim(0)


def _load(model_id: str):
    if _loaded["id"] == model_id:
        return _loaded["model"]
    _unload()
    family, filename, _ = MODELS[model_id]
    if family == "sam3":
        path = WEIGHTS_DIR / filename
        if not path.exists():
            raise WeightsMissing(f"{filename} is not in the weights directory")
        from ultralytics.models.sam import SAM3SemanticPredictor
        model = SAM3SemanticPredictor(overrides=dict(
            conf=0.25, task="segment", mode="predict", model=str(path),
            half=DEVICE != "cpu", device=DEVICE, save=False, verbose=False,
        ))
    elif family == "yoloe":
        from ultralytics import YOLOE
        model = YOLOE(filename)
    else:
        from ultralytics import YOLO
        model = YOLO(filename)
    log.info("loaded %s on %s", model_id, DEVICE)
    _loaded.update(id=model_id, model=model, classes=None)
    return model


def _set_yoloe_classes(model, classes: list[str]) -> None:
    try:
        model.set_classes(classes)
    except TypeError:
        # Older YOLOE builds want the text embeddings passed in.
        model.set_classes(classes, model.get_text_pe(classes))


def _parse_classes(text: str) -> list[str]:
    parts = re.split(r"\s*(?:,|;|\s\.\s)\s*", text or "")
    seen, out = set(), []
    for part in parts:
        name = part.strip().strip(".").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


def _mask_rings(mask: np.ndarray, width: int, height: int) -> list:
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rings = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(contour) < 4:
            continue
        if len(contour) > MAX_RING_POINTS:
            contour = cv2.approxPolyDP(contour, 0.002 * cv2.arcLength(contour, True), True)
        points = contour.reshape(-1, 2)
        if len(points) < 3:
            continue
        ring = [[round(float(x) / width, 5), round(float(y) / height, 5)] for x, y in points]
        ring.append(ring[0])
        rings.append(ring)
    return rings


def _detections(result, names: dict, width: int, height: int) -> list[dict]:
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return []
    xyxy = boxes.xyxy.cpu().numpy()
    confs = boxes.conf.cpu().numpy()
    cls = boxes.cls.cpu().numpy().astype(int)
    masks = result.masks.data.cpu().numpy() if result.masks is not None else None
    out = []
    for i in range(len(xyxy)):
        x1, y1, x2, y2 = (float(v) for v in xyxy[i])
        rings, area = [], int(max(0.0, x2 - x1) * max(0.0, y2 - y1))
        if masks is not None and i < len(masks):
            mask = masks[i] > 0.5
            if mask.shape != (height, width):
                mask = cv2.resize(mask.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST) > 0
            area = int(mask.sum())
            rings = _mask_rings(mask, width, height)
        out.append({
            "detection_id": i + 1,
            "class_id": int(cls[i]),
            "class_name": str(names.get(int(cls[i]), cls[i])),
            "confidence": round(float(confs[i]), 4),
            "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
            "area": area,
            "mask_polygons_norm": rings,
        })
    return out


def _run(model_id: str, image: np.ndarray, classes: list[str], conf: float, imgsz: int, max_det: int):
    family = MODELS[model_id][0]
    model = _load(model_id)
    unknown: list[str] = []
    common = dict(conf=conf, imgsz=imgsz, max_det=max_det, device=DEVICE, retina_masks=True, verbose=False)
    if family == "sam3":
        model.args.conf = conf
        model.set_image(image)
        result = model(text=classes)[0]
        names = getattr(result, "names", None) or classes
        if not isinstance(names, dict):
            names = dict(enumerate(names))
        return result, names, unknown
    if family == "yoloe":
        if _loaded["classes"] != classes:
            _set_yoloe_classes(model, classes)
            _loaded["classes"] = list(classes)
        result = model.predict(image, **common)[0]
        return result, dict(result.names), unknown
    ids = None
    if classes:
        lookup = {str(name).lower(): idx for idx, name in model.names.items()}
        ids = [lookup[c.lower()] for c in classes if c.lower() in lookup]
        unknown = [c for c in classes if c.lower() not in lookup]
        if not ids:
            return None, dict(model.names), unknown
    result = model.predict(image, classes=ids, **common)[0]
    return result, dict(result.names), unknown


def _gpu_name():
    return torch.cuda.get_device_name(0) if torch.cuda.is_available() else None


@app.route("/health")
def health():
    import ultralytics
    return jsonify(
        status="ok",
        device=DEVICE,
        cuda_available=torch.cuda.is_available(),
        gpu_name=_gpu_name(),
        ultralytics=ultralytics.__version__,
        loaded=_loaded["id"],
        default_model=DEFAULT_MODEL,
        sam3_weights=(WEIGHTS_DIR / MODELS["sam3"][1]).exists(),
        resident_mb=_resident_mb(),
    )


@app.route("/api/models")
def api_models():
    return jsonify(models=[
        {
            "id": model_id,
            "family": family,
            "masks": masks,
            "needs_classes": family in NEEDS_CLASSES,
            "weights_present": (WEIGHTS_DIR / filename).exists(),
            "auto_download": family != "sam3",
        }
        for model_id, (family, filename, masks) in MODELS.items()
    ], default=DEFAULT_MODEL)


def _number(name: str, default, caster, low, high):
    raw = request.form.get(name)
    try:
        value = caster(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        value = default
    return min(max(value, low), high)


@app.route("/api/predict", methods=["POST"])
def api_predict():
    upload = request.files.get("file")
    if upload is None:
        return jsonify(success=False, error="file is required"), 400
    model_id = (request.form.get("model") or DEFAULT_MODEL).strip()
    model_id = LEGACY_IDS.get(model_id, model_id)
    if model_id not in MODELS:
        return jsonify(success=False, error=f"unknown model {model_id!r}", models=sorted(MODELS)), 400
    family = MODELS[model_id][0]
    classes = _parse_classes(request.form.get("classes", ""))
    if family in NEEDS_CLASSES and not classes:
        return jsonify(success=False, error=f"{model_id} needs a list of things to find"), 400

    conf = _number("confidence", 0.25, float, 0.01, 0.99)
    imgsz = int(_number("imgsz", DEFAULT_IMGSZ, int, 320, MAX_IMGSZ)) // 32 * 32
    max_det = int(_number("max_detections", MAX_DETECTIONS, int, 1, MAX_DETECTIONS))

    image = cv2.imdecode(np.frombuffer(upload.read(), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return jsonify(success=False, error="could not decode the image"), 400
    height, width = image.shape[:2]

    with _lock:
        t0 = time.time()
        try:
            result, names, unknown = _run(model_id, image, classes, conf, imgsz, max_det)
            detections = _detections(result, names, width, height) if result is not None else []
        except WeightsMissing as err:
            return jsonify(success=False, reason="weights_missing", error=str(err)), 503
        except torch.cuda.OutOfMemoryError:
            _unload()
            log.exception("out of GPU memory running %s", model_id)
            return jsonify(success=False, reason="out_of_memory", error="the GPU ran out of memory"), 503
        except Exception as err:
            log.exception("prediction failed for %s", model_id)
            return jsonify(success=False, error=f"{type(err).__name__}: {err}"), 500
        finally:
            if UNLOAD_AFTER_PREDICT:
                _unload()
        elapsed_ms = int((time.time() - t0) * 1000)

    log.info("%s %dx%d classes=%s -> %d in %d ms", model_id, width, height, classes or "all", len(detections), elapsed_ms)
    return jsonify(
        success=True,
        model=model_id,
        family=family,
        classes=classes,
        unknown_classes=unknown,
        num_detections=len(detections),
        detections=detections,
        image_size=[width, height],
        imgsz=imgsz,
        inference_ms=elapsed_ms,
        device=DEVICE,
        cuda_available=torch.cuda.is_available(),
        gpu_name=_gpu_name(),
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), threaded=True)
