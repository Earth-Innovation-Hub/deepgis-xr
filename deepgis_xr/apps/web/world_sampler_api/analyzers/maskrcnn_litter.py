"""
MaskRCNN-Litter analyzer branch.

Dispatched when ``model_type=maskrcnn_litter``. Proxies the viewport
image to the remote ``maskrcnn-litter-api`` Flask service
(``http://192.168.0.232:5005`` by default), which serves the DeepGIS
litter-dynamics Mask R-CNN (default checkpoint
``litter_dynamics_hero_e0008``, classes ``background, litter``).

Catalog note: the underlying ``epoch_0008.param`` weight is
byte-identical to the one served by ``maskrcnn-newlife-api`` on port
5007 (and to three other ``deepgis_*`` siblings — see
``deployable-self-contained/litter_dynamics_deepgis/README.md``).
The two services therefore produce identical predictions until
distinct trained heads are recovered. They are kept as separate
branches because the routing, label contract, and results subdir
are project-specific even when the weights coincide.
"""

from ._maskrcnn_remote import RemoteMaskRCNNBranch, run_remote_maskrcnn_branch


_BRANCH = RemoteMaskRCNNBranch(
    model_type='maskrcnn_litter',
    settings_key='MASKRCNN_LITTER_API_URL',
    display_label='MaskRCNN Litter',
    fallback_label='litter',
    results_subdir='maskrcnn_litter_results',
    folder_prefix='maskrcnn_litter',
    container_name='maskrcnn-litter-api',
    suggested_default_url='http://192.168.0.232:5005',
    log_emoji='🗑️',
)


def _analyze_viewport_maskrcnn_litter(
    image,
    location,
    model_id,
    score_threshold,
    max_detections,
    scripts_dir,
):
    """Run the remote MaskRCNN-Litter API. See :mod:`._maskrcnn_remote`."""
    return run_remote_maskrcnn_branch(
        _BRANCH,
        image=image,
        location=location,
        model_id=model_id,
        score_threshold=score_threshold,
        max_detections=max_detections,
        scripts_dir=scripts_dir,
    )
