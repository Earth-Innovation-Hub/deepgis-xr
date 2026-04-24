#!/usr/bin/env python3
"""
client.py — sibling of dreams-lab-website-server/deepgis-xr/scripts/
            grounding_dino_api_client.py, but for the rock Mask R-CNN service.

Usage
-----

    # Health + models
    python client.py --health
    python client.py --list

    # Detect on an RGB JPG with the default (bishop_hero) model
    python client.py --image bishop_rgb.jpg

    # Pick a specific variant
    python client.py --image bishop_rgb.jpg --model bishop_tl_rgb_e0023

    # Multi-channel .npy (e.g. 4-ch RGB+DEM for the rgbd1 variants)
    python client.py --image tile_rgbd1.npy --model bishop_tl_rgbd1_e0023
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import requests

DEFAULT_URL = "http://192.168.0.232:5002"


def main() -> int:
    ap = argparse.ArgumentParser(description="maskrcnn-rocks-api client")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--image")
    ap.add_argument("--model", dest="model_id")
    ap.add_argument("--score", type=float, default=0.5)
    ap.add_argument("--mask", type=float, default=0.5)
    ap.add_argument("--max", type=int, default=200)
    ap.add_argument("--health", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--info", action="store_true")
    ap.add_argument("--output")
    ap.add_argument("--json", action="store_true",
                    help="print raw JSON response")
    args = ap.parse_args()

    if args.health:
        r = requests.get(f"{args.url}/health", timeout=10)
        print(json.dumps(r.json(), indent=2))
        return 0

    if args.info:
        r = requests.get(f"{args.url}/api/info", timeout=10)
        print(json.dumps(r.json(), indent=2))
        return 0

    if args.list:
        r = requests.get(f"{args.url}/api/models", timeout=10)
        body = r.json()
        for m in body["models"]:
            print(f"{m['id']:<45}  {m['family']:<10}  {m['variant']:<28}  "
                  f"ch={m.get('declared_channels')}")
        print(f"\ntotal: {body['count']}, default: {body['default_model_id']}")
        return 0

    if not args.image:
        ap.error("--image is required for detection")

    path = Path(args.image)
    if not path.exists():
        print(f"no such file: {path}", file=sys.stderr)
        return 1

    with path.open("rb") as f:
        files = {"file": (path.name, f,
                          "application/octet-stream" if path.suffix == ".npy"
                          else "image/jpeg")}
        data = {
            "score_threshold": args.score,
            "mask_threshold": args.mask,
            "max_detections": args.max,
        }
        if args.model_id:
            data["model_id"] = args.model_id
        r = requests.post(f"{args.url}/api/predict",
                          files=files, data=data, timeout=120)

    body = r.json()
    if args.json:
        preview = {**body}
        if "annotated_image" in preview:
            preview["annotated_image"] = "<base64:truncated>"
        print(json.dumps(preview, indent=2))
    else:
        if not body.get("success"):
            print(f"error: {body}")
            return 2
        preds = body["predictions"]
        print(f"model={body['model_id']} (input_channel="
              f"{body['model'].get('declared_channels', '?')})")
        print(f"{preds['count']} rock detections "
              f"({body['inference_ms']} ms, "
              f"{body['image_size']['width']}×{body['image_size']['height']})")
        for i, (score, box) in enumerate(
                zip(preds["scores"], preds["boxes"]), 1):
            x1, y1, x2, y2 = box
            print(f"  #{i:<3}  {score:6.3f}   "
                  f"({x1:7.1f},{y1:7.1f})→({x2:7.1f},{y2:7.1f})")

    if args.output and body.get("annotated_image"):
        b64 = body["annotated_image"].split(",", 1)[-1]
        Path(args.output).write_bytes(base64.b64decode(b64))
        print(f"saved annotated image → {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
