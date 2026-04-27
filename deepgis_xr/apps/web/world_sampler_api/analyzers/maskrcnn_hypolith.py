"""
MaskRCNN-Hypolith analyzer branch.

Dispatched when ``model_type=maskrcnn_hypolith``. Proxies the viewport
image to the remote ``maskrcnn-hypolith-api`` Flask service
(``http://192.168.0.232:5004`` by default), which runs the same
``maskrcnn-rocks:latest`` Docker image as the rocks/house siblings,
configured at runtime to serve the Gobabeb-Namib hypolithic-microbe
detector (default checkpoint ``gobabeb_hero_e0011``, classes
``background, hypolith``).

All HTTP plumbing, JPEG re-encoding, response decoding, and on-disk
artefact layout live in :mod:`._maskrcnn_remote`. This module only
declares the per-branch identity (settings key, container name,
results subdir, fallback class label, etc.).

The promoted weight bundle lives at
``/mnt/22tb-hdd/maskrcnn/deployable-self-contained/hypolith_gobabeb/``
and is also reachable through the model registry as
``gobabeb_hero_e0011``; the same family carries 26 ablation siblings
(``rock_*``, ``c3_*``, ``dem_*``) that can be selected per-request
via the ``model_id`` form field on ``/api/predict``.
"""

from ._maskrcnn_remote import RemoteMaskRCNNBranch, run_remote_maskrcnn_branch


_BRANCH = RemoteMaskRCNNBranch(
    model_type='maskrcnn_hypolith',
    settings_key='MASKRCNN_HYPOLITH_API_URL',
    display_label='MaskRCNN Hypolith',
    fallback_label='hypolith',
    results_subdir='maskrcnn_hypolith_results',
    folder_prefix='maskrcnn_hypolith',
    container_name='maskrcnn-hypolith-api',
    suggested_default_url='http://192.168.0.232:5004',
    log_emoji='🦠',
)


def _analyze_viewport_maskrcnn_hypolith(
    image,
    location,
    model_id,
    score_threshold,
    max_detections,
    scripts_dir,
):
    """Run the remote MaskRCNN-Hypolith API. See :mod:`._maskrcnn_remote`."""
    return run_remote_maskrcnn_branch(
        _BRANCH,
        image=image,
        location=location,
        model_id=model_id,
        score_threshold=score_threshold,
        max_detections=max_detections,
        scripts_dir=scripts_dir,
    )
