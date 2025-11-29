# Nginx Configuration Updates for 3D Model Optimization

These instructions will help you update your existing DreamsLab Nginx configuration to optimize the delivery of 3D models.

## Instructions

1. Open your existing Nginx configuration file (typically `/etc/nginx/nginx.conf` or a site config in `/etc/nginx/sites-available/`)

2. Add these MIME types to your `http` block or `types` block if you already have one:

```nginx
# Add proper MIME types for 3D model files
types {
    model/gltf+json gltf;
    model/gltf-binary glb;
    application/octet-stream bin;
    application/octet-stream buffer;
}
```

3. Make sure the following compression settings are enabled in your `http` block:

```nginx
# Enable compression for 3D model files
gzip on;
gzip_comp_level 5;
gzip_types 
    application/octet-stream
    application/json
    model/gltf-binary
    model/gltf+json;
```

4. Add these location blocks to your server configuration (within the `server` block):

```nginx
# Handle 3D model files with proper caching and compression
location ~* \.(gltf|glb)$ {
    # Enable compression for these files
    gzip_static on;
    gunzip on;
    
    # Set cache control headers
    expires 30d;
    add_header Cache-Control "public, max-age=2592000";
    add_header Vary Accept-Encoding;
    
    # Allow CORS for models
    add_header Access-Control-Allow-Origin "*";
    add_header Access-Control-Allow-Methods "GET, HEAD, OPTIONS";
    
    # Enable byte-range requests for large models
    add_header Accept-Ranges bytes;
}

# Handle auxiliary 3D model files (buffers, textures)
location ~* \.(bin|buffer)$ {
    # Set even longer cache time for binary data
    expires 365d;
    add_header Cache-Control "public, max-age=31536000";
    add_header Vary Accept-Encoding;
    
    # Common binary data compression
    gzip_static on;
    gunzip on;
    
    # Allow CORS for buffers
    add_header Access-Control-Allow-Origin "*";
    add_header Access-Control-Allow-Methods "GET, HEAD, OPTIONS";
    
    # Enable byte-range requests
    add_header Accept-Ranges bytes;
}

# Optimize texture files
location ~* \.(jpg|jpeg|png|webp)$ {
    # Cache settings for textures
    expires 30d;
    add_header Cache-Control "public, max-age=2592000";
    
    # Allow CORS for textures
    add_header Access-Control-Allow-Origin "*";
    
    # WebP support
    add_header Vary Accept;
}
```

5. For HTTP/2 support, ensure your server is listening with HTTP/2 enabled:

```nginx
listen 443 ssl http2;  # If using SSL/TLS (recommended)
```

6. For templates that load 3D models, add the preload headers. You can add this to relevant location blocks (like HTML files):

```nginx
# For templates loading 3D models
location ~* \.(html)$ {
    # Enable preloading
    http2_push_preload on;
    
    # Customize this link to point to your GLB model
    add_header Link "</static/deepgis/models/gltf/navagunjara-sculpture-only.glb>; rel=preload; as=fetch; crossorigin";
}
```

7. Make sure ETags are enabled in the http block:

```nginx
etag on;
```

8. Set appropriate client max body size if you allow model uploads:

```nginx
client_max_body_size 50M;
```

## Example Integration

Here's an example of how these configurations might look in your existing `server` block:

```nginx
server {
    listen 80;
    listen 443 ssl http2;
    server_name dreams-lab.example.com;
    
    # ... your existing configuration ...
    
    # 3D Model optimizations
    location ~* \.(gltf|glb)$ {
        gzip_static on;
        expires 30d;
        add_header Cache-Control "public, max-age=2592000";
        add_header Vary Accept-Encoding;
        add_header Access-Control-Allow-Origin "*";
        add_header Accept-Ranges bytes;
    }
    
    location ~* \.(bin|buffer)$ {
        gzip_static on;
        expires 365d;
        add_header Cache-Control "public, max-age=31536000";
        add_header Vary Accept-Encoding;
        add_header Access-Control-Allow-Origin "*";
        add_header Accept-Ranges bytes;
    }
    
    # ... rest of your configuration ...
}
```

## Testing Your Configuration

After updating your configuration:

1. Check the syntax: `sudo nginx -t`
2. Reload Nginx: `sudo systemctl reload nginx`
3. Verify model loading in the browser (check Network tab in Dev Tools)
4. Confirm proper MIME types and caching headers

## Troubleshooting

If you encounter issues:
- Check Nginx error logs: `sudo tail -f /var/log/nginx/error.log`
- Verify file permissions for model files
- Ensure paths in header directives match your actual file locations 