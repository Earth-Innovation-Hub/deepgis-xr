"""
MaskRCNN-Brent-Moon-Craters analyzer branch.

Dispatched when ``model_type=maskrcnn_brent_moon_craters``. Proxies
the viewport image to the remote ``maskrcnn-brent-moon-craters-api``
Flask service (``http://192.168.0.232:5008`` by default), which
serves Brent's lunar LROC-NAC crater Mask R-CNN (default checkpoint
``moon_craters_brent_brent_e0009``, classes ``background, crater``).

Companion to ``maskrcnn_harish_moon_craters`` — same target body
(Moon, LROC-NAC imagery), different training run. Brent's run hits
9 epochs on the ``moon_craters_brent`` bundle; Harish's hits 99 on
the ``moon_craters_harish`` bundle. Side-by-side comparison is the
explicit reason both are deployed simultaneously rather than
collapsed into one ``moon_craters`` branch.
"""

from ._maskrcnn_remote import RemoteMaskRCNNBranch, run_remote_maskrcnn_branch


_BRANCH = RemoteMaskRCNNBranch(
    model_type='maskrcnn_brent_moon_craters',
    settings_key='MASKRCNN_BRENT_MOON_CRATERS_API_URL',
    display_label='MaskRCNN Brent Moon Craters',
    fallback_label='crater',
    results_subdir='maskrcnn_brent_moon_craters_results',
    folder_prefix='maskrcnn_brent_moon_craters',
    container_name='maskrcnn-brent-moon-craters-api',
    suggested_default_url='http://192.168.0.232:5008',
    log_emoji='🌑',
)


def _analyze_viewport_maskrcnn_brent_moon_craters(
    image,
    location,
    model_id,
    score_threshold,
    max_detections,
    scripts_dir,
):
    """Run the remote MaskRCNN-Brent-Moon-Craters API.

    See :mod:`._maskrcnn_remote`.
    """
    return run_remote_maskrcnn_branch(
        _BRANCH,
        image=image,
        location=location,
        model_id=model_id,
        score_threshold=score_threshold,
        max_detections=max_detections,
        scripts_dir=scripts_dir,
    )
