from rest_framework import serializers
from django.contrib.gis.geos import GEOSGeometry

from deepgis_xr.apps.core.models import (
    CategoryType, Image, ImageLabel, CategoryLabel,
    TiledGISLabel, RasterImage, VehicleType, Vehicle, 
    VehiclePosition, VehicleGeofence, VehicleAlert, Color
)


class ColorSerializer(serializers.Serializer):
    """Color representation"""
    red = serializers.IntegerField(min_value=0, max_value=255)
    green = serializers.IntegerField(min_value=0, max_value=255)
    blue = serializers.IntegerField(min_value=0, max_value=255)


class CategoryTypeSerializer(serializers.ModelSerializer):
    """Category type serializer"""
    color = ColorSerializer()
    
    class Meta:
        model = CategoryType
        fields = ['id', 'category_name', 'pub_date', 'color', 'label_type']


class ImageSerializer(serializers.ModelSerializer):
    """Image serializer"""
    categories = CategoryTypeSerializer(many=True, read_only=True)
    
    class Meta:
        model = Image
        fields = ['id', 'name', 'path', 'description', 'pub_date', 
                 'width', 'height', 'categories']


class ImageLabelSerializer(serializers.ModelSerializer):
    """Image label serializer"""
    image = ImageSerializer()
    
    class Meta:
        model = ImageLabel
        fields = ['id', 'image', 'combined_label_shapes', 'pub_date', 
                 'time_taken']


class CategoryLabelSerializer(serializers.ModelSerializer):
    """Category label serializer"""
    category = CategoryTypeSerializer()
    
    class Meta:
        model = CategoryLabel
        fields = ['id', 'category', 'label_shapes']


class RasterImageSerializer(serializers.ModelSerializer):
    """Raster image serializer"""
    class Meta:
        model = RasterImage
        fields = ['id', 'name', 'path', 'attribution', 'min_zoom', 'max_zoom', 
                 'resolution', 'latitude', 'longitude']


class TiledGISLabelSerializer(serializers.ModelSerializer):
    """GIS label serializer"""
    category = CategoryTypeSerializer()
    parent_raster = RasterImageSerializer()
    
    class Meta:
        model = TiledGISLabel
        fields = ['id', 'northeast_lat', 'northeast_lng', 'southwest_lat', 
                 'southwest_lng', 'zoom_level', 'category', 'label_json',
                 'label_type', 'parent_raster', 'pub_date']
        
    def validate_label_json(self, value):
        """Validate GeoJSON format"""
        try:
            geometry = value.get('geometry', {})
            GEOSGeometry(str(geometry))
        except Exception as e:
            raise serializers.ValidationError(f"Invalid GeoJSON geometry: {str(e)}")
        return value


# ===== VEHICLE TRACKING SERIALIZERS =====

class VehicleTypeSerializer(serializers.ModelSerializer):
    """Vehicle type serializer"""
    default_color = ColorSerializer(read_only=True)
    
    class Meta:
        model = VehicleType
        fields = ['id', 'name', 'category', 'icon_url', 'icon_symbol', 
                 'default_color', 'description', 'created_at']


class VehiclePositionSerializer(serializers.ModelSerializer):
    """Vehicle position serializer"""
    
    class Meta:
        model = VehiclePosition
        fields = ['id', 'latitude', 'longitude', 'altitude', 'heading', 
                 'speed', 'vertical_speed', 'gps_accuracy', 'satellite_count',
                 'battery_level', 'signal_strength', 'sensor_data', 
                 'timestamp', 'received_at']
        read_only_fields = ['id', 'received_at']


class VehicleSerializer(serializers.ModelSerializer):
    """Vehicle serializer"""
    vehicle_type = VehicleTypeSerializer(read_only=True)
    vehicle_type_id = serializers.IntegerField(write_only=True)
    custom_color = ColorSerializer(read_only=True)
    display_color = serializers.CharField(source='get_display_color', read_only=True)
    display_icon = serializers.CharField(source='get_display_icon', read_only=True)
    position_age_seconds = serializers.FloatField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    
    # Include recent positions
    recent_positions = serializers.SerializerMethodField()
    
    class Meta:
        model = Vehicle
        fields = ['id', 'vehicle_id', 'name', 'vehicle_type', 'vehicle_type_id',
                 'status', 'current_latitude', 'current_longitude', 'current_altitude',
                 'current_heading', 'current_speed', 'mission_id', 'last_update',
                 'created_at', 'custom_color', 'custom_icon', 'show_trail',
                 'trail_length', 'max_speed', 'max_altitude', 'battery_level',
                 'display_color', 'display_icon', 'position_age_seconds', 
                 'is_active', 'recent_positions']
        read_only_fields = ['id', 'last_update', 'created_at']
    
    def get_recent_positions(self, obj):
        """Get recent positions for trail display"""
        if not obj.show_trail:
            return []
        
        recent_positions = obj.positions.all()[:obj.trail_length]
        return VehiclePositionSerializer(recent_positions, many=True).data


