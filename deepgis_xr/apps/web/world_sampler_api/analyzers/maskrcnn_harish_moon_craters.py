"""
MaskRCNN-Harish-Moon-Craters analyzer branch.

Dispatched when ``model_type=maskrcnn_harish_moon_craters``. Proxies
the viewport image to the remote ``maskrcnn-harish-moon-craters-api``
Flask service (``http://192.168.0.232:5009`` by default), which
serves Harish Anand's lunar LROC-NAC crater Mask R-CNN (default
checkpoint ``hanand_stragglers_download.openuas.us_e0099``, classes
``background, crater``).

Companion to ``maskrcnn_brent_moon_craters``; see that module's
docstring for why both Moon-crater branches are deployed at once.
The bundle at ``deployable-self-contained/moon_craters_harish/``
also ships an early-sweep sibling (``e0011``) and a lighter
ResNet-18-FPN backbone variant (``hanand_home__epoch_0008_r18fpn``);
both are reachable per-request via the ``model_id`` form field on
``/api/predict`` without changing this branch.
"""

from ._maskrcnn_remote import RemoteMaskRCNNBranch, run_remote_maskrcnn_branch


_BRANCH = RemoteMaskRCNNBranch(
    model_type='maskrcnn_harish_moon_craters',
    settings_key='MASKRCNN_HARISH_MOON_CRATERS_API_URL',
    display_label='MaskRCNN Harish Moon Craters',
    fallback_label='crater',
    results_subdir='maskrcnn_harish_moon_craters_results',
    folder_prefix='maskrcnn_harish_moon_craters',
    container_name='maskrcnn-harish-moon-craters-api',
    suggested_default_url='http://192.168.0.232:5009',
    default_model_id='hanand_stragglers_download.openuas.us_e0099',
    log_emoji='🌒',
)


def _analyze_viewport_maskrcnn_harish_moon_craters(
    image,
    location,
    model_id,
    score_threshold,
    max_detections,
    scripts_dir,
):
    """Run the remote MaskRCNN-Harish-Moon-Craters API.

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
