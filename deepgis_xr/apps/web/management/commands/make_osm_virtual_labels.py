"""Build a building-label dataset from OpenStreetMap footprints.

OSM is the annotator. The world sampler draws view centers inside city
patches, each view gets a random zoom, and the buildings that fall in
that view become one label. Density (sparse, medium, dense) is balanced
across the set so the corpus is not one downtown repeated a hundred times.
"""

import json
import math
import time
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from shapely.geometry import box

from deepgis_xr.apps.core.models import (
    CategoryLabel, CategoryType, Color, Image, ImageLabel, ImageSourceType,
    ImageWindow, Labeler, TrainingDataset, TrainingLabel,
)
from deepgis_xr.apps.web.world_sampler import WorldSampler


ZOOMS = (17, 18, 19)
VIEW_PX = 512
# Half-size of the OSM patch fetched once per city, in degrees.
FETCH_HALF = 0.008
# Gaussian draw around the city center. Kept inside the patch so a
# zoom-17 window still lies on fetched footprints.
SAMPLE_SPREAD = 0.0025
DATASET_NAME = "OSM buildings virtual annotations"
OVERPASS_URLS = (
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
)
DENSITY_BINS = (
    ("sparse", 1, 8),
    ("medium", 9, 25),
    ("dense", 26, 80),
)


def _meters_per_pixel(lat, zoom):
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom)


def _view_bbox(lat, lon, zoom, pixels=VIEW_PX):
    half_m = (pixels / 2.0) * _meters_per_pixel(lat, zoom)
    dlat = half_m / 111320.0
    cos_lat = max(0.2, math.cos(math.radians(lat)))
    dlon = dlat / cos_lat
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon  # south, west, north, east


def _density_bin(count):
    for name, lo, hi in DENSITY_BINS:
        if lo <= count <= hi:
            return name
    return None


def _ring_norm(geom, south, west, north, east):
    """Exterior ring in normalized image pixels. Origin is the top-left."""
    width = east - west
    height = north - south
    if width <= 0 or height <= 0:
        return []
    raw = list(geom.exterior.coords)
    ring = []
    for lon, lat in raw:
        x = (lon - west) / width
        y = (north - lat) / height
        point = [round(x, 4), round(y, 4)]
        if ring and ring[-1] == point:
            continue
        ring.append(point)
    if len(ring) >= 2 and ring[0] == ring[-1]:
        ring = ring[:-1]
    return ring if len(ring) >= 3 else []


def _simplify(geom):
    current = geom
    for tol in (8e-6, 2e-5, 5e-5):
        candidate = current.simplify(tol, preserve_topology=True)
        if candidate.is_empty or candidate.geom_type != "Polygon":
            continue
        current = candidate
        if len(current.exterior.coords) <= 32:
            break
    return current