class VehicleGeofenceSerializer(serializers.ModelSerializer):
    """Vehicle geofence serializer"""
    vehicles = VehicleSerializer(many=True, read_only=True)
    vehicle_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )
    
    class Meta:
        model = VehicleGeofence
        fields = ['id', 'name', 'geofence_type', 'vehicles', 'vehicle_ids',
                 'geometry', 'min_altitude', 'max_altitude', 'is_active',
                 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_geometry(self, value):
        """Validate GeoJSON geometry"""
        try:
            import json
            geometry_dict = json.loads(value) if isinstance(value, str) else value
            GEOSGeometry(json.dumps(geometry_dict))
        except Exception as e:
            raise serializers.ValidationError(f"Invalid GeoJSON geometry: {str(e)}")
        return value
    
    def create(self, validated_data):
        vehicle_ids = validated_data.pop('vehicle_ids', [])
        geofence = super().create(validated_data)
        if vehicle_ids:
            geofence.vehicles.set(vehicle_ids)
        return geofence
    
    def update(self, instance, validated_data):
        vehicle_ids = validated_data.pop('vehicle_ids', None)
        geofence = super().update(instance, validated_data)
        if vehicle_ids is not None:
            geofence.vehicles.set(vehicle_ids)
        return geofence


class VehicleAlertSerializer(serializers.ModelSerializer):
    """Vehicle alert serializer"""
    vehicle = VehicleSerializer(read_only=True)
    vehicle_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = VehicleAlert
        fields = ['id', 'vehicle', 'vehicle_id', 'alert_type', 'severity',
                 'title', 'message', 'latitude', 'longitude', 'altitude',
                 'is_acknowledged', 'acknowledged_at', 'created_at', 'resolved_at',
                 'metadata']
        read_only_fields = ['id', 'created_at', 'acknowledged_at']


# Specialized serializers for different use cases

class VehicleLocationSerializer(serializers.ModelSerializer):
    """Lightweight serializer for vehicle locations only"""
    display_color = serializers.CharField(source='get_display_color', read_only=True)
    display_icon = serializers.CharField(source='get_display_icon', read_only=True)
    
    class Meta:
        model = Vehicle
        fields = ['id', 'vehicle_id', 'name', 'status', 'current_latitude', 
                 'current_longitude', 'current_altitude', 'current_heading',
                 'current_speed', 'battery_level', 'last_update', 'display_color',
                 'display_icon']


class VehicleTrailSerializer(serializers.ModelSerializer):
    """Serializer for vehicle trail data"""
    positions = serializers.SerializerMethodField()
    
    class Meta:
        model = Vehicle
        fields = ['id', 'vehicle_id', 'name', 'display_color', 'positions']
    
    def get_positions(self, obj):
        """Get trail positions"""
        if not obj.show_trail:
            return []
        
        positions = obj.positions.all()[:obj.trail_length]
        return [
            {
                'lat': float(pos.latitude),
                'lng': float(pos.longitude),
                'alt': pos.altitude,
                'timestamp': pos.timestamp.isoformat()
            }
            for pos in positions
        ]


class VehicleStatusUpdateSerializer(serializers.Serializer):
    """Serializer for bulk vehicle status updates"""
    vehicle_id = serializers.CharField()
    latitude = serializers.DecimalField(max_digits=17, decimal_places=14)
    longitude = serializers.DecimalField(max_digits=17, decimal_places=14)
    altitude = serializers.FloatField(required=False, allow_null=True)
    heading = serializers.FloatField(required=False, allow_null=True)
    speed = serializers.FloatField(required=False, allow_null=True)
    battery_level = serializers.FloatField(required=False, allow_null=True)
    status = serializers.ChoiceField(choices=Vehicle.STATUS_CHOICES, required=False)
    timestamp = serializers.DateTimeField(required=False)
    sensor_data = serializers.DictField(required=False)


# Request/Response Serializers
class PredictionRequestSerializer(serializers.Serializer):
    """Prediction request parameters"""
    bounds = serializers.ListField(
        child=serializers.FloatField(),
        min_length=4,
        max_length=4
    )
    raster_id = serializers.IntegerField()
    model_path = serializers.CharField(required=False)
    confidence_threshold = serializers.FloatField(default=0.5)


class PredictionResponseSerializer(serializers.Serializer):
    """Prediction response format"""
    status = serializers.CharField()
    predictions = serializers.DictField()
    message = serializers.CharField(required=False)


class TrainingRequestSerializer(serializers.Serializer):
    """Training request parameters"""
    output_dir = serializers.CharField(required=False)
    

class TrainingResponseSerializer(serializers.Serializer):
    """Training response format"""
    status = serializers.CharField()
    message = serializers.CharField()
    task_id = serializers.CharField() 