# DeepGIS-XR — Scripts

Utility scripts, clients, and one-shot tools. Runnable standalone; not
part of the Django app's import graph.

## Contents

| Script | What it does |
|---|---|
| `setup_label_images.py` | Existing helper to seed the label-image set. |
| `sync_assets.sh` | Pull large data/models/deepgis_results from `/mnt/dreamslab-store` so the repo checkout stays light. Run on first boot / after clean clone. |
| `optimize_large_glb.py` | Optimize large GLB models for web delivery (Navagunjara 140 MB, etc.). Uses `gltf-pipeline`, `meshoptimizer`, `draco_encoder`. |
| `grounding_dino_api_client.py` | Python client for the remote GroundingDINO REST service (port 5000 / 5001). |

## Usage

```bash
# Sync data/models/deepgis_results from the lab store
bash scripts/sync_assets.sh

# Optimize a large GLB
python scripts/optimize_large_glb.py --input big.glb --output small.glb

# Call the remote DINO service
python scripts/grounding_dino_api_client.py \
    --image viewport.jpg \
    --prompt "rock . boulder . crater"
```
