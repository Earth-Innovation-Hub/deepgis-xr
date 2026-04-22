"""
deepgis_xr.apps.web.views — package form.

Previously this was a single 2 633-line module. It is being split into
focused submodules as part of the Tier-B refactor (see
`notes/2026-04-22-deepgis-xr-refactoring.md` in the integration
manuscript workspace).

This `__init__.py` re-exports every public name that `urls.py` routes to,
so `from deepgis_xr.apps.web import views; views.foo` continues to work
unchanged while functions migrate out of `legacy.py` into focused modules.

Migration order (commits land in this order):
    1. Scaffold                  (this commit — everything still in legacy.py)
    2. Missions                  → views/missions.py
    3. Auth AJAX                 → views/auth_ajax.py
    4. AI analysis reports       → views/ai_reports.py
    5. Training datasets         → views/training_datasets.py
    6. 3D model serving          → views/models_3d.py     (future)
    7. Simple page renderers     → views/pages.py         (future)

As each submodule is added, its names are imported here and removed from
the star-import from legacy. Nothing outside the `views/` package should
need to change.
"""

# fmt: off
# --- still-in-legacy (everything lives in legacy.py after the scaffold commit) --
from .legacy import (
    # classes (most are overridden by function aliases below, but kept for API parity)
    BaseView,
    IndexView, LabelView, Label3DView, MapLabelView, ViewLabelView, ResultsView,

    # helpers
    simple_render,
    success_json_response, error_json_response,
    get_image_labels, create_simple_grid,

    # page renderers
    index, label, stl_viewer, label_3d, label_3d_dev,
    map_label, view_label, results,

    # richer page views (have their own request logic)
    label_3d_sigma, label_topology, label_search,
    label_topology_sigma, label_moon_viewer,

    # labeling / tileserver / grid
    get_category_info, get_new_image, save_label, create_category,
    save_labels, export_shapefile, get_raster_info, get_tileserver_url,
    get_tileserver_layers, get_all_images, detect_grid,

    # 3D models
    get_3d_model, list_stl_models,

    # lidar / elevation proxies
    opentopography_lidar_search, elevation_proxy,

    # semi-supervised labeling
    label_semi_supervised, generate_assisted_labels, save_assisted_labels,

    # training datasets: get_label_images only; dataset CRUD moved to .training_datasets
    get_label_images,

)

# --- moved out of legacy.py ---
from .missions import (
    list_missions, create_mission, get_mission, update_mission,
    delete_mission, add_waypoint, remove_waypoint,
)
from .auth_ajax import (
    check_auth_status, ajax_phone_login, ajax_logout,
)
from .ai_reports import (
    ai_analysis_report, serve_analysis_geojson, serve_analysis_image,
    generate_analysis_summary,
)
from .training_datasets import (
    create_training_dataset, list_training_datasets, get_dataset_details,
    add_label_to_dataset,
)
# fmt: on

__all__ = [
    "BaseView",
    "IndexView", "LabelView", "Label3DView", "MapLabelView",
    "ViewLabelView", "ResultsView",
    "simple_render",
    "success_json_response", "error_json_response",
    "get_image_labels", "create_simple_grid",
    "index", "label", "stl_viewer", "label_3d", "label_3d_dev",
    "map_label", "view_label", "results",
    "label_3d_sigma", "label_topology", "label_search",
    "label_topology_sigma", "label_moon_viewer",
    "get_category_info", "get_new_image", "save_label", "create_category",
    "save_labels", "export_shapefile", "get_raster_info", "get_tileserver_url",
    "get_tileserver_layers", "get_all_images", "detect_grid",
    "get_3d_model", "list_stl_models",
    "opentopography_lidar_search", "elevation_proxy",
    "label_semi_supervised", "generate_assisted_labels", "save_assisted_labels",
    "create_training_dataset", "list_training_datasets", "get_dataset_details",
    "add_label_to_dataset", "get_label_images",
    "ai_analysis_report", "serve_analysis_geojson", "serve_analysis_image",
    "generate_analysis_summary",
    "list_missions", "create_mission", "get_mission", "update_mission",
    "delete_mission", "add_waypoint", "remove_waypoint",
    "check_auth_status", "ajax_phone_login", "ajax_logout",
]
