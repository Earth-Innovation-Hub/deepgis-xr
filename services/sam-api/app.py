from __future__ import annotations

import base64
import gc
import io
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
import torch
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from PIL import Image
from segment_anything import SamAutomaticMaskGenerator, sam_model_registry
from werkzeug.utils import secure_filename


UPLOAD_FOLDER = Path(os.environ.get("UPLOAD_FOLDER", "/tmp/uploads"))
RESULTS_FOLDER = Path(os.environ.get("RESULTS_FOLDER", "/tmp/results"))
CHECKPOINT_DIR = Path(os.environ.get("SAM_CHECKPOINT_DIR", "/opt/program/checkpoints"))
MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 32 * 1024 * 1024))
DEFAULT_MODEL_TYPE = os.environ.get("DEFAULT_MODEL_TYPE", "vit_b")
MAX_SEGMENTS = int(os.environ.get("SAM_MAX_SEGMENTS", 200))
POINTS_PER_SIDE = int(os.environ.get("SAM_POINTS_PER_SIDE", 32))
PRED_IOU_THRESH = float(os.environ.get("SAM_PRED_IOU_THRESH", 0.86))
STABILITY_SCORE_THRESH = float(os.environ.get("SAM_STABILITY_SCORE_THRESH", 0.92))
MIN_MASK_REGION_AREA = int(os.environ.get("SAM_MIN_MASK_REGION_AREA", 100))


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


EAGER_WARMUP = _env_bool("SAM_EAGER_WARMUP", False)
UNLOAD_AFTER_PREDICT = _env_bool("SAM_UNLOAD_AFTER_PREDICT", True)
EMPTY_CACHE_AFTER_PREDICT = _env_bool("SAM_EMPTY_CACHE_AFTER_PREDICT", True)
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

MODELS = {
    "vit_h": {
        "checkpoint": "sam_vit_h_4b8939.pth",
        "description": "Huge - best quality, slowest",
    },
    "vit_l": {
        "checkpoint": "sam_vit_l_0b3195.pth",
        "description": "Large - balanced quality/speed",
    },
    "vit_b": {
        "checkpoint": "sam_vit_b_01ec64.pth",
        "description": "Base - fastest",
    },
}

UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
RESULTS_FOLDER.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

_MODEL_CACHE: Dict[str, Tuple[torch.nn.Module, SamAutomaticMaskGenerator]] = {}
_MODEL_LOCK = threading.Lock()


def _cuda_memory() -> Dict[str, int | None]:
    if not torch.cuda.is_available():
        return {"allocated_bytes": None, "reserved_bytes": None}
    return {
        "allocated_bytes": int(torch.cuda.memory_allocated()),
        "reserved_bytes": int(torch.cuda.memory_reserved()),
    }


def _clear_cuda_cache() -> None:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        try:
            torch.cuda.ipc_collect()
        except Exception:
            pass


def _checkpoint_path(model_type: str) -> Path:
    if model_type not in MODELS:
        raise KeyError(f"unknown SAM model_type: {model_type!r}")
    path = CHECKPOINT_DIR / MODELS[model_type]["checkpoint"]
    if not path.exists():
        raise FileNotFoundError(f"missing checkpoint for {model_type}: {path}")
    return path


def _get_generator(model_type: str) -> Tuple[torch.nn.Module, SamAutomaticMaskGenerator]:
    if model_type in _MODEL_CACHE:
        return _MODEL_CACHE[model_type]

    t0 = time.time()
    checkpoint = _checkpoint_path(model_type)
    print(f"Loading SAM {model_type} from {checkpoint} on {DEVICE}", flush=True)
    model = sam_model_registry[model_type](checkpoint=str(checkpoint))
    model.to(DEVICE)
    model.eval()
    generator = SamAutomaticMaskGenerator(
        model=model,
        points_per_side=POINTS_PER_SIDE,
        pred_iou_thresh=PRED_IOU_THRESH,
        stability_score_thresh=STABILITY_SCORE_THRESH,
        crop_n_layers=1,
        crop_n_points_downscale_factor=2,
        min_mask_region_area=MIN_MASK_REGION_AREA,
    )
    _MODEL_CACHE[model_type] = (model, generator)
    print(f"Loaded SAM {model_type} in {time.time() - t0:.1f}s", flush=True)
    return model, generator


