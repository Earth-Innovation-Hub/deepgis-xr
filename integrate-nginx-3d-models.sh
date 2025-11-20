#!/bin/bash

# Nginx Integration Script for Large GLB Model Support
# This script safely integrates 3D model optimizations into your existing nginx.conf

set -e  # Exit on any error

NGINX_CONF="/etc/nginx/nginx.conf"
BACKUP_DIR="/home/jdas/dreams-lab-website-server/nginx-backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/nginx.conf.backup.$TIMESTAMP"

echo "🚀 Starting Nginx Integration for Large GLB Model Support"
echo "=================================================="

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Backup current nginx.conf
echo "📋 Creating backup of current nginx.conf..."
sudo cp "$NGINX_CONF" "$BACKUP_FILE"
echo "✅ Backup created: $BACKUP_FILE"

# Check if nginx configuration is valid before starting
echo "🔍 Checking current nginx configuration..."
if ! sudo nginx -t; then
    echo "❌ Current nginx configuration is invalid. Please fix before proceeding."
    exit 1
fi

# Create temporary working file
TEMP_CONF="/tmp/nginx_integrated.conf"
cp "$NGINX_CONF" "$TEMP_CONF"

echo "🔧 Integrating 3D model optimizations..."

# 1. Add enhanced MIME types after existing mime.types include
echo "   Adding enhanced MIME types..."
sed -i '/include \/etc\/nginx\/mime.types;/a\\n    # Enhanced MIME types for 3D models\n    types {\n        model/gltf-binary                     glb;\n        model/gltf+json                       gltf;\n        application/octet-stream              bin buffer;\n        model/obj                             obj;\n        model/mtl                             mtl;\n    }' "$TEMP_CONF"

# 2. Add large file handling settings
echo "   Adding large file handling settings..."
sed -i '/default_type application\/octet-stream;/a\\n    # Large file handling for 3D models\n    client_max_body_size 200M;\n    client_body_buffer_size 128k;\n    client_body_timeout 300s;\n    client_header_timeout 300s;\n    send_timeout 300s;' "$TEMP_CONF"

# 3. Enhance gzip settings
echo "   Enhancing gzip compression..."
# First, check if gzip is already configured
if grep -q "gzip on;" "$TEMP_CONF"; then
    echo "   Gzip already configured, enhancing existing settings..."
    # Add 3D model types to existing gzip_types
    sed -i '/gzip_types/,/;/{
        /;/i\
        model/gltf-binary\
        model/gltf+json\
        application/octet-stream
    }' "$TEMP_CONF"
else
    echo "   Adding new gzip configuration..."
    sed -i '/send_timeout 300s;/a\\n    # Enhanced gzip compression for 3D models\n    gzip on;\n    gzip_vary on;\n    gzip_min_length 1024;\n    gzip_comp_level 6;\n    gzip_types\n        application/octet-stream\n        model/gltf-binary\n        model/gltf+json\n        application/json\n        text/plain\n        text/css\n        application/javascript\n        text/xml\n        application/xml\n        application/xml+rss\n        text/javascript;' "$TEMP_CONF"
fi

# 4. Add proxy settings for large files
echo "   Adding proxy settings for large files..."
sed -i '/resolver 172\.20\.0\.2 valid=2s;/a\\n    # Proxy settings for large files\n    proxy_buffering on;\n    proxy_buffer_size 8k;\n    proxy_buffers 16 8k;\n    proxy_busy_buffers_size 16k;\n    proxy_max_temp_file_size 2048m;\n    proxy_temp_file_write_size 8k;\n    proxy_connect_timeout 300s;\n    proxy_send_timeout 300s;\n    proxy_read_timeout 300s;' "$TEMP_CONF"

# 5. Add 3D models location block to existing deepgis.org server
echo "   Adding 3D models location block to deepgis.org server..."

