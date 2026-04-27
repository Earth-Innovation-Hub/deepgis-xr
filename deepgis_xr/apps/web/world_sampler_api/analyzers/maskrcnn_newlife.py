"""
MaskRCNN-NewLife analyzer branch.

Dispatched when ``model_type=maskrcnn_newlife``. Proxies the viewport
image to the remote ``maskrcnn-newlife-api`` Flask service
(``http://192.168.0.232:5007`` by default), which serves the DeepGIS
"new life" / biology ground-imagery Mask R-CNN (default checkpoint
``new_life_hero_e0008``, classes ``background, organism``).

Catalog note: see ``maskrcnn_litter.py``. The underlying
``epoch_0008.param`` weight is byte-identical across five
``terrestrial/deepgis_*`` project directories, so this branch and
``maskrcnn_litter`` will return the same masks until distinct
trained heads are recovered. The ``organism`` class label is a
coarse placeholder — refine via ``MASKRCNN_LABELS_NEW_LIFE`` once
the source taxonomy (lichen / moss / biocrust subclasses) is
recovered from the AGU 2021 demo notebook.
"""

from ._maskrcnn_remote import RemoteMaskRCNNBranch, run_remote_maskrcnn_branch


_BRANCH = RemoteMaskRCNNBranch(
    model_type='maskrcnn_newlife',
    settings_key='MASKRCNN_NEWLIFE_API_URL',
    display_label='MaskRCNN NewLife',
    fallback_label='organism',
    results_subdir='maskrcnn_newlife_results',
    folder_prefix='maskrcnn_newlife',
    container_name='maskrcnn-newlife-api',
    suggested_default_url='http://192.168.0.232:5007',
    log_emoji='🌱',
)


def _analyze_viewport_maskrcnn_newlife(
    image,
    location,
    model_id,
    score_threshold,
    max_detections,
    scripts_dir,
):
    """Run the remote MaskRCNN-NewLife API. See :mod:`._maskrcnn_remote`."""
    return run_remote_maskrcnn_branch(
        _BRANCH,
        image=image,
        location=location,
        model_id=model_id,
        score_threshold=score_threshold,
        max_detections=max_detections,
        scripts_dir=scripts_dir,
    )
