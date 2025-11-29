# AI Analysis Report URL Pattern Fix - Added /label/ Prefix

## Problem

The AI analysis report URLs were not matching because:
- Nginx routes `/label/` requests to deepgis-xr (port 8060)
- The URL being requested was: `/label/ai-analysis/report/...`
- But the Django URL pattern was: `ai-analysis/report/...` (missing `/label/` prefix)
- Django saw the path as `label/ai-analysis/report/...` but pattern only matched `ai-analysis/report/...`

## Solution

Updated the URL patterns in `deepgis_xr/apps/web/urls.py` to include the `/label/` prefix, matching the pattern used by all other `/label/` routes.

## Changes Made

### 1. URL Patterns (`deepgis_xr/apps/web/urls.py`)

**Before:**
```python
# AI Analysis Report
path('ai-analysis/report/<str:session_id>/', views.ai_analysis_report, name='ai_analysis_report'),
path('ai-analysis/image/<str:session_id>/<str:image_type>/', views.serve_analysis_image, name='serve_analysis_image'),
```

**After:**
```python
# AI Analysis Report
path('label/ai-analysis/report/<str:session_id>/', views.ai_analysis_report, name='ai_analysis_report'),
path('label/ai-analysis/image/<str:session_id>/<str:image_type>/', views.serve_analysis_image, name='serve_analysis_image'),
```

### 2. Report URL Generation (`deepgis_xr/apps/web/world_sampler_api.py`)

Updated all three instances where `report_url` is generated to include the `/label/` prefix:

**Before:**
```python
'report_url': f'/ai-analysis/report/{session_id}/'
```

**After:**
```python
'report_url': f'/label/ai-analysis/report/{session_id}/'
```

**Locations updated:**
- Line 968: `_analyze_viewport_sam()` function
- Line 1112: `_analyze_viewport_zero_shot()` function  
- Line 1291: `_analyze_viewport_mask2former()` function

## Consistency with Other Routes

All other `/label/` routes in deepgis-xr include the prefix:
- ✅ `path('label/', ...)`
- ✅ `path('label/3d/', ...)`
- ✅ `path('label/3d/topology/', ...)`
- ✅ `path('label/semi-supervised/', ...)`
- ✅ `path('label/ai-analysis/report/...', ...)` ← **Now matches pattern**

## Request Flow (Fixed)

```
User Request: http://deepgis.org/label/ai-analysis/report/...
    ↓
Nginx: location /label/ → proxy to localhost:8060
    ↓
deepgis-xr Django: Receives path as "label/ai-analysis/report/..."
    ↓
URL Pattern: path('label/ai-analysis/report/<str:session_id>/', ...)
    ↓
✅ MATCH! → ai_analysis_report() view
```

## Testing

After these changes, the following URLs should work:

1. **Report URL:**
   ```
   http://deepgis.org/label/ai-analysis/report/sam_20251128_213833_lat64p495971_lonn165p427112_alt251m_modelvit_b/
   ```

2. **Image URL:**
   ```
   http://deepgis.org/label/ai-analysis/image/sam_20251128_213833_lat64p495971_lonn165p427112_alt251m_modelvit_b/query/
   ```

## Files Modified

1. `/home/jdas/dreams-lab-website-server/deepgis-xr/deepgis_xr/apps/web/urls.py`
   - Added `/label/` prefix to AI analysis URL patterns

2. `/home/jdas/dreams-lab-website-server/deepgis-xr/deepgis_xr/apps/web/world_sampler_api.py`
   - Updated `report_url` generation in 3 functions to include `/label/` prefix

## Note on Nginx Configuration

**No nginx changes needed!** The existing `/label/` location block already handles this:

```nginx
location /label/ {
    proxy_pass http://localhost:8060;
}
```

This routes all `/label/*` requests to deepgis-xr, which now has the correct URL patterns.

