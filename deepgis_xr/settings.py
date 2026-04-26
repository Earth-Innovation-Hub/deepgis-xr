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
DEBUG = os.environ.get('DEBUG', 'True').lower() == 'true'
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
# USE_L10N was removed: it became the default (True) in Django 4.0 and
# the setting itself is removed in Django 5.0. Keeping this line out
# silences the 4.x deprecation warning without changing behaviour on
# Django 3.2.24 (where True is also the effective default).
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