def _unload_model(model_type: str) -> bool:
    cached = _MODEL_CACHE.pop(model_type, None)
    if not cached:
        if EMPTY_CACHE_AFTER_PREDICT:
            _clear_cuda_cache()
        return False
    model, _generator = cached
    try:
        model.to("cpu")
    except Exception:
        pass
    del model
    _clear_cuda_cache()
    return True


def _unload_all() -> int:
    count = 0
    for model_type in list(_MODEL_CACHE):
        count += int(_unload_model(model_type))
    _clear_cuda_cache()
    return count


def _extract_image() -> Tuple[Image.Image, str]:
    if "file" in request.files:
        f = request.files["file"]
        if not f.filename:
            raise ValueError("empty file field")
        filename = secure_filename(f.filename)
        return Image.open(f.stream).convert("RGB"), filename

    if request.is_json:
        data = request.get_json(silent=True) or {}
        raw = data.get("image")
        if not raw:
            raise ValueError("missing 'image' in JSON body")
        filename = secure_filename(data.get("filename") or "viewport.jpg")
        return Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB"), filename

    raise ValueError("expected multipart 'file' or JSON with 'image'")


def _param(name: str, default, caster):
    if request.is_json:
        data = request.get_json(silent=True) or {}
        if name in data:
            return caster(data[name])
    if name in request.form:
        return caster(request.form[name])
    return default


def _mask_to_polygons_norm(mask: np.ndarray) -> List[List[List[float]]]:
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = mask.shape[:2]
    polygons: List[List[List[float]]] = []
    for contour in contours:
        if len(contour) < 3:
            continue
        epsilon = 0.0025 * cv2.arcLength(contour, True)
        simplified = cv2.approxPolyDP(contour, epsilon, True)
        if len(simplified) < 3:
            continue
        coords = []
        for x, y in simplified.reshape(-1, 2):
            coords.append([float(x) / w, float(y) / h])
        if coords and coords[0] != coords[-1]:
            coords.append(coords[0])
        polygons.append(coords)
    return polygons


def _to_geojson(masks: List[Dict[str, Any]], image_size: Tuple[int, int]) -> Dict[str, Any]:
    features = []
    for i, mask_data in enumerate(masks):
        polygons = _mask_to_polygons_norm(mask_data["segmentation"])
        for polygon in polygons:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [polygon],
                },
                "properties": {
                    "segment_id": i,
                    "area": int(mask_data["area"]),
                    "bbox": [float(x) for x in mask_data["bbox"]],
                    "iou": float(mask_data.get("predicted_iou", 0.0)),
                    "stability": float(mask_data.get("stability_score", 0.0)),
                    "auto_generated": True,
                    "model": "segment_anything",
                },
            })
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "model": "segment_anything",
            "num_segments": len(masks),
            "image_size": list(image_size),
        },
    }


def _visualize(image: Image.Image, masks: List[Dict[str, Any]]) -> Image.Image:
    base = image.convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    masks_sorted = sorted(masks, key=lambda m: m["area"], reverse=True)
    rng = np.random.default_rng(42)
    for mask_data in masks_sorted:
        mask = mask_data["segmentation"].astype(bool)
        color = rng.integers(50, 256, size=3, dtype=np.uint8).tolist() + [90]
        arr = np.zeros((image.height, image.width, 4), dtype=np.uint8)
        arr[mask] = color
        overlay = Image.alpha_composite(overlay, Image.fromarray(arr, "RGBA"))
    return Image.alpha_composite(base, overlay).convert("RGB")


@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "device": str(DEVICE),
        "cuda_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "cached_models": sorted(_MODEL_CACHE.keys()),
        "cache_policy": {
            "eager_warmup": EAGER_WARMUP,
            "unload_after_predict": UNLOAD_AFTER_PREDICT,
            "empty_cache_after_predict": EMPTY_CACHE_AFTER_PREDICT,
        },
        "cuda_memory": _cuda_memory(),
    })


@app.route("/api/models")
def api_models():
    return jsonify({
        "default_model_type": DEFAULT_MODEL_TYPE,
        "models": [
            {
                "model_type": model_type,
                "checkpoint": str(CHECKPOINT_DIR / info["checkpoint"]),
                "available": (CHECKPOINT_DIR / info["checkpoint"]).exists(),
                "description": info["description"],
            }
            for model_type, info in MODELS.items()
        ],
    })


