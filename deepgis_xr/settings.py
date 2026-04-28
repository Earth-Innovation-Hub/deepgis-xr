import os
import sys
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Add dreams_laboratory/scripts to Python path for SAM and other ML scripts
# Handle both containerized and local environments
# In container: mounted at /app/dreams_laboratory_scripts
# Locally: /home/jdas/dreams-lab-website-server/deepgis-xr -> /home/jdas/dreams-lab-website-server/dreams_laboratory/scripts
WORKSPACE_ROOT = BASE_DIR.parent  # Go up from deepgis-xr/ to dreams-lab-website-server/
SCRIPTS_DIR = WORKSPACE_ROOT / 'dreams_laboratory' / 'scripts'

# If not found, try container path (when running in Docker)
if not SCRIPTS_DIR.exists():
    # In container, scripts are mounted at /app/dreams_laboratory_scripts
    container_scripts_dir = Path('/app') / 'dreams_laboratory_scripts'
    if container_scripts_dir.exists():
        SCRIPTS_DIR = container_scripts_dir
    else:
        # Try other common container mount points
        for mount_point in ['/app/dreams_laboratory/scripts', '/workspace/dreams_laboratory/scripts', '/code/dreams_laboratory/scripts']:
            alt_scripts_dir = Path(mount_point)
            if alt_scripts_dir.exists():
                SCRIPTS_DIR = alt_scripts_dir
                break

if SCRIPTS_DIR.exists() and str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# Core Settings
SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-your-secret-key-here')
# DEBUG defaults to False so that an unset / mistyped env var produces a
# production-safe posture (DisallowedHost, no traceback page, no static-file
# autoreload). Local development must set DEBUG=True explicitly via .env or
# the container env, which docker-compose.yml does for the `web` service when
# the operator opts in. The previous default (True) leaked stack traces and
# wide-open CORS to anyone who deployed without setting the variable; that
# is the wrong direction for the default.
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '*').split(',')

# Application definition
INSTALLED_APPS = [
    # Django apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',
    
    # Third party apps
    'rest_framework',
    'corsheaders',
    'phonenumber_field',
    
    # Local apps - auth must come first
    'deepgis_xr.apps.auth.apps.AuthConfig',
    'deepgis_xr.apps.core',
    'deepgis_xr.apps.api',
    'deepgis_xr.apps.ml',
    'deepgis_xr.apps.web',
    'deepgis_xr.apps.tile_catalog.apps.TileCatalogConfig',
]

# Middleware
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# URLs and Templates
ROOT_URLCONF = 'deepgis_xr.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'deepgis_xr.wsgi.application'

# Database
#
# Backend selection is driven by the ``DATABASE_URL`` env var:
#
#   * unset / blank      -> SQLite at ``BASE_DIR/db.sqlite3`` (legacy default;
#                           the 1.7 GB dev DB lives here today)
#   * ``postgres://...`` -> PostgreSQL (compose ships a ``db`` service, see
#                           docker-compose.yml; psycopg2-binary in
#                           requirements.txt)
#   * any other URL accepted by ``dj_database_url.parse`` (sqlite, mysql, ...)
#
# This indirection exists so that flipping the deployment from SQLite to
# Postgres is a one-line ``.env`` change plus the migration runbook in
# ``STATUS.md`` — no settings.py edit, no image rebuild. ``conn_max_age=600``
# keeps a small connection pool warm for Postgres without affecting SQLite
# (which ignores the field).
_DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
if _DATABASE_URL:
    try:
        import dj_database_url
    except ImportError as exc:  # pragma: no cover — defensive
        raise ImportError(
            "DATABASE_URL is set but dj-database-url is not installed. "
            "Add `dj-database-url` to requirements.txt or unset DATABASE_URL "
            "to fall back to the SQLite default."
        ) from exc
    DATABASES = {
        'default': dj_database_url.parse(
            _DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
# USE_L10N was removed in Django 5.0; localization is always on.
USE_TZ = True

# Static and Media Files
STATIC_URL = os.environ.get('STATIC_URL', '/label/static/deepgis/')
STATIC_ROOT = os.path.join(BASE_DIR, 'static')
# Single source of truth for frontend assets is BASE_DIR/staticfiles/ (tracked in git).
# deepgis_xr/static/ holds vendored libs (paperjs, jquery) — also untracked; see
# refactor/tier-d0-static-tree-consolidation for the plan to fold it into staticfiles/lib/.
# We deliberately do NOT use collectstatic; Django serves these dirs directly via
# staticfiles finders in both dev and container deployments.
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'staticfiles'),
    os.path.join(BASE_DIR, 'deepgis_xr', 'static'),
]