class Command(BaseCommand):
    help = "Create building labels from OSM footprints sampled across cities."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=100)
        parser.add_argument("--seed", type=int, default=21)
        parser.add_argument("--dataset-name", default=DATASET_NAME)
        parser.add_argument("--replace", action="store_true")
        parser.add_argument(
            "--cache-only",
            action="store_true",
            help="Use OSM building extracts already cached on this host.",
        )
        parser.add_argument(
            "--cities",
            default="",
            help="Comma-separated city names from WorldSampler.CITY_CENTERS. Empty uses all.",
        )

    def handle(self, *args, **options):
        count = options["count"]
        if count < 1:
            raise CommandError("--count must be at least 1")
        cities = self._select_cities(options["cities"])
        user = self._label_user()
        dataset = self._dataset(user, options["dataset_name"], options["replace"])
        already = dataset.training_labels.count()
        if already >= count:
            self.stdout.write(f"{dataset.name} already has {already} labels")
            return

        sampler = WorldSampler(
            num_points=16,
            initialization="uniform",
            lat_range=(-60, 70),
            lon_range=(-180, 180),
            alt_range=(0, 1000),
            seed=options["seed"],
        )
        if options["cache_only"]:
            candidates = self._candidates_from_cache(sampler)
        else:
            candidates = self._collect_candidates(sampler, cities)
        if not candidates:
            raise CommandError("OSM returned no usable city views")

        chosen = self._balance(sampler, candidates, count - already)
        if len(chosen) < count - already:
            self.stdout.write(
                f"filled {len(chosen)} of {count - already} requested views"
            )
        saved = self._write_labels(dataset, user, chosen, start_index=already)
        self._write_manifest(dataset, saved)
        self.stdout.write(self.style.SUCCESS(
            f"dataset {dataset.id} {dataset.name}: {dataset.training_labels.count()} labels"
        ))

    def _select_cities(self, raw):
        catalog = list(WorldSampler.CITY_CENTERS)
        wanted = [part.strip().lower() for part in raw.split(",") if part.strip()]
        if not wanted:
            return catalog
        chosen = [city for city in catalog if city[0].lower() in wanted]
        missing = sorted(set(wanted) - {city[0].lower() for city in chosen})
        if missing:
            raise CommandError(f"unknown cities: {', '.join(missing)}")
        return chosen

    def _label_user(self):
        User = get_user_model()
        user = User.objects.filter(is_superuser=True).order_by("id").first()
        if user is None:
            user = User.objects.order_by("id").first()
        if user is None:
            raise CommandError("no user available to own the dataset")
        return user

    def _dataset(self, user, name, replace):
        if replace:
            old = TrainingDataset.objects.filter(name=name).first()
            if old is not None:
                self._delete_dataset(old)
        dataset, _ = TrainingDataset.objects.get_or_create(
            name=name,
            defaults={
                "created_by": user,
                "kind": "osm_virtual",
                "description": (
                    "Building footprints taken from OpenStreetMap and treated "
                    "as a third-party annotator. Each label is one sampled "
                    "city view at a random zoom."
                ),
                "min_tiles_for_training": 1000,
                "status": "draft",
            },
        )
        return dataset

    def _delete_dataset(self, dataset):
        image_ids = list(
            dataset.training_labels.values_list("image_label__image_id", flat=True)
        )
        label_ids = list(
            dataset.training_labels.values_list("image_label_id", flat=True)
        )
        dataset.training_labels.all().delete()
        ImageLabel.objects.filter(id__in=label_ids).delete()
        Image.objects.filter(id__in=image_ids).delete()
        dataset.delete()

    def _collect_candidates(self, sampler, cities):
        import osmnx as ox

        ox.settings.use_cache = True
        ox.settings.requests_timeout = 60
        ox.settings.log_console = False
        candidates = []
        for name, lat, lon in cities:
            south, west, north, east = (
                lat - FETCH_HALF, lon - FETCH_HALF,
                lat + FETCH_HALF, lon + FETCH_HALF,
            )
            self.stdout.write(f"fetch {name}")
            self.stdout.flush()
            gdf, error = self._fetch_buildings(ox, name, north, south, east, west)
            if error is not None:
                self.stdout.write(f"  skip {name}: {error}")
                continue
            if gdf is None or gdf.empty:
                self.stdout.write(f"  skip {name}: no buildings")
                continue
            gdf = gdf[gdf.geometry.notnull() & ~gdf.geometry.is_empty]
            self.stdout.write(f"  {name}: {len(gdf)} features")
            draws = sampler.sample_around_cities(
                90, spread_deg=SAMPLE_SPREAD, cities=((name, lat, lon),),
            )
            city_added = 0
            for point in draws:
                zoom = int(sampler.rng.choice(ZOOMS))
                view = _view_bbox(point.lat, point.lon, zoom)
                vs, vw, vn, ve = view
                if vs < south or vw < west or vn > north or ve > east:
                    continue
                window = box(vw, vs, ve, vn)
                try:
                    clipped = gdf.clip(window)
                except Exception:
                    continue
                polygons = []
                for geom in clipped.geometry:
                    if geom is None or geom.is_empty:
                        continue
                    parts = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
                    for part in parts:
                        if part.geom_type != "Polygon" or part.area <= 1e-12:
                            continue
                        polygons.append(_simplify(part))
                density = _density_bin(len(polygons))
                if density is None:
                    continue
                polygons.sort(key=lambda geom: geom.area, reverse=True)
                candidates.append({
                    "city": name,
                    "zoom": zoom,
                    "density": density,
                    "center": (point.lat, point.lon),
                    "bbox": {"south": vs, "west": vw, "north": vn, "east": ve},
                    "polygons": polygons[:60],
                    "building_count": len(polygons),
                    "footprint_fraction": round(
                        sum(p.area for p in polygons) / window.area, 4
                    ),
                })
                city_added += 1
            self.stdout.write(f"  {name}: {city_added} candidate views")
        return candidates

    def _fetch_buildings(self, ox, name, north, south, east, west):
        last = "no attempt"
        for attempt in range(3):
            ox.settings.overpass_url = OVERPASS_URLS[attempt % len(OVERPASS_URLS)]
            try:
                return ox.features_from_bbox(
                    bbox=(north, south, east, west),
                    tags={"building": True},
                ), None
            except Exception as exc:
                last = str(exc).splitlines()[0][:180]
                wait = 15 * (2 ** attempt)
                self.stdout.write(f"  retry {name} in {wait}s: {last}")
                self.stdout.flush()
                time.sleep(wait)
        return None, last

    def _candidates_from_cache(self, sampler):
        """Build view candidates from OSM JSON already stored by osmnx.

        Public Overpass was refusing new city queries. The cache still holds
        building extracts for Berlin and the Phoenix metro, which are cities
        the world sampler knows. Each file's node/way graph is turned back
        into polygons, then sample_around_cities draws the views.
        """
        from shapely.geometry import Polygon
        from shapely.strtree import STRtree

        places = (
            ("Berlin", 52.520, 13.405),
            ("Phoenix", 33.449, -112.074),
            ("Tempe", 33.425, -111.940),
            ("Scottsdale", 33.494, -111.926),
        )
        best = {}
        cache = Path("/app/cache")
        if not cache.is_dir():
            cache = Path("cache")
        for path in cache.glob("*.json"):
            size = path.stat().st_size
            if size < 50_000 or size > 8_000_000:
                continue
            try:
                data = json.loads(path.read_text())
            except Exception:
                continue
            nodes = {}
            buildings = 0
            first = None
            for el in data.get("elements", []):
                if el.get("type") == "node" and "lat" in el:
                    nodes[el["id"]] = (el["lat"], el["lon"])
                if el.get("type") == "way" and "building" in (el.get("tags") or {}):
                    buildings += 1
                    if first is None:
                        for nid in el.get("nodes") or []:
                            if nid in nodes:
                                first = nodes[nid]
                                break
            if buildings < 80 or first is None:
                continue
            lat, lon = first
            nearest, dist = None, 99.0
            for name, plat, plon in places:
                delta = ((lat - plat) ** 2 + (lon - plon) ** 2) ** 0.5
                if delta < dist:
                    nearest, dist = name, delta
            if dist > 0.25:
                continue
            current = best.get(nearest)
            if current is None or buildings > current[0]:
                best[nearest] = (buildings, path, data, nodes)

        candidates = []
        for name, (_count, path, data, nodes) in best.items():
            polygons = []
            for el in data.get("elements", []):
                if el.get("type") != "way" or "building" not in (el.get("tags") or {}):
                    continue
                coords = []
                for nid in el.get("nodes") or []:
                    if nid in nodes:
                        lat, lon = nodes[nid]
                        coords.append((lon, lat))
                if len(coords) < 4:
                    continue
                poly = Polygon(coords)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if poly.is_empty:
                    continue
                if poly.geom_type == "Polygon":
                    polygons.append(poly)
                elif poly.geom_type == "MultiPolygon":
                    polygons.extend(part for part in poly.geoms if not part.is_empty)
            if len(polygons) < 40:
                self.stdout.write(f"skip cache {name}: {len(polygons)} polygons")
                continue
            tree = STRtree(polygons)
            minx = min(p.bounds[0] for p in polygons)
            miny = min(p.bounds[1] for p in polygons)
            maxx = max(p.bounds[2] for p in polygons)
            maxy = max(p.bounds[3] for p in polygons)
            self.stdout.write(f"cache {name}: {len(polygons)} buildings from {path.name[:8]}")
            center_lat = (miny + maxy) / 2.0
            center_lon = (minx + maxx) / 2.0
            spread = max(maxy - miny, maxx - minx) / 6.0
            draws = sampler.sample_around_cities(
                160, spread_deg=spread, cities=((name, center_lat, center_lon),),
            )
            added = 0
            for point in draws:
                zoom = int(sampler.rng.choice(ZOOMS))
                view = _view_bbox(point.lat, point.lon, zoom)
                vs, vw, vn, ve = view
                if vs < miny or vw < minx or vn > maxy or ve > maxx:
                    continue
                window = box(vw, vs, ve, vn)
                chosen_polys = []
                for index in tree.query(window):
                    poly = polygons[int(index)]
                    if not poly.intersects(window):
                        continue
                    piece = poly.intersection(window)
                    parts = piece.geoms if piece.geom_type == "MultiPolygon" else [piece]
                    for part in parts:
                        if part.geom_type != "Polygon" or part.is_empty or part.area <= 1e-12:
                            continue
                        chosen_polys.append(_simplify(part))
                density = _density_bin(len(chosen_polys))
                if density is None:
                    continue
                chosen_polys.sort(key=lambda geom: geom.area, reverse=True)
                candidates.append({
                    "city": name,
                    "zoom": zoom,
                    "density": density,
                    "center": (point.lat, point.lon),
                    "bbox": {"south": vs, "west": vw, "north": vn, "east": ve},
                    "polygons": chosen_polys[:60],
                    "building_count": len(chosen_polys),
                    "footprint_fraction": round(
                        sum(p.area for p in chosen_polys) / window.area, 4
                    ),
                })
                added += 1
            self.stdout.write(f"  {name}: {added} candidate views")
        return candidates

    def _balance(self, sampler, candidates, needed):
        quotas = {"sparse": 0, "medium": 0, "dense": 0}
        base, extra = divmod(needed, 3)
        for index, name in enumerate(("sparse", "medium", "dense")):
            quotas[name] = base + (1 if index < extra else 0)
        order = list(range(len(candidates)))
        sampler.rng.shuffle(order)
        chosen = []
        used = set()
        for index in order:
            item = candidates[index]
            if quotas[item["density"]] <= 0:
                continue
            quotas[item["density"]] -= 1
            chosen.append(item)
            used.add(index)
            if len(chosen) >= needed:
                return chosen
        for index in order:
            if index in used:
                continue
            chosen.append(candidates[index])
            if len(chosen) >= needed:
                break
        return chosen

    def _write_labels(self, dataset, user, chosen, start_index):
        source, _ = ImageSourceType.objects.get_or_create(
            description="OSM building mask (virtual annotator)"
        )
        color, _ = Color.objects.get_or_create(red=59, green=130, blue=246)
        category, _ = CategoryType.objects.get_or_create(
            category_name="building",
            defaults={"label_type": "P", "color": color},
        )
        window, _ = ImageWindow.objects.get_or_create(
            x=0, y=0, width=VIEW_PX, height=VIEW_PX,
        )
        labeler, _ = Labeler.objects.get_or_create(user=user)
        mask_dir = Path(settings.MEDIA_ROOT) / "annotation_game" / "osm_virtual" / "masks"
        mask_dir.mkdir(parents=True, exist_ok=True)
        saved = []
        for offset, item in enumerate(chosen):
            index = start_index + offset + 1
            slug = item["city"].lower().replace(" ", "_")
            name = f"osm_virtual_{index:03d}_{slug}_z{item['zoom']}"
            rel = Path("annotation_game") / "osm_virtual" / "masks" / f"{name}.png"
            collection = self._collection(item)
            if not collection["features"]:
                self.stdout.write(f"skip {item['city']} z{item['zoom']}: empty rings")
                continue
            text = json.dumps(collection, separators=(",", ":"))
            if len(text) > 90000:
                collection["features"] = collection["features"][:30]
                collection["metadata"]["truncated_to"] = 30
                text = json.dumps(collection, separators=(",", ":"))
            self._write_mask(mask_dir / f"{name}.png", collection["features"])
            with transaction.atomic():
                image = Image.objects.create(
                    name=name[:200],
                    path=str(rel).replace("\\", "/"),
                    description=(
                        f"OSM building mask, {item['city']}, "
                        f"zoom {item['zoom']}, {item['density']}"
                    )[:500],
                    source=source,
                    width=VIEW_PX,
                    height=VIEW_PX,
                )
                image.categories.add(category)
                image_label = ImageLabel.objects.create(
                    image=image,
                    combined_label_shapes=text,
                    labeler=labeler,
                    window=window,
                )
                CategoryLabel.objects.create(
                    category=category,
                    label_shapes=text,
                    parent_label=image_label,
                )
                TrainingLabel.objects.create(
                    dataset=dataset,
                    image_label=image_label,
                    source_prediction_id=f"osm:{slug}:{index}",
                    corrections_made={
                        "virtual_annotator": "openstreetmap",
                        "city": item["city"],
                        "zoom": item["zoom"],
                        "density_bin": item["density"],
                        "building_count": item["building_count"],
                        "stored_polygons": len(collection["features"]),
                        "footprint_fraction": item["footprint_fraction"],
                        "bbox": item["bbox"],
                        "center": {"lat": item["center"][0], "lon": item["center"][1]},
                        "coordinate_space": "normalized_top_left",
                    },
                )
            saved.append({
                "name": name,
                "city": item["city"],
                "zoom": item["zoom"],
                "density": item["density"],
                "buildings": item["building_count"],
            })
            self.stdout.write(
                f"saved {index} {item['city']} z{item['zoom']} {item['density']} "
                f"n={item['building_count']}"
            )
            self.stdout.flush()
        return saved

    def _collection(self, item):
        south = item["bbox"]["south"]
        west = item["bbox"]["west"]
        north = item["bbox"]["north"]
        east = item["bbox"]["east"]
        features = []
        for geom in item["polygons"]:
            ring = _ring_norm(geom, south, west, north, east)
            if not ring:
                continue
            features.append({
                "type": "Feature",
                "properties": {"category": "building", "source": "openstreetmap"},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            })
        return {
            "type": "FeatureCollection",
            "metadata": {
                "coordinate_space": "normalized_top_left",
                "virtual_annotator": "openstreetmap",
                "city": item["city"],
                "zoom": item["zoom"],
                "density_bin": item["density"],
                "bbox": item["bbox"],
            },
            "features": features,
        }

    def _write_mask(self, path, features):
        from PIL import Image, ImageDraw

        image = Image.new("L", (VIEW_PX, VIEW_PX), 0)
        draw = ImageDraw.Draw(image)
        for feature in features:
            ring = feature["geometry"]["coordinates"][0]
            pixels = [
                (int(round(x * (VIEW_PX - 1))), int(round(y * (VIEW_PX - 1))))
                for x, y in ring
            ]
            if len(pixels) >= 3:
                draw.polygon(pixels, fill=255)
        image.save(path, "PNG")

    def _write_manifest(self, dataset, saved):
        from collections import Counter

        out_dir = Path(settings.MEDIA_ROOT) / "annotation_game" / "osm_virtual"
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "dataset_id": dataset.id,
            "dataset_name": dataset.name,
            "labels": dataset.training_labels.count(),
            "by_city": dict(Counter(row["city"] for row in saved)),
            "by_zoom": dict(Counter(row["zoom"] for row in saved)),
            "by_density": dict(Counter(row["density"] for row in saved)),
            "rows": saved,
        }
        (out_dir / "manifest.json").write_text(json.dumps(payload, indent=2))
