"""Staff page that lists every label stored in the registry."""

import json
from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse

from deepgis_xr.apps.core.models import (
    CategoryLabel, CategoryType, Image, ImageLabel, TiledGISLabel,
    TrainingDataset, TrainingLabel,
)


def install():
    """Mount the dashboard on the default admin site, once."""
    if getattr(admin.site, "_label_dashboard", False):
        return
    original = admin.site.get_urls

    def get_urls():
        custom = [
            path(
                "labels/",
                admin.site.admin_view(label_dashboard),
                name="label-dashboard",
            ),
            path(
                "labels/mask/<int:image_id>/",
                admin.site.admin_view(label_mask),
                name="label-mask",
            ),
        ]
        return custom + original()

    admin.site.get_urls = get_urls
    admin.site.index_template = "admin/deepgis_index.html"
    admin.site._label_dashboard = True


def label_mask(request, image_id):
    """Serve a label mask through the /label/ prefix so the public proxy can see it."""
    image = get_object_or_404(Image, pk=image_id)
    root = Path(settings.MEDIA_ROOT).resolve()
    path = (root / (image.path or "")).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise Http404("mask not on disk")
    content_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(path.open("rb"), content_type=content_type)


def _feature_count(text):
    if not text:
        return 0
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return 0
    if isinstance(data, dict):
        return len(data.get("features") or [])
    return 0


def _meta(training_labels):
    """City, zoom, and density live on the training-label corrections."""
    for link in training_labels:
        made = link.corrections_made or {}
        if isinstance(made, str):
            try:
                made = json.loads(made)
            except ValueError:
                made = {}
        if not isinstance(made, dict):
            continue
        if made.get("city") or made.get("zoom") or made.get("density_bin"):
            return made
    return {}


def label_dashboard(request):
    dataset_id = request.GET.get("dataset") or ""
    category = request.GET.get("category") or ""
    city = request.GET.get("city") or ""
    query = (request.GET.get("q") or "").strip()

    labels = (
        ImageLabel.objects
        .select_related("image", "labeler", "labeler__user")
        .prefetch_related(
            "categorylabel_set__category",
            "training_datasets__dataset",
        )
        .order_by("-pub_date", "-id")
    )
    if dataset_id.isdigit():
        labels = labels.filter(training_datasets__dataset_id=int(dataset_id))
    if category:
        labels = labels.filter(categorylabel__category__category_name=category)
    if city:
        labels = labels.filter(training_datasets__corrections_made__city=city)
    if query:
        labels = labels.filter(image__name__icontains=query)
    labels = labels.distinct()

    paginator = Paginator(labels, 24)
    page = paginator.get_page(request.GET.get("page") or 1)

    rows = []
    for label in page.object_list:
        categories = []
        for cat_label in label.categorylabel_set.all():
            if cat_label.category_id and cat_label.category.category_name not in categories:
                categories.append(cat_label.category.category_name)
        links = list(label.training_datasets.all())
        datasets = []
        for link in links:
            if link.dataset.name not in datasets:
                datasets.append(link.dataset.name)
        made = _meta(links)
        image = label.image
        has_mask = bool(image and image.path and image.path.lower().endswith((".png", ".jpg", ".jpeg")))
        rows.append({
            "id": label.id,
            "name": image.name if image else "",
            "when": label.pub_date,
            "labeler": str(label.labeler) if label.labeler_id else "",
            "categories": categories,
            "datasets": datasets,
            "polygons": _feature_count(label.combined_label_shapes),
            "city": made.get("city") or "",
            "zoom": made.get("zoom") or "",
            "density": made.get("density_bin") or "",
            "buildings": made.get("building_count") or "",
            "mask_url": reverse("admin:label-mask", args=[image.id]) if has_mask else "",
            "change_url": reverse("admin:core_imagelabel_change", args=[label.id]),
        })

    cities = (
        TrainingLabel.objects
        .exclude(corrections_made__city__isnull=True)
        .exclude(corrections_made__city="")
        .values_list("corrections_made__city", flat=True)
        .distinct()
        .order_by("corrections_made__city")
    )
    context = {
        **admin.site.each_context(request),
        "title": "Label dashboard",
        "rows": rows,
        "page_obj": page,
        "paginator": paginator,
        "datasets": TrainingDataset.objects.order_by("name"),
        "categories": CategoryType.objects.order_by("category_name"),
        "cities": list(cities),
        "filters": {
            "dataset": dataset_id,
            "category": category,
            "city": city,
            "q": query,
        },
        "counts": {
            "image_labels": ImageLabel.objects.count(),
            "category_labels": CategoryLabel.objects.count(),
            "training_labels": TrainingLabel.objects.count(),
            "datasets": TrainingDataset.objects.count(),
            "tiled": TiledGISLabel.objects.count(),
            "showing": paginator.count,
        },
    }
    return TemplateResponse(request, "admin/label_dashboard.html", context)
