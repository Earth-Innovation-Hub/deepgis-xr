"""
Middleware for optimizing 3D model delivery
This middleware:
1. Adds proper caching headers for 3D model files
2. Applies content negotiation for models with multiple formats
3. Selects appropriate LOD models based on client capabilities
"""

import os
import re
import json
from pathlib import Path
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin
from django.http import HttpResponse
import logging

logger = logging.getLogger(__name__)

class ModelOptimizationMiddleware(MiddlewareMixin):
    """
    Middleware to optimize the delivery of 3D models
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        # Regex patterns for model file URLs
        self.model_patterns = [
            r'.*\.(gltf|glb|obj|stl|fbx)$',  # 3D model files
            r'.*/models/.*\.(bin|buffer)$',  # Binary data for models
        ]
        # Cache known model manifests
        self.lod_manifests = {}
        # Initialize
        self._load_manifests()
    
    def _load_manifests(self):
        """Load LOD manifest files"""
        if not hasattr(settings, 'STATIC_ROOT') or not settings.STATIC_ROOT:
            logger.warning("STATIC_ROOT not configured, LOD selection disabled")
            return
        
        # Find all manifest files
        try:
            manifest_files = list(Path(settings.STATIC_ROOT).glob("**/lod/*_manifest.json"))
            for manifest_file in manifest_files:
                try:
                    with open(manifest_file, 'r') as f:
                        manifest_data = json.load(f)
                        # Store using the original model path as key
                        original = Path(manifest_data.get('original', '')).name
                        if original:
                            self.lod_manifests[original] = manifest_data
                            logger.debug(f"Loaded LOD manifest for {original}")
                except Exception as e:
                    logger.error(f"Error loading manifest {manifest_file}: {e}")
        except Exception as e:
            logger.error(f"Error scanning for manifests: {e}")
    
    def _is_model_request(self, path):
        """Check if the request is for a 3D model"""
        for pattern in self.model_patterns:
            if re.match(pattern, path):
                return True
        return False
    
    def _get_device_capability(self, request):
        """
        Determine device capability level based on request headers
        Returns: 0 (low), 1 (medium), 2 (high)
        """
        # Check for explicit capability headers
        capability = request.headers.get('X-Device-Capability')
        if capability:
            try:
                capability = int(capability)
                return min(max(capability, 0), 2)  # Clamp between 0-2
            except (ValueError, TypeError):
                pass
        
        # Check for device type
        user_agent = request.headers.get('User-Agent', '').lower()
        
        # Mobile detection
        is_mobile = any(device in user_agent for device in [
            'mobile', 'android', 'iphone', 'ipad', 'ipod'
        ])
        
        # VR/AR detection
        is_xr = any(xr in user_agent for xr in [
            'oculus', 'vive', 'vrchrome', 'webxr', 'arcore', 'arkit'
        ])
        
        # Hardware classification based on browser hints
        hardware = request.headers.get('Sec-CH-UA-Platform-Version', '')
        hardware_arch = request.headers.get('Sec-CH-UA-Arch', '')
        
        # Simple heuristic - can be improved with more detailed analysis
        if is_xr:
            return 2  # High capability for XR devices
        elif is_mobile:
            return 0  # Low capability for mobile
        elif hardware_arch and 'arm' in hardware_arch.lower():
            return 1  # Medium for ARM devices
        else:
            return 2  # High for desktop
    
    def _select_lod_variant(self, path, device_capability):
        """Select appropriate LOD variant based on device capability"""
        # Extract the base name from the path
        base_name = os.path.basename(path)
        
        # Check if we have LOD versions for this model
        if base_name in self.lod_manifests:
            manifest = self.lod_manifests[base_name]
            variants = manifest.get('variants', [])
            
            # Map device capability to LOD level
            # 0 (low) -> highest LOD (most simplified)
            # 2 (high) -> lowest LOD (highest quality)
            target_level = 2 - device_capability
            
            # Find the best match
            best_match = None
            for variant in variants:
                level = variant.get('level', 0)
                if level == target_level:
                    best_match = variant
                    break
            
            # If exact match not found, use the closest lower LOD
            if not best_match and variants:
                # Sort by level
                sorted_variants = sorted(variants, key=lambda v: v.get('level', 0))
                for variant in sorted_variants:
                    if variant.get('level', 0) >= target_level:
                        best_match = variant
                        break
                
                # If still no match, use the highest LOD
                if not best_match:
                    best_match = sorted_variants[-1]
            
            # Return the matched file path if found
            if best_match and 'file' in best_match:
                return best_match['file']
        
        # No LOD variant found, return original path
        return None
    
    def process_response(self, request, response):
        """Process the response to optimize model delivery"""
        # Only process successful responses
        if response.status_code != 200:
            return response
        
        # Check if this is a model file request
        path = request.path.lower()
        if not self._is_model_request(path):
            return response
        
        # Add caching headers for model files
        if path.endswith('.glb') or path.endswith('.gltf'):
            response['Cache-Control'] = 'public, max-age=2592000'  # 30 days
            response['Expires'] = '2592000'  # 30 days in seconds
        
        # For bin/buffer files (GLTF binary data), use even longer cache
        if path.endswith('.bin') or path.endswith('.buffer'):
            response['Cache-Control'] = 'public, max-age=31536000'  # 1 year
            response['Expires'] = '31536000'  # 1 year in seconds
        
        return response
    
    def process_request(self, request):
        """Process the request to select appropriate model version"""
        # Only process GET requests
        if request.method != 'GET':
            return None
        
        # Check if this might be a model file request
        path = request.path.lower()
        if not self._is_model_request(path):
            return None
        
        # Determine device capability
        device_capability = self._get_device_capability(request)
        logger.debug(f"Device capability for {path}: {device_capability}")
        
        # Select LOD variant
        lod_path = self._select_lod_variant(path, device_capability)
        if lod_path:
            # Redirect to the LOD variant
            # This implementation depends on your URL structure
            # You may need to adapt this to your specific URL patterns
            logger.info(f"Redirecting {path} to LOD variant: {lod_path}")
            # Implementation will depend on your URL structure
            # You might need to modify this based on your setup
        
        return None  # Continue processing 