MEDIA_URL = '/media/deepgis/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Storages dict — Django 4.2 introduced the unified STORAGES setting and
# Django 5.x deprecates the legacy STATICFILES_STORAGE / DEFAULT_FILE_STORAGE
# scalars. We declare these explicitly even though the values match Django's
# own defaults, so a future bump (e.g. swapping in ManifestStaticFilesStorage
# behind a CDN, or S3Boto3Storage for media) is a one-line change here.
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Celery Configuration
CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://redis:6379/0')
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'

# CORS settings
CORS_ALLOW_ALL_ORIGINS = DEBUG  # Only allow all origins in debug mode
CORS_ALLOW_CREDENTIALS = True

# REST Framework settings
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
}

# GIS Services Configuration
VECTOR_TILES_URL = os.environ.get('VECTOR_TILES_URL', 'https://vector_tiles:8080')
RASTER_TILES_URL = os.environ.get('RASTER_TILES_URL', 'https://raster_tiles:8081')

# Cesium Ion access token for 3D globe/terrain visualization
CESIUM_ION_TOKEN = os.environ.get('CESIUM_ION_TOKEN', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiI5MzIyMWMxOC03MTk5LTQyMmUtYTM5NC02NzVlYWU1NDg2NGYiLCJpZCI6MzA1OTgwLCJpYXQiOjE3NDgxMjcxNDZ9.AgxpEL6okIFIv0028AEmR2Mk9GeHCPLQyM3RjjBORNk')

# Custom user model
AUTH_USER_MODEL = 'deepgis_auth.User'

# Authentication settings
LOGIN_URL = 'auth:phone_login'
LOGIN_REDIRECT_URL = 'index'
LOGOUT_REDIRECT_URL = 'index'
SESSION_COOKIE_NAME = os.environ.get('SESSION_COOKIE_NAME', 'deepgis_xr_sessionid')
CSRF_COOKIE_NAME = os.environ.get('CSRF_COOKIE_NAME', 'deepgis_xr_csrftoken')
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        'CSRF_TRUSTED_ORIGINS',
        'https://deepgis.org,http://deepgis.org',
    ).split(',')
    if origin.strip()
]
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# Authentication backends
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]

# Phone number field settings
PHONENUMBER_DEFAULT_REGION = 'US'  # Change this to your default region

# Twilio settings
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER', '')

# Tile server settings
TILESERVER_URL = 'https://tileserver'
TILESERVER_PORT = '80'

# Remote AI Services Configuration
# Grounding DINO API - Set to your GPU server running the grounding-dino Docker container
# Example: GROUNDING_DINO_API_URL=http://192.168.0.232:5000
GROUNDING_DINO_API_URL = os.environ.get('GROUNDING_DINO_API_URL', None)

# Grounded-SAM-2 API - Grounding DINO + SAM 2 for detection + segmentation
# Example: GROUNDED_SAM_API_URL=http://192.168.0.232:5001
GROUNDED_SAM_API_URL = os.environ.get('GROUNDED_SAM_API_URL', None)

# Classic SAM API - automatic mask generation with Meta Segment Anything v1
# Example: SAM_API_URL=http://192.168.0.232:5010
SAM_API_URL = os.environ.get('SAM_API_URL', None)

# Unified MaskRCNN API — single Flask container that serves the full model
# registry across all eight families (rocks, house, hypolith, litter,
# roadkill, newlife, brent_moon_craters, harish_moon_craters). When set,
# every analyzer that today uses a per-family ``MASKRCNN_*_API_URL``
# routes here instead, injecting the family's ``default_model_id`` into
# the form payload so the unified container picks the correct
# checkpoint. The per-family URLs below take precedence when set, so
# rollout can be gradual: leave the per-family URLs alone, drop them
# one at a time as each family is migrated to the unified container.
# Example: MASKRCNN_API_URL=http://192.168.0.232:5002
MASKRCNN_API_URL = os.environ.get('MASKRCNN_API_URL', None)

# MaskRCNN Rocks API - Rock instance-segmentation Mask R-CNN ensemble
# (Bishop/Jezero-analog flagship model `bishop_hero_e0004` by default).
# Example: MASKRCNN_ROCKS_API_URL=http://192.168.0.232:5002
MASKRCNN_ROCKS_API_URL = os.environ.get('MASKRCNN_ROCKS_API_URL', None)

# MaskRCNN House API — Tornado/Eureka damage-detection Mask R-CNN ensemble
# (Zhiang's `tornado_detector_eureka_aug_mult_e0039` by default; 6 classes:
# background, house_undamaged, house_damage_{0..3}). Used as an additional
# distinction kernel by the Distinction Game SceneGraph orchestrator —
# nominally a "house" detector but in practice sometimes fires on rooftops
# regardless of damage state, which is exactly the kind of label-vs-kernel
# mismatch the Q_s refit is meant to absorb (see kernelcal docs §3.0).
# Example: MASKRCNN_HOUSE_API_URL=http://192.168.0.232:5003
MASKRCNN_HOUSE_API_URL = os.environ.get('MASKRCNN_HOUSE_API_URL', None)

