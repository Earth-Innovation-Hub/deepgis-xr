# AI Analysis Report Image Rendering Fix

## Problem

Images in the AI Analysis Report are only partially rendering - showing the top portion (sky/horizon) but the bottom appears white/blank. This suggests the images are being truncated or not fully loaded.

## Root Causes

1. **FileResponse Configuration**: Missing proper headers for image streaming
2. **Nginx Buffering**: Proxy buffering might be interfering with large image delivery
3. **Content-Length Header**: Missing Content-Length header can cause browsers to stop loading early

## Solution

### 1. Updated FileResponse Implementation

**File:** `deepgis_xr/apps/web/views.py` - `serve_analysis_image()` function

**Changes:**
- Added `Content-Length` header with actual file size
- Added `Accept-Ranges` header for partial content support
- Added `X-Accel-Buffering: no` header to disable nginx buffering for images
- Explicitly set `as_attachment=False` for inline display

**Code:**
```python
response = FileResponse(
    open(image_path, 'rb'),
    content_type=content_type,
    as_attachment=False
)

# Set headers for proper image display
response['Content-Disposition'] = f'inline; filename="{image_path.name}"'
response['Content-Length'] = image_path.stat().st_size
response['Accept-Ranges'] = 'bytes'
response['X-Accel-Buffering'] = 'no'  # Disable nginx buffering
```

### 2. Nginx Configuration (Optional Enhancement)

If images still don't load fully, you may want to add a specific location block for image serving that disables buffering:

**Add to `/etc/nginx/nginx.conf` in the `deepgis.org` server block:**

```nginx
location ~* \.(jpg|jpeg|png|gif|webp)$ {
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_pass http://localhost:8060;
    proxy_http_version 1.1;
    
    # Disable buffering for images
    proxy_buffering off;
    proxy_request_buffering off;
    
    # Cache images
    expires 1h;
    add_header Cache-Control "public, immutable";
}
```

**Note:** This should be added BEFORE the `/label/` location block so it matches first.

## Why This Fixes It

1. **Content-Length Header**: Tells the browser exactly how many bytes to expect, preventing early termination
2. **Accept-Ranges Header**: Enables HTTP range requests for partial content (useful for large images)
3. **X-Accel-Buffering: no**: Tells nginx not to buffer the response, allowing streaming
4. **as_attachment=False**: Ensures images display inline rather than triggering download

## Testing

After applying the fix:

1. **Check browser network tab:**
   - Verify `Content-Length` header matches file size
   - Check if image loads completely (status 200, full size)

2. **Test with different image sizes:**
   - Small images (< 1MB)
   - Medium images (1-5MB)
   - Large images (> 5MB)

3. **Check response headers:**
   ```bash
   curl -I http://deepgis.org/label/ai-analysis/image/session_id/query/
   ```
   Should show:
   - `Content-Length: <file_size>`
   - `Content-Type: image/png` or `image/jpeg`
   - `Accept-Ranges: bytes`

## Files Modified

- `/home/jdas/dreams-lab-website-server/deepgis-xr/deepgis_xr/apps/web/views.py`
  - Updated `serve_analysis_image()` function to add proper headers

## Additional Debugging

If images still don't render fully:

1. **Check file size:**
   ```python
   # In Django shell or view
   from pathlib import Path
   image_path = Path('/app/deepgis_results/sam_results/.../query_image.png')
   print(f"File size: {image_path.stat().st_size} bytes")
   ```

2. **Verify file integrity:**
   ```bash
   file /app/deepgis_results/sam_results/.../query_image.png
   identify /app/deepgis_results/sam_results/.../query_image.png  # if ImageMagick installed
   ```

3. **Check nginx logs:**
   ```bash
   sudo tail -f /var/log/nginx/error.log
   ```

4. **Test direct file access:**
   - Try accessing the image URL directly in browser
   - Check if it loads completely when accessed directly

