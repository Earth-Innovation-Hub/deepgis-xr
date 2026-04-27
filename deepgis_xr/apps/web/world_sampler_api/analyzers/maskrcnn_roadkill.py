"""
MaskRCNN-Roadkill analyzer branch.

Dispatched when ``model_type=maskrcnn_roadkill``. Proxies the viewport
image to the remote ``maskrcnn-roadkill-api`` Flask service
(``http://192.168.0.232:5006`` by default), which serves Sarah's
DeepGIS roadkill detector (default checkpoint
``roadkill__sarah_e0004``, classes ``background, roadkill``).

Caveat: the upstream weight has only seen 4 epochs of training, which
is preview-quality. False positives on shadows, oil stains, and
rectangular debris are expected; treat detections as candidates
for human review, not as ground-truth labels. The analyzer routing
will continue to work unchanged once a longer replacement run is
swapped in via the ``DEFAULT_MODEL_ID`` env block on the container.
"""

from ._maskrcnn_remote import RemoteMaskRCNNBranch, run_remote_maskrcnn_branch


_BRANCH = RemoteMaskRCNNBranch(
    model_type='maskrcnn_roadkill',
    settings_key='MASKRCNN_ROADKILL_API_URL',
    display_label='MaskRCNN Roadkill',
    fallback_label='roadkill',
    results_subdir='maskrcnn_roadkill_results',
    folder_prefix='maskrcnn_roadkill',
    container_name='maskrcnn-roadkill-api',
    suggested_default_url='http://192.168.0.232:5006',
    default_model_id='roadkill__sarah_e0004',
    log_emoji='🦝',
)


def _analyze_viewport_maskrcnn_roadkill(
    image,
    location,
    model_id,
    score_threshold,
    max_detections,
    scripts_dir,
):
    """Run the remote MaskRCNN-Roadkill API. See :mod:`._maskrcnn_remote`."""
    return run_remote_maskrcnn_branch(
        _BRANCH,
        image=image,
        location=location,
        model_id=model_id,
        score_threshold=score_threshold,
        max_detections=max_detections,
        scripts_dir=scripts_dir,
    )