# Remaining six remote Mask R-CNN sibling services — same upstream
# `services/maskrcnn-rocks/` Docker image as the rocks/house pair, each
# configured with a different env-driven `DEFAULT_MODEL_ID` and
# `MASKRCNN_LABELS_<FAMILY>` so the analyzer branches can dispatch to
# distinct domains without rebuilding the image. Bundles for these
# weights live under `/mnt/22tb-hdd/maskrcnn/deployable-self-contained/`
# (see top-level `deployable_models.json` for the index).

# MaskRCNN Hypolith API — Gobabeb-Namib hypolithic-microbe detector
# (default `gobabeb_hero_e0011`, classes background,hypolith).
# Example: MASKRCNN_HYPOLITH_API_URL=http://192.168.0.232:5004
MASKRCNN_HYPOLITH_API_URL = os.environ.get('MASKRCNN_HYPOLITH_API_URL', None)

# MaskRCNN Litter API — DeepGIS litter-dynamics detector
# (default `litter_dynamics_hero_e0008`, classes background,litter).
# NOTE: underlying weight is byte-identical to the one served by
# MASKRCNN_NEWLIFE_API_URL — predictions will match until distinct
# trained heads are recovered. See
# `analyzers/maskrcnn_litter.py` docstring.
# Example: MASKRCNN_LITTER_API_URL=http://192.168.0.232:5005
MASKRCNN_LITTER_API_URL = os.environ.get('MASKRCNN_LITTER_API_URL', None)

# MaskRCNN Roadkill API — Sarah's DeepGIS roadkill detector
# (default `roadkill__sarah_e0004`, classes background,roadkill).
# Caveat: only 4 epochs of training — treat detections as candidates
# for human review, not as ground-truth labels.
# Example: MASKRCNN_ROADKILL_API_URL=http://192.168.0.232:5006
MASKRCNN_ROADKILL_API_URL = os.environ.get('MASKRCNN_ROADKILL_API_URL', None)

# MaskRCNN NewLife API — DeepGIS biology ground-imagery detector
# (default `new_life_hero_e0008`, classes background,organism).
# NOTE: shares weights with MASKRCNN_LITTER_API_URL — see above.
# The "organism" class is a coarse placeholder; refine via
# MASKRCNN_LABELS_NEW_LIFE on the upstream container once the AGU 2021
# taxonomy is recovered.
# Example: MASKRCNN_NEWLIFE_API_URL=http://192.168.0.232:5007
MASKRCNN_NEWLIFE_API_URL = os.environ.get('MASKRCNN_NEWLIFE_API_URL', None)

# MaskRCNN Brent Moon Craters API — Brent's lunar LROC-NAC crater
# detector (default `moon_craters_brent_brent_e0009`, classes
# background,crater). Companion to MASKRCNN_HARISH_MOON_CRATERS_API_URL
# below; both services run simultaneously so Brent's 9-epoch run and
# Harish's 99-epoch run can be compared side-by-side on the same
# viewport.
# Example: MASKRCNN_BRENT_MOON_CRATERS_API_URL=http://192.168.0.232:5008
MASKRCNN_BRENT_MOON_CRATERS_API_URL = os.environ.get(
    'MASKRCNN_BRENT_MOON_CRATERS_API_URL', None,
)

# MaskRCNN Harish Moon Craters API — Harish Anand's lunar LROC-NAC
# crater detector (default
# `hanand_stragglers_download.openuas.us_e0099`, classes
# background,crater). Bundle ships two sweep siblings (`e0099` best,
# `e0011` early) plus a lighter ResNet-18-FPN backbone variant; all
# reachable per-request via the `model_id` form field.
# Example: MASKRCNN_HARISH_MOON_CRATERS_API_URL=http://192.168.0.232:5009
MASKRCNN_HARISH_MOON_CRATERS_API_URL = os.environ.get(
    'MASKRCNN_HARISH_MOON_CRATERS_API_URL', None,
)

# MIME type configuration for 3D model files
import mimetypes
mimetypes.add_type('application/octet-stream', '.glb')
mimetypes.add_type('model/gltf-binary', '.glb')
mimetypes.add_type('model/gltf+json', '.gltf')
mimetypes.add_type('application/gltf+json', '.gltf')

# Static file serving configuration for large files
DATA_UPLOAD_MAX_MEMORY_SIZE = 200 * 1024 * 1024  # 200MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 200 * 1024 * 1024  # 200MB

# Add middleware for model optimization
MIDDLEWARE.insert(-1, 'deepgis_xr.apps.web.middleware.model_optimizations.ModelOptimizationMiddleware') 