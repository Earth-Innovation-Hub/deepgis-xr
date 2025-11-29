# AI Analysis Report URL Routing Issue

## Problem

The URL `http://deepgis.org/ai-analysis/report/sam_20251128_213833_lat64p495971_lonn165p427112_alt251m_modelvit_b/` returns a 404 error because:

1. **The URL pattern exists in `deepgis-xr`** (`deepgis_xr/apps/web/urls.py` line 64)
2. **But nginx is routing it to `dreams_laboratory`** (port 8080) instead of `deepgis-xr` (port 8060)
3. **`dreams_laboratory` doesn't have this URL pattern**, so it returns 404

## Current Nginx Configuration

**File:** `/home/jdas/dreams-lab-website-server/nginx.conf`

```nginx
server {
    server_name deepgis.org www.deepgis.org;
    listen 443 ssl;
    
    # These routes go to deepgis-xr (port 8060)
    location /label/ {
        proxy_pass http://localhost:8060;
    }
    
    location /webclient/ {
        proxy_pass http://localhost:8060;
    }
    
    location /map-label/ {
        proxy_pass http://localhost:8060;
    }
    
    # Default route goes to dreams_laboratory (port 8080)
    location / {
        proxy_pass http://localhost:8080;
    }
}
```

## The Issue

The URL `/ai-analysis/report/...` doesn't match any of the specific location blocks, so it falls through to the default `location /` which proxies to `localhost:8080` (dreams_laboratory).

However, the `ai-analysis/` URL pattern is only defined in:
- ✅ `deepgis-xr/deepgis_xr/apps/web/urls.py` (line 64-65)
- ❌ NOT in `dreams_laboratory/urls.py`

## Solution

Add a location block in nginx.conf to proxy `/ai-analysis/` requests to the deepgis-xr Django app (port 8060):

```nginx
location /ai-analysis/ {
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_pass http://localhost:8060;
    proxy_http_version 1.1;
}
```

## URL Pattern Analysis

### deepgis-xr URLs (port 8060)
- **File:** `deepgis-xr/deepgis_xr/apps/web/urls.py`
- **Pattern:** `path('ai-analysis/report/<str:session_id>/', views.ai_analysis_report, name='ai_analysis_report')`
- **Pattern:** `path('ai-analysis/image/<str:session_id>/<str:image_type>/', views.serve_analysis_image, name='serve_analysis_image')`
- **View:** `deepgis_xr/apps/web/views.py` → `ai_analysis_report()` and `serve_analysis_image()`

### dreams_laboratory URLs (port 8080)
- **File:** `dreams_laboratory/urls.py`
- **Status:** ❌ No `ai-analysis/` patterns defined
- **Result:** 404 error when request hits this server

## Request Flow (Current - Broken)

```
User Request: http://deepgis.org/ai-analysis/report/...
    ↓
Nginx (nginx.conf)
    ↓
No match for /label/, /webclient/, /map-label/
    ↓
Falls through to location / (default)
    ↓
Proxies to localhost:8080 (dreams_laboratory)
    ↓
dreams_laboratory/urls.py - No ai-analysis/ pattern
    ↓
404 Error ❌
```

## Request Flow (Fixed)

```
User Request: http://deepgis.org/ai-analysis/report/...
    ↓
Nginx (nginx.conf)
    ↓
Matches location /ai-analysis/
    ↓
Proxies to localhost:8060 (deepgis-xr)
    ↓
deepgis_xr/apps/web/urls.py - Has ai-analysis/ pattern
    ↓
Views: ai_analysis_report() ✅
```

## Implementation

Add this location block to nginx.conf **before** the default `location /` block:

```nginx
location /ai-analysis/ {
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_pass http://localhost:8060;
    proxy_http_version 1.1;
}
```

**Location in file:** Insert after line 233 (after `/webclient/` block) and before line 235 (before default `location /`).

## Testing

After adding the nginx location block and reloading nginx:

1. Test report URL:
   ```
   http://deepgis.org/ai-analysis/report/sam_20251128_213833_lat64p495971_lonn165p427112_alt251m_modelvit_b/
   ```

2. Test image URL:
   ```
   http://deepgis.org/ai-analysis/image/sam_20251128_213833_lat64p495971_lonn165p427112_alt251m_modelvit_b/query/
   ```

Both should now route correctly to deepgis-xr and return the report/images.

## Related Files

- **Nginx config:** `/home/jdas/dreams-lab-website-server/nginx.conf`
- **deepgis-xr URLs:** `/home/jdas/dreams-lab-website-server/deepgis-xr/deepgis_xr/apps/web/urls.py`
- **deepgis-xr Views:** `/home/jdas/dreams-lab-website-server/deepgis-xr/deepgis_xr/apps/web/views.py`
- **dreams_laboratory URLs:** `/home/jdas/dreams-lab-website-server/dreams_laboratory/urls.py`

