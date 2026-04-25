"""
inference.py — image → tensor → Mask R-CNN → (boxes, scores, labels, masks).

Mirrors the output contract of the grounding-dino-api container so that
deepgis-xr can consume both services with minimal glue code.

Multi-channel inputs:
  * RGB (3ch):           plain JPG/PNG on the wire.
  * RGB+DEM / multispec: the caller POSTs a .npy file whose last axis has the
    correct number of channels.  We pick channels 0..input_channel.
  * ``bishop_tl_rgb_*`` + a plain RGB image:  the common case, everything
    stays 3-channel and no special data path is required.
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import torch
from PIL import Image
from pycocotools import mask as mask_utils

log = logging.getLogger(__name__)


@dataclass
class Detection:
    box: List[float]          # [x1, y1, x2, y2] in pixel coords
    box_norm: List[float]     # [x1, y1, x2, y2] in 0..1
    score: float
    label: str
    mask_rle: Optional[Dict[str, Any]]
    # Vector contours of the binary mask, normalized to [0, 1] image coords.
    # Shape: list of rings; each ring is [[x_norm, y_norm], ...] with the
    # largest ring conventionally listed first. Empty when the mask has
    # no contour above the simplification threshold.
    mask_polygons_norm: List[List[List[float]]]
    area: float


def _mask_to_polygons_norm(
    bmask: np.ndarray,
    epsilon_px: float = 1.0,
    min_points: int = 3,
) -> List[List[List[float]]]:
    """Vectorize a binary mask into normalized polygon rings.

    Uses `cv2.findContours(RETR_EXTERNAL)` to get outer rings only, then
    `approxPolyDP` to drop colinear vertices. Coordinates are normalized
    to [0, 1] using the mask's own (H, W), which equals the model input
    size — i.e. the same frame the boxes are in. Rings are sorted by
    descending pixel area so consumers can take rings[0] as the
    "primary" polygon when they only render one.
    """
    if bmask.ndim != 2:
        raise ValueError(f"expected 2D mask, got shape {bmask.shape}")
    h, w = bmask.shape
    if h == 0 or w == 0:
        return []
    contours, _ = cv2.findContours(
        bmask.astype(np.uint8),
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_TC89_L1,
    )
    rings: List[Tuple[float, List[List[float]]]] = []
    for c in contours:
        if c is None or len(c) < min_points:
            continue
        approx = cv2.approxPolyDP(c, epsilon_px, closed=True)
        if approx is None or len(approx) < min_points:
            continue
        pts = approx.reshape(-1, 2).astype(np.float64)
        ring = [[float(x) / w, float(y) / h] for x, y in pts]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        if len(ring) < min_points + 1:
            continue
        # Use abs() so a CW vs CCW orientation doesn't flip the sort.
        area = float(abs(cv2.contourArea(approx)))
        rings.append((area, ring))
    rings.sort(key=lambda kv: kv[0], reverse=True)
    return [ring for _, ring in rings]


def load_image_any(raw_bytes: bytes, filename: str,
                   want_channels: int) -> np.ndarray:
    """Decode request bytes into an HxWxC uint8/float32 array."""
    name = (filename or "").lower()
    if name.endswith(".npy"):
        arr = np.load(io.BytesIO(raw_bytes), allow_pickle=False)
        if arr.ndim == 2:
            arr = arr[:, :, None]
        if arr.shape[2] < want_channels:
            raise ValueError(
                f".npy has {arr.shape[2]} channels but model wants {want_channels}"
            )
        arr = arr[:, :, :want_channels].astype(np.float32)
        return arr
    # Everything else we treat as a standard image.
    pil = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    arr = np.asarray(pil, dtype=np.uint8)  # HxWx3
    if want_channels == 1:
        arr = np.mean(arr, axis=2, keepdims=True).astype(np.uint8)
    elif want_channels > 3:
        pad = np.zeros((arr.shape[0], arr.shape[1], want_channels - 3),
                       dtype=arr.dtype)
        arr = np.concatenate([arr, pad], axis=2)
    return arr


def to_tensor(image: np.ndarray, device: torch.device) -> torch.Tensor:
    """HxWxC [0..255] or float → 1xCxHxW float tensor on device."""
    if image.dtype == np.uint8:
        t = torch.from_numpy(image).float() / 255.0
    else:
        t = torch.from_numpy(image.astype(np.float32))
    t = t.permute(2, 0, 1).unsqueeze(0).to(device)
    return t


@torch.inference_mode()
def run_inference(
    model: torch.nn.Module,
    image_tensor: torch.Tensor,
    score_threshold: float = 0.5,
    mask_threshold: float = 0.5,
    max_detections: int = 200,
    label_name: str = "rock",
    label_names: Optional[List[str]] = None,
) -> Tuple[List[Detection], Tuple[int, int]]:
    """Run the model and post-process outputs into Detection records.

    ``label_names`` is a class-index-keyed table (index 0 is background).
    When the model emits a class index that isn't covered by the table,
    we fall back to ``f"{label_name}_{class_idx}"`` so the caller can
    still tell predictions apart on a multi-class head whose taxonomy
    isn't fully known yet.
    """
    _, _, h, w = image_tensor.shape
    out = model(image_tensor)[0]

    boxes = out["boxes"].cpu().numpy()
    scores = out["scores"].cpu().numpy()
    labels = out.get("labels")
    labels = labels.cpu().numpy() if labels is not None else None
    masks = out["masks"].cpu().numpy()  # N,1,H,W float in [0,1]

    keep = scores >= score_threshold
    boxes = boxes[keep][:max_detections]
    scores = scores[keep][:max_detections]
    labels = labels[keep][:max_detections] if labels is not None else None
    masks = masks[keep][:max_detections]

    detections: List[Detection] = []
    for idx, (box, score, mask) in enumerate(zip(boxes, scores, masks)):
        x1, y1, x2, y2 = box.tolist()
        bmask = (mask[0] >= mask_threshold).astype(np.uint8)
        rle = mask_utils.encode(np.asfortranarray(bmask))
        rle["counts"] = rle["counts"].decode("ascii")
        polygons_norm = _mask_to_polygons_norm(bmask)
        class_idx = int(labels[idx]) if labels is not None else None
        if label_names and class_idx is not None and 0 <= class_idx < len(label_names):
            resolved_label = label_names[class_idx]
        elif class_idx is not None:
            resolved_label = f"{label_name}_{class_idx}"
        else:
            resolved_label = label_name
        detections.append(
            Detection(
                box=[float(x1), float(y1), float(x2), float(y2)],
                box_norm=[
                    float(x1) / w, float(y1) / h,
                    float(x2) / w, float(y2) / h,
                ],
                score=float(score),
                label=resolved_label,
                mask_rle=rle,
                mask_polygons_norm=polygons_norm,
                area=float(bmask.sum()),
            )
        )
    return detections, (w, h)


def annotate(image: np.ndarray, detections: List[Detection]) -> np.ndarray:
    """Draw boxes + mask overlays onto an RGB/BGR image for preview."""
    if image.ndim == 2:
        vis = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.shape[2] >= 3:
        vis = cv2.cvtColor(image[:, :, :3].astype(np.uint8), cv2.COLOR_RGB2BGR)
    else:
        vis = cv2.cvtColor(image.astype(np.uint8), cv2.COLOR_GRAY2BGR)

    overlay = vis.copy()
    for d in detections:
        if d.mask_rle:
            m = mask_utils.decode(d.mask_rle).astype(bool)
            overlay[m] = (0, 200, 255)
    vis = cv2.addWeighted(overlay, 0.35, vis, 0.65, 0)

    for d in detections:
        x1, y1, x2, y2 = (int(v) for v in d.box)
        cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
        caption = f"{d.label} {d.score:.2f}"
        cv2.putText(vis, caption, (x1, max(12, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1,
                    lineType=cv2.LINE_AA)
    return vis


def encode_jpeg_b64(bgr_image: np.ndarray, quality: int = 90) -> str:
    ok, buf = cv2.imencode(".jpg",
                           bgr_image,
                           [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("cv2.imencode failed")
    return base64.b64encode(buf.tobytes()).decode("ascii")
