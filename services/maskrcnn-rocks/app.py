"""
app.py — Flask REST service for rock Mask R-CNN checkpoints.

REST contract (deliberately parallel to grounding-dino-api on port 5000):

    GET  /                      — minimal web demo page
    GET  /health                — {status, device, cuda_available, num_models}
    GET  /api/info              — model family + active default + runtime
    GET  /api/models            — full registry (id, variant, channels, path, ...)
    POST /api/predict           — run inference on a single image
    GET  /api/result/<file>     — fetch a saved annotated image

POST /api/predict accepts EITHER:
  * multipart/form-data with
        file            — image or .npy tensor
        model_id        — registry id (optional; defaults to DEFAULT_MODEL_ID)
        score_threshold, mask_threshold, max_detections, return_annotated
  * application/json with
        image           — base64-encoded bytes (same field grounding-dino uses)
        filename        — original filename (so we know if it's .npy)
        model_id, score_threshold, mask_threshold, max_detections,
        return_annotated
"""

from __future__ import annotations

import base64
import logging
import os
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import cv2
import torch
from flask import Flask, jsonify, render_template, request, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename

from inference import (
    annotate,
    encode_jpeg_b64,
    load_image_any,
    run_inference,
    to_tensor,
)
from model import load_from_checkpoint
from registry import ModelEntry, discover, pick_default, to_public_json

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("maskrcnn-rocks")

WEIGHTS_ROOT = os.environ.get("WEIGHTS_ROOT", "/opt/program/weights")
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "/tmp/uploads")
RESULTS_FOLDER = os.environ.get("RESULTS_FOLDER", "/tmp/results")
DEFAULT_MODEL_ID = os.environ.get("DEFAULT_MODEL_ID", "bishop_hero_e0004")
MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 32 * 1024 * 1024))

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

app = Flask(__name__)
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# -------------------------------------------------------------------------
# Registry + lazy model cache
# -------------------------------------------------------------------------

REGISTRY: Dict[str, ModelEntry] = discover(WEIGHTS_ROOT)
ACTIVE_DEFAULT: Optional[str] = pick_default(REGISTRY, DEFAULT_MODEL_ID)

log.info("device: %s", DEVICE)
log.info("registry size: %d", len(REGISTRY))
log.info("default model_id: %s", ACTIVE_DEFAULT)

_MODEL_CACHE: Dict[str, Tuple[torch.nn.Module, Dict[str, Any]]] = {}


def _get_model(model_id: str) -> Tuple[torch.nn.Module, Dict[str, Any], ModelEntry]:
    if model_id not in REGISTRY:
        raise KeyError(f"unknown model_id: {model_id!r}")
    entry = REGISTRY[model_id]
    if model_id in _MODEL_CACHE:
        model, meta = _MODEL_CACHE[model_id]
        return model, meta, entry
    log.info("loading %s from %s", model_id, entry.path)
    t0 = time.time()
    model, meta = load_from_checkpoint(entry.path, DEVICE)
    log.info("loaded %s in %.1fs (input_channel=%d, num_classes=%d, "
             "missing=%d unexpected=%d)",
             model_id, time.time() - t0,
             meta["input_channel"], meta["num_classes"],
             len(meta["missing_keys"]), len(meta["unexpected_keys"]))
    _MODEL_CACHE[model_id] = (model, meta)
    # Stamp the registry entry with ground-truth channel count now that
    # we've actually inspected the checkpoint.
    entry.declared_channels = meta["input_channel"]
    return model, meta, entry


# Eagerly warm the default so the first request isn't slow.
if ACTIVE_DEFAULT:
    try:
        _get_model(ACTIVE_DEFAULT)
    except Exception as exc:
        log.warning("failed to warm default model %s: %s", ACTIVE_DEFAULT, exc)


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def _extract_image_bytes() -> Tuple[bytes, str]:
    """Return (raw bytes, filename) from the request, JSON or multipart."""
    if "file" in request.files:
        f = request.files["file"]
        if not f.filename:
            raise ValueError("empty file field")
        return f.read(), secure_filename(f.filename)
    if request.is_json:
        data = request.get_json(silent=True) or {}
        if "image" not in data:
            raise ValueError("missing 'image' in JSON body")
        raw = base64.b64decode(data["image"])
        fn = secure_filename(data.get("filename") or "viewport.jpg")
        return raw, fn
    raise ValueError("expected multipart 'file' or JSON with 'image'")


def _param(name: str, default, caster):
    """Pull a param from form-data or JSON body."""
    if request.is_json:
        data = request.get_json(silent=True) or {}
        if name in data:
            return caster(data[name])
    if name in request.form:
        return caster(request.form[name])
    return default


