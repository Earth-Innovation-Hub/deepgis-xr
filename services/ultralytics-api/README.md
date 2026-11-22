# ultralytics-api

Flask service for the AI panel's YOLO option: YOLO26 and YOLOE-26 (Ultralytics 8.4)
and SAM 3. It holds one model on the GPU at a time and unloads it after each request.

## Models

| id | what it does | classes |
|---|---|---|
| `yolo26{n,s,m,l,x}` / `yolo26{n,s,m,l,x}-seg` | COCO detection / segmentation | optional COCO filter |
| `yoloe-26{n,s,m,l,x}-seg` | open-vocabulary segmentation | required, any phrases |
| `sam3` | SAM 3 masks from text prompts | required, any phrases |

Old ids `yolov8n`..`yolov8x` map to the YOLO26 segmentation models. YOLO26 and YOLOE
weights download into `weights/` on first use.

## SAM 3 weights

`facebook/sam3` is gated on Hugging Face. Request access on the model page, wait for
approval, create a Read token, then download `sam3.pt` into `weights/`:

```bash
read -s -p "HF token: " HF_TOKEN; echo; export HF_TOKEN
docker run --rm -e HF_TOKEN -v "$PWD/weights:/w" python:3.11-slim \
  bash -c "pip -q install -U huggingface_hub && hf download facebook/sam3 sam3.pt --local-dir /w"
unset HF_TOKEN
```

Until the file is there, `sam3` requests return 503 with `reason: weights_missing`.

## Run

```bash
docker compose up -d --build
```

The compose file joins the web stack's network as `ultralytics-api`; the web container
reaches it through `ULTRALYTICS_API_URL=http://ultralytics-api:5000`. It publishes no
host port. Set the GPU in `device_ids`.

## API

- `GET /health`: device, loaded model, whether `sam3.pt` is present
- `GET /api/models`: the model table above
- `POST /api/predict` (multipart): `file`, `model`, `classes` (comma-separated),
  `confidence` (default 0.25), `imgsz` (default 1024; YOLO models only),
  `max_detections`. Returns detections with pixel boxes and normalized mask rings
  (`mask_polygons_norm`).