@app.route("/api/cache")
def api_cache():
    return jsonify({
        "cached_models": sorted(_MODEL_CACHE.keys()),
        "cuda_memory": _cuda_memory(),
    })


@app.route("/api/unload", methods=["POST"])
def api_unload():
    model_type = _param("model_type", "", str)
    with _MODEL_LOCK:
        if model_type:
            unloaded = _unload_model(model_type)
            return jsonify({
                "success": True,
                "model_type": model_type,
                "unloaded": unloaded,
                "cached_models": sorted(_MODEL_CACHE.keys()),
                "cuda_memory": _cuda_memory(),
            })
        unloaded_count = _unload_all()
        return jsonify({
            "success": True,
            "unloaded_count": unloaded_count,
            "cached_models": sorted(_MODEL_CACHE.keys()),
            "cuda_memory": _cuda_memory(),
        })


@app.route("/api/predict", methods=["POST"])
def api_predict():
    try:
        image, filename = _extract_image()
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    model_type = _param("model_type", DEFAULT_MODEL_TYPE, str)
    min_area = _param("min_area", 100, int)
    max_segments = _param("max_segments", MAX_SEGMENTS, int)
    return_visualization = _param("return_visualization", True, lambda v: str(v).lower() in {"1", "true", "yes"})

    with _MODEL_LOCK:
        try:
            _model, generator = _get_generator(model_type)
            t0 = time.time()
            try:
                masks = generator.generate(np.array(image))
            except IndexError as exc:
                # SAM's AutomaticMaskGenerator can raise inside torchvision's
                # box_area() when a crop produces no candidate boxes (common
                # for blank or very low-texture smoke-test images). Treat that
                # as a valid empty segmentation rather than a service failure.
                if "too many indices" not in str(exc):
                    raise
                masks = []
            inference_ms = int((time.time() - t0) * 1000)
            filtered = [m for m in masks if int(m.get("area", 0)) >= min_area]
            filtered.sort(
                key=lambda m: float(m.get("predicted_iou", 0.0)) * float(m.get("stability_score", 0.0)),
                reverse=True,
            )
            filtered = filtered[:max_segments]
            geojson = _to_geojson(filtered, image.size)
            result_name = None
            result_url = None
            visualization_b64 = None
            if return_visualization:
                visualization = _visualize(image, filtered)
                result_name = f"sam_{uuid.uuid4().hex[:12]}.jpg"
                result_path = RESULTS_FOLDER / result_name
                visualization.save(result_path, quality=92)
                result_url = f"/api/result/{result_name}"
                buf = io.BytesIO()
                visualization.save(buf, format="JPEG", quality=88)
                visualization_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

            segments = [
                {
                    "segment_id": i + 1,
                    "area": int(m["area"]),
                    "bbox": [int(x) for x in m["bbox"]],
                    "predicted_iou": float(m.get("predicted_iou", 0.0)),
                    "stability_score": float(m.get("stability_score", 0.0)),
                }
                for i, m in enumerate(filtered)
            ]

            if UNLOAD_AFTER_PREDICT:
                cache_policy_applied = "unloaded_model_after_predict"
                _unload_model(model_type)
            elif EMPTY_CACHE_AFTER_PREDICT:
                cache_policy_applied = "emptied_cuda_cache_after_predict"
                _clear_cuda_cache()
            else:
                cache_policy_applied = "none"

            return jsonify({
                "success": True,
                "model_type": model_type,
                "filename": filename,
                "num_segments": len(filtered),
                "segments": segments,
                "geojson": geojson,
                "image_size": [image.width, image.height],
                "inference_ms": inference_ms,
                "result_url": result_url,
                "visualization_image": visualization_b64,
                "cache_policy_applied": cache_policy_applied,
            })
        except Exception as exc:
            if UNLOAD_AFTER_PREDICT:
                _unload_model(model_type)
            elif EMPTY_CACHE_AFTER_PREDICT:
                _clear_cuda_cache()
            import traceback
            return jsonify({
                "success": False,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }), 500


@app.route("/api/result/<path:filename>")
def api_result(filename: str):
    safe = secure_filename(filename)
    path = RESULTS_FOLDER / safe
    if not path.exists():
        return jsonify({"error": "not found"}), 404
    return send_file(str(path), mimetype="image/jpeg")


if EAGER_WARMUP:
    with _MODEL_LOCK:
        _get_generator(DEFAULT_MODEL_TYPE)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