def _class_names(default_label: str = "rock") -> Optional[list[str]]:
    raw = _param("class_names", os.environ.get("CLASS_NAMES", ""), str)
    if not raw:
        return None
    names = [n.strip() for n in raw.replace(";", ",").split(",") if n.strip()]
    if not names:
        return None
    if names[0].lower() not in {"background", "__background__", "bg"}:
        names = ["background", *names]
    return names or ["background", default_label]


# -------------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------------

@app.route("/")
def index():
    try:
        return render_template(
            "index.html",
            default_model=ACTIVE_DEFAULT,
            registry=to_public_json(REGISTRY),
        )
    except Exception:
        return jsonify({
            "service": "maskrcnn-rocks",
            "default_model": ACTIVE_DEFAULT,
            "num_models": len(REGISTRY),
        })


@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "device": str(DEVICE),
        "cuda_available": torch.cuda.is_available(),
        "gpu_name": (torch.cuda.get_device_name(0)
                     if torch.cuda.is_available() else None),
        "num_models": len(REGISTRY),
        "default_model_id": ACTIVE_DEFAULT,
    })


@app.route("/api/info")
def api_info():
    entry = REGISTRY.get(ACTIVE_DEFAULT) if ACTIVE_DEFAULT else None
    return jsonify({
        "service": "maskrcnn-rocks",
        "framework": "torchvision.maskrcnn_resnet50_fpn",
        "torch_version": torch.__version__,
        "device": str(DEVICE),
        "weights_root": WEIGHTS_ROOT,
        "default_model_id": ACTIVE_DEFAULT,
        "default_model": asdict(entry) if entry else None,
        "num_models": len(REGISTRY),
        "supported_formats": ["png", "jpg", "jpeg", "bmp", "webp", "npy"],
        "max_file_size_mb": MAX_CONTENT_LENGTH // (1024 * 1024),
    })


@app.route("/api/models")
def api_models():
    return jsonify({
        "count": len(REGISTRY),
        "default_model_id": ACTIVE_DEFAULT,
        "models": to_public_json(REGISTRY),
    })


@app.route("/api/predict", methods=["POST"])
def api_predict():
    try:
        raw, filename = _extract_image_bytes()
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    model_id = _param("model_id", ACTIVE_DEFAULT, str)
    if not model_id:
        return jsonify({"success": False,
                        "error": "no model_id given and no default available"}), 400

    try:
        model, meta, entry = _get_model(model_id)
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc),
                        "available": list(REGISTRY)[:20]}), 404
    except Exception as exc:
        log.exception("failed to load model %s", model_id)
        return jsonify({"success": False,
                        "error": f"failed to load model: {exc}"}), 500

    score_thr = _param("score_threshold", 0.5, float)
    mask_thr = _param("mask_threshold", 0.5, float)
    max_det = _param("max_detections", 200, int)
    class_names = _class_names()
    return_annotated = _param("return_annotated", True,
                              lambda v: str(v).lower() in {"1", "true", "yes"})

    try:
        image = load_image_any(raw, filename, meta["input_channel"])
        tensor = to_tensor(image, DEVICE)
        t0 = time.time()
        detections, (w, h) = run_inference(
            model, tensor,
            score_threshold=score_thr,
            mask_threshold=mask_thr,
            max_detections=max_det,
            label_name="rock",
            class_names=class_names,
        )
        elapsed_ms = int((time.time() - t0) * 1000)
    except Exception as exc:
        log.exception("inference failed")
        return jsonify({"success": False, "error": f"inference failed: {exc}"}), 500

    response: Dict[str, Any] = {
        "success": True,
        "model_id": model_id,
        "model": asdict(entry),
        "inference_ms": elapsed_ms,
        "image_size": {"width": w, "height": h},
        "class_names": class_names,
        "predictions": {
            "count": len(detections),
            "boxes":     [d.box       for d in detections],
            "boxes_norm":[d.box_norm  for d in detections],
            "scores":    [d.score     for d in detections],
            "labels":    [d.label     for d in detections],
            "masks_rle": [d.mask_rle  for d in detections],
            "areas":     [d.area      for d in detections],
        },
    }

    if return_annotated and detections:
        try:
            vis = annotate(image, detections)
            response["annotated_image"] = "data:image/jpeg;base64," + encode_jpeg_b64(vis)
            result_name = f"result_{uuid.uuid4().hex[:12]}.jpg"
            result_path = Path(RESULTS_FOLDER) / result_name
            cv2.imwrite(str(result_path), vis)
            response["result_url"] = f"/api/result/{result_name}"
        except Exception as exc:
            log.exception("annotation failed")
            response["annotated_image_error"] = str(exc)

    return jsonify(response)


@app.route("/api/result/<path:filename>")
def api_result(filename: str):
    safe = secure_filename(filename)
    path = Path(RESULTS_FOLDER) / safe
    if not path.exists():
        return jsonify({"error": "not found"}), 404
    return send_file(str(path), mimetype="image/jpeg")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