# Create the location block content
cat > /tmp/models_location.conf << 'EOF'

        location /static/deepgis/models/ {
            alias /home/jdas/dreams-lab-website-server/deepgis-xr/staticfiles/deepgis/models/;
            
            # Extended cache for 3D models
            expires 7d;
            add_header Cache-Control "public, no-transform, immutable";
            
            # CORS headers for 3D models
            add_header Access-Control-Allow-Origin "*" always;
            add_header Access-Control-Allow-Methods "GET, HEAD, OPTIONS" always;
            add_header Access-Control-Allow-Headers "Range, Accept, Accept-Encoding, Accept-Language" always;
            add_header Access-Control-Expose-Headers "Content-Length, Content-Range, Accept-Ranges" always;
            
            # Handle preflight requests
            if ($request_method = 'OPTIONS') {
                add_header Access-Control-Allow-Origin "*" always;
                add_header Access-Control-Allow-Methods "GET, HEAD, OPTIONS" always;
                add_header Access-Control-Allow-Headers "Range, Accept, Accept-Encoding, Accept-Language" always;
                add_header Access-Control-Max-Age 86400;
                add_header Content-Type "text/plain; charset=utf-8";
                add_header Content-Length 0;
                return 204;
            }
            
            # Enable range requests for large files
            add_header Accept-Ranges bytes always;
            
            # Optimize for large file delivery
            sendfile on;
            tcp_nopush on;
            tcp_nodelay on;
            
            # Set appropriate MIME type for GLB files
            location ~* \.glb$ {
                add_header Content-Type "model/gltf-binary" always;
                add_header Content-Disposition "inline" always;
            }
            
            location ~* \.gltf$ {
                add_header Content-Type "model/gltf+json" always;
            }
        }
EOF

# Insert the location block before the closing brace of the deepgis.org server block
sed -i '/server_name deepgis\.org www\.deepgis\.org;/,/^    }$/{
    /^    }$/{
        r /tmp/models_location.conf
    }
}' "$TEMP_CONF"

# 6. Create models directory if it doesn't exist
echo "   Creating models directory structure..."
sudo mkdir -p /home/jdas/dreams-lab-website-server/deepgis-xr/staticfiles/deepgis/models/gltf
sudo chown -R jdas:jdas /home/jdas/dreams-lab-website-server/deepgis-xr/staticfiles/deepgis/models/

# 7. Test the new configuration
echo "🧪 Testing new nginx configuration..."
if sudo nginx -t -c "$TEMP_CONF"; then
    echo "✅ New configuration is valid!"
    
    # Apply the new configuration
    echo "🔄 Applying new configuration..."
    sudo cp "$TEMP_CONF" "$NGINX_CONF"
    
    # Reload nginx
    echo "🔄 Reloading nginx..."
    if sudo systemctl reload nginx; then
        echo "✅ Nginx reloaded successfully!"
    else
        echo "❌ Failed to reload nginx. Restoring backup..."
        sudo cp "$BACKUP_FILE" "$NGINX_CONF"
        sudo systemctl reload nginx
        exit 1
    fi
else
    echo "❌ New configuration is invalid. Check the errors above."
    echo "   Original configuration preserved."
    exit 1
fi

# 8. Create a simple test file
echo "📝 Creating test files..."
cat > /home/jdas/dreams-lab-website-server/deepgis-xr/staticfiles/deepgis/models/index.json << 'EOF'
{
    "models": {
        "navagunjara-reborn-digital-twin-propane-and-solar-v4": {
            "name": "Navagunjara Reborn Digital Twin",
            "description": "Propane and Solar Powered Art Installation",
            "size": "140MB",
            "format": "GLB",
            "optimized_variants": [
                "navagunjara-reborn-digital-twin-propane-and-solar-v4_draco.glb",
                "navagunjara-reborn-digital-twin-propane-and-solar-v4_LOD1.glb",
                "navagunjara-reborn-digital-twin-propane-and-solar-v4_LOD2.glb"
            ]
        }
    },
    "endpoints": {
        "base_url": "https://deepgis.org/static/deepgis/models/gltf/",
        "cors_enabled": true,
        "range_requests": true,
        "compression": "gzip"
    }
}
EOF

# Cleanup
rm -f /tmp/models_location.conf /tmp/nginx_integrated.conf

echo ""
echo "🎉 Integration Complete!"
echo "=================================================="
echo "✅ Nginx configuration updated with 3D model optimizations"
echo "✅ Backup created: $BACKUP_FILE"
echo "✅ Models directory created: /home/jdas/dreams-lab-website-server/deepgis-xr/staticfiles/deepgis/models/"
echo "✅ Test endpoint available: https://deepgis.org/static/deepgis/models/index.json"
echo ""
echo "📋 Next Steps:"
echo "1. Place your 140MB GLB file in: /home/jdas/dreams-lab-website-server/deepgis-xr/staticfiles/deepgis/models/gltf/"
echo "2. Run the optimization script: python deepgis-xr/optimize_large_glb.py"
echo "3. Test the model loading in your DeepGIS XR application"
echo ""
echo "🔗 Your model will be accessible at:"
echo "   https://deepgis.org/static/deepgis/models/gltf/navagunjara-reborn-digital-twin-propane-and-solar-v4.glb"
echo ""
echo "🛠️  To rollback if needed:"
echo "   sudo cp $BACKUP_FILE /etc/nginx/nginx.conf && sudo systemctl reload nginx" 