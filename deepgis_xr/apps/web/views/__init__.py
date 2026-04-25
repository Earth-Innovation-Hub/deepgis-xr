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
    # helpers
    success_json_response, error_json_response,
    get_image_labels, create_simple_grid,

    # richer page views (have their own request logic)
    label_3d_sigma, label_topology, label_search,
    label_topology_sigma, label_moon_viewer,

    # labeling / tileserver / grid (save_labels/export_shapefile retained
    # for the legacy /label/ page; map_label and assisted-labeling endpoints
    # have been removed in favour of /label/rocks/edit/<session_id>/).
    get_category_info, get_new_image, save_label, create_category,
    save_labels, export_shapefile, get_raster_info, get_tileserver_url,
    get_tileserver_layers, get_all_images, detect_grid,

    # lidar / elevation proxies
    opentopography_lidar_search, elevation_proxy,
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
from .rock_label import (
    rock_label_edit, rock_label_save_tile, rock_label_capture,
    rock_dataset_list, rock_category_list,
)
from .models_3d import get_3d_model, list_stl_models
from .pages import (
    BaseView,
    IndexView, LabelView, Label3DView, ViewLabelView, ResultsView,
    simple_render,
    index, label, stl_viewer, label_3d, label_3d_dev,
    view_label, results,
)
# fmt: on

__all__ = [
    "BaseView",
    "IndexView", "LabelView", "Label3DView",
    "ViewLabelView", "ResultsView",
    "simple_render",
    "success_json_response", "error_json_response",
    "get_image_labels", "create_simple_grid",
    "index", "label", "stl_viewer", "label_3d", "label_3d_dev",
    "view_label", "results",
    "label_3d_sigma", "label_topology", "label_search",
    "label_topology_sigma", "label_moon_viewer",
    "get_category_info", "get_new_image", "save_label", "create_category",
    "save_labels", "export_shapefile", "get_raster_info", "get_tileserver_url",
    "get_tileserver_layers", "get_all_images", "detect_grid",
    "get_3d_model", "list_stl_models",
    "opentopography_lidar_search", "elevation_proxy",
    "create_training_dataset", "list_training_datasets", "get_dataset_details",
    "add_label_to_dataset",
    "rock_label_edit", "rock_label_save_tile", "rock_label_capture",
    "rock_dataset_list", "rock_category_list",
    "ai_analysis_report", "serve_analysis_geojson", "serve_analysis_image",
    "generate_analysis_summary",
    "list_missions", "create_mission", "get_mission", "update_mission",
    "delete_mission", "add_waypoint", "remove_waypoint",
    "check_auth_status", "ajax_phone_login", "ajax_logout",
]
