from __future__ import unicode_literals

from datetime import datetime
from django.contrib.auth.models import User
from django.db import models
from django.core.validators import MaxValueValidator
import random
from django.db.models import JSONField
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


class Color(models.Model):
    """Color model for category visualization"""
    red = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(255)])
    green = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(255)])
    blue = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(255)])

    class Meta:
        unique_together = ('red', 'green', 'blue')

    def __str__(self):
        return f"rgb({self.red}, {self.green}, {self.blue})"


def get_default_color():
    """Get or create default color"""
    default_color = Color.objects.first()
    if not default_color:
        default_color = Color.objects.create()
    return default_color.id


def get_random_color():
    """Get a random unused color or create new one"""
    if Color.objects.count() <= 1:
        with open('deepgis_xr/data/distinct_colors.txt') as f:
            for line in f:
                r, g, b = [int(n) for n in line.split()]
                Color.objects.get_or_create(red=r, green=g, blue=b)
    
    query = Color.objects.filter(categorytype=None)
    if query:
        return query[0]
    return Color.objects.order_by('?').first()


class CategoryType(models.Model):
    """Category for classification"""
    LABEL_TYPE_CHOICES = [
        ("R", "Rectangle"),
        ("C", "Circle"), 
        ("P", "Polygon"),
        ("A", "Any")
    ]

    category_name = models.CharField(default='unknown', max_length=100, unique=True)
    pub_date = models.DateTimeField(default=datetime.now, blank=True)
    color = models.ForeignKey(Color, on_delete=models.CASCADE, null=True)
    label_type = models.CharField(max_length=1, choices=LABEL_TYPE_CHOICES, default="C")

    def __str__(self):
        return f'Category: {self.category_name}'


class ImageSourceType(models.Model):
    """Source type for images"""
    description = models.CharField(default='unknown', max_length=200, unique=True)
    pub_date = models.DateTimeField(default=datetime.now, blank=True)

    def __str__(self):
        return f'Source: {self.description}'


class Image(models.Model):
    """Base image model"""
    name = models.CharField(max_length=200)
    path = models.CharField(max_length=500)
    description = models.CharField(max_length=500)
    source = models.ForeignKey(ImageSourceType, on_delete=models.CASCADE)
    pub_date = models.DateTimeField(default=datetime.now, blank=True)
    width = models.PositiveSmallIntegerField(default=1920)
    height = models.PositiveSmallIntegerField(default=1080)
    categories = models.ManyToManyField(CategoryType)

    class Meta:
        unique_together = ('name', 'path')

    def __str__(self):
        return f'Image: {self.name}'


class Labeler(models.Model):
    """User who performs labeling"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='labelers'
    )

    def __str__(self):
        return str(self.user)


class ImageWindow(models.Model):
    """Window/crop of an image"""
    x = models.PositiveSmallIntegerField()
    y = models.PositiveSmallIntegerField() 
    width = models.PositiveSmallIntegerField()
    height = models.PositiveSmallIntegerField()

    class Meta:
        unique_together = ('x', 'y', 'width', 'height')

    def __str__(self):
        return f'Window: ({self.x},{self.y}), {self.width}x{self.height}'


def get_default_window():
    """Get or create default full-size window"""
    default_window = ImageWindow.objects.filter(
        x=0, y=0, width=1920, height=1080
    ).first()
    
    if not default_window:
        default_window = ImageWindow.objects.create(
            x=0, y=0, width=1920, height=1080
        )
    return default_window.id


class ImageLabel(models.Model):
    """Label for an image"""
    image = models.ForeignKey(Image, on_delete=models.CASCADE)
    combined_label_shapes = models.TextField(max_length=100000)
    pub_date = models.DateTimeField(default=datetime.now, blank=True)
    labeler = models.ForeignKey(Labeler, on_delete=models.CASCADE, null=True, blank=True)
    window = models.ForeignKey(ImageWindow, on_delete=models.CASCADE, default=get_default_window)
    time_taken = models.PositiveIntegerField(null=True)

    def __str__(self):
        return f'Label: {self.image.name} by {self.labeler} on {self.pub_date}'


class CategoryLabel(models.Model):
    """Label for a specific category"""
    category = models.ForeignKey(CategoryType, on_delete=models.CASCADE)
    label_shapes = models.TextField(max_length=100000)
    parent_label = models.ForeignKey(ImageLabel, on_delete=models.CASCADE)

    def __str__(self):
        return f'{self.parent_label} | Category: {self.category}'


class ImageFilter(models.Model):
    """Image enhancement filters"""
    brightness = models.DecimalField(max_digits=3, decimal_places=1, default=1)
    contrast = models.DecimalField(max_digits=3, decimal_places=1, default=1)
    saturation = models.DecimalField(max_digits=3, decimal_places=1, default=1)
    image_label = models.ForeignKey(ImageLabel, on_delete=models.CASCADE, null=True, blank=True)
    labeler = models.ForeignKey(Labeler, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return f'Filter: brightness={self.brightness}, contrast={self.contrast}, saturation={self.saturation}'


class TiledLabel(models.Model):
    """Base class for tiled labels"""
    LABEL_TYPE_CHOICES = [
        ("R", "Rectangle"),
        ("C", "Circle"),
        ("P", "Polygon"), 
        ("A", "Any")
    ]

    northeast_lat = models.DecimalField(max_digits=17, decimal_places=14)
    northeast_lng = models.DecimalField(max_digits=17, decimal_places=14)
    southwest_lat = models.DecimalField(max_digits=17, decimal_places=14)
    southwest_lng = models.DecimalField(max_digits=17, decimal_places=14)
    zoom_level = models.PositiveSmallIntegerField(default=23)
    category = models.ForeignKey(CategoryType, on_delete=models.CASCADE, null=True, blank=True)
    label_json = JSONField()
    label_type = models.CharField(max_length=1, choices=LABEL_TYPE_CHOICES, default="R")

    class Meta:
        abstract = True


class RasterImage(models.Model):
    """Raster image data"""
    name = models.CharField(max_length=5000, unique=True)
    path = models.CharField(max_length=5000)
    attribution = models.CharField(max_length=5000)
    min_zoom = models.FloatField()
    max_zoom = models.FloatField()
    resolution = models.FloatField(default=-1)
    latitude = models.FloatField(default=0)
    longitude = models.FloatField(default=0)

    def __str__(self):
        return f'Raster: {self.name}'


class TiledGISLabel(TiledLabel):
    """GIS-specific tiled label"""
    parent_raster = models.ForeignKey(RasterImage, on_delete=models.CASCADE, null=True, blank=True)
    pub_date = models.DateTimeField(default=datetime.now, blank=True)
    labeler = models.ForeignKey(Labeler, on_delete=models.CASCADE, null=True, blank=True)
    geometry = models.TextField(max_length=100000)

    def __str__(self):
        return f'GIS Label: {self.category} at ({self.northeast_lat},{self.northeast_lng})' 


# ===== VEHICLE TRACKING MODELS =====

class VehicleType(models.Model):
    """Types of vehicles that can be tracked"""
    VEHICLE_CATEGORIES = [
        ('DRONE', 'Drone/UAV'),
        ('GROUND', 'Ground Vehicle'),
        ('MARINE', 'Marine Vehicle'),
        ('AIRCRAFT', 'Aircraft'),
        ('SATELLITE', 'Satellite'),
        ('PERSON', 'Person/Personnel'),
        ('ROBOT', 'Robot'),
        ('OTHER', 'Other')
    ]
    
    name = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=20, choices=VEHICLE_CATEGORIES, default='OTHER')
    icon_url = models.URLField(max_length=500, blank=True, null=True)
    icon_symbol = models.CharField(max_length=10, default='📍')  # Unicode emoji/symbol
    default_color = models.ForeignKey(Color, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['category', 'name']
    
    def __str__(self):
        return f'{self.name} ({self.get_category_display()})'


class Vehicle(models.Model):
    """Individual vehicle instances"""
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('INACTIVE', 'Inactive'),
        ('MAINTENANCE', 'Maintenance'),
        ('LOST', 'Lost Signal'),
        ('EMERGENCY', 'Emergency')
    ]
    
    # Basic Information
    vehicle_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    vehicle_type = models.ForeignKey(VehicleType, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='INACTIVE')
    
    # Current Position (most recent)
    current_latitude = models.DecimalField(max_digits=17, decimal_places=14, null=True, blank=True)
    current_longitude = models.DecimalField(max_digits=17, decimal_places=14, null=True, blank=True)
    current_altitude = models.FloatField(null=True, blank=True, help_text="Altitude in meters")
    current_heading = models.FloatField(null=True, blank=True, help_text="Heading in degrees (0-360)")
    current_speed = models.FloatField(null=True, blank=True, help_text="Speed in m/s")
    
    # Metadata
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    mission_id = models.CharField(max_length=100, blank=True, null=True)
    last_update = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Display Properties
    custom_color = models.ForeignKey(Color, on_delete=models.SET_NULL, null=True, blank=True)
    custom_icon = models.CharField(max_length=10, blank=True, null=True)
    show_trail = models.BooleanField(default=True)
    trail_length = models.PositiveIntegerField(default=100, help_text="Number of trail points to show")
    
    # Operational Parameters
    max_speed = models.FloatField(null=True, blank=True, help_text="Maximum speed in m/s")
    max_altitude = models.FloatField(null=True, blank=True, help_text="Maximum altitude in meters")
    battery_level = models.FloatField(null=True, blank=True, help_text="Battery level 0-100%")
    
    class Meta:
        ordering = ['-last_update']
        indexes = [
            models.Index(fields=['vehicle_id']),
            models.Index(fields=['status']),
            models.Index(fields=['last_update']),
            models.Index(fields=['current_latitude', 'current_longitude']),
        ]
    
    def __str__(self):
        return f'{self.name} ({self.vehicle_id})'
    
    @property
    def is_active(self):
        """Check if vehicle is currently active"""
        return self.status == 'ACTIVE'
    
    @property
    def position_age_seconds(self):
        """Get age of current position in seconds"""
        if self.last_update:
            return (timezone.now() - self.last_update).total_seconds()
        return None
    
    def get_display_color(self):
        """Get the color to display for this vehicle"""
        if self.custom_color:
            return f"rgb({self.custom_color.red}, {self.custom_color.green}, {self.custom_color.blue})"
        elif self.vehicle_type.default_color:
            color = self.vehicle_type.default_color
            return f"rgb({color.red}, {color.green}, {color.blue})"
        else:
            return "rgb(255, 0, 0)"  # Default red
    
    def get_display_icon(self):
        """Get the icon to display for this vehicle"""
        return self.custom_icon or self.vehicle_type.icon_symbol


class VehiclePosition(models.Model):
    """Historical position data for vehicles"""
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='positions')
    
    # Position Data
    latitude = models.DecimalField(max_digits=17, decimal_places=14)
    longitude = models.DecimalField(max_digits=17, decimal_places=14)
    altitude = models.FloatField(null=True, blank=True, help_text="Altitude in meters")
    
    # Motion Data
    heading = models.FloatField(null=True, blank=True, help_text="Heading in degrees (0-360)")
    speed = models.FloatField(null=True, blank=True, help_text="Speed in m/s")
    vertical_speed = models.FloatField(null=True, blank=True, help_text="Vertical speed in m/s")
    
    # Quality Indicators
    gps_accuracy = models.FloatField(null=True, blank=True, help_text="GPS accuracy in meters")
    satellite_count = models.PositiveIntegerField(null=True, blank=True)
    
    # Sensor Data
    battery_level = models.FloatField(null=True, blank=True, help_text="Battery level 0-100%")
    signal_strength = models.FloatField(null=True, blank=True, help_text="Signal strength in dBm")
    
    # Additional Data
    sensor_data = JSONField(default=dict, blank=True, help_text="Additional sensor readings")
    
    # Timestamps
    timestamp = models.DateTimeField(default=timezone.now)
    received_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['vehicle', '-timestamp']),
            models.Index(fields=['latitude', 'longitude']),
            models.Index(fields=['timestamp']),
        ]
    
    def __str__(self):
        return f'{self.vehicle.name} at ({self.latitude}, {self.longitude}) - {self.timestamp}'


class VehicleGeofence(models.Model):
    """Geofence definitions for vehicle monitoring"""
    GEOFENCE_TYPES = [
        ('INCLUSION', 'Inclusion Zone'),
        ('EXCLUSION', 'Exclusion Zone'),
        ('WARNING', 'Warning Zone'),
        ('LANDING', 'Landing Zone'),
        ('TAKEOFF', 'Takeoff Zone'),
    ]
    
    name = models.CharField(max_length=200)
    geofence_type = models.CharField(max_length=20, choices=GEOFENCE_TYPES)
    vehicles = models.ManyToManyField(Vehicle, blank=True, related_name='geofences')
    
    # Geometry (stored as GeoJSON)
    geometry = models.TextField(help_text="GeoJSON geometry definition")
    
    # Properties
    min_altitude = models.FloatField(null=True, blank=True, help_text="Minimum altitude in meters")
    max_altitude = models.FloatField(null=True, blank=True, help_text="Maximum altitude in meters")
    is_active = models.BooleanField(default=True)
    
    # Metadata
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f'{self.name} ({self.get_geofence_type_display()})'


class VehicleAlert(models.Model):
    """Alerts and notifications for vehicle monitoring"""
    ALERT_TYPES = [
        ('GEOFENCE', 'Geofence Violation'),
        ('LOW_BATTERY', 'Low Battery'),
        ('SIGNAL_LOST', 'Signal Lost'),
        ('SPEED_LIMIT', 'Speed Limit Exceeded'),
        ('ALTITUDE_LIMIT', 'Altitude Limit Exceeded'),
        ('EMERGENCY', 'Emergency'),
        ('MAINTENANCE', 'Maintenance Required'),
        ('CUSTOM', 'Custom Alert'),
    ]
    
    SEVERITY_LEVELS = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('CRITICAL', 'Critical'),
    ]
    
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='alerts')
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPES)
    severity = models.CharField(max_length=10, choices=SEVERITY_LEVELS, default='MEDIUM')
    
    title = models.CharField(max_length=200)
    message = models.TextField()
    
    # Location where alert occurred
    latitude = models.DecimalField(max_digits=17, decimal_places=14, null=True, blank=True)
    longitude = models.DecimalField(max_digits=17, decimal_places=14, null=True, blank=True)
    altitude = models.FloatField(null=True, blank=True)
    
    # Alert Status
    is_acknowledged = models.BooleanField(default=False)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='acknowledged_alerts')
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    # Additional Data
    metadata = JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['vehicle', '-created_at']),
            models.Index(fields=['alert_type']),
            models.Index(fields=['severity']),
            models.Index(fields=['is_acknowledged']),
        ]
    
    def __str__(self):
        return f'{self.vehicle.name}: {self.title} ({self.get_severity_display()})' 


# ===== MISSION PLANNING MODELS =====

class Mission(models.Model):
    """Mission planning for autonomous vehicles"""
    MISSION_TYPES = [
        ('SURVEY', 'Survey'),
        ('PATROL', 'Patrol'),
        ('DATA_CAPTURE', 'Data Capture'),
        ('INSPECTION', 'Inspection'),
        ('MAPPING', 'Mapping'),
        ('CUSTOM', 'Custom'),
    ]
    
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('READY', 'Ready'),
        ('UPLOADED', 'Uploaded to Vehicle'),
        ('ACTIVE', 'Active'),
        ('PAUSED', 'Paused'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]
    
    # Basic Information
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    mission_type = models.CharField(max_length=50, choices=MISSION_TYPES, default='CUSTOM')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    
    # Vehicle Association
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='missions', null=True, blank=True)
    
    # Mission Data (GeoJSON format)
    waypoints = models.JSONField(default=list, help_text="GeoJSON FeatureCollection of waypoints")
    
    # Mission Parameters
    default_altitude = models.FloatField(default=50.0, help_text="Default altitude in meters")
    default_speed = models.FloatField(null=True, blank=True, help_text="Default speed in m/s")
    return_to_home = models.BooleanField(default=True, help_text="Return to home after mission")
    
    # Metadata
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='created_missions')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    uploaded_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['vehicle', '-created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['created_by', '-created_at']),
        ]
        verbose_name = 'Mission'
        verbose_name_plural = 'Missions'
    
    def __str__(self):
        return f'{self.name} ({self.get_status_display()})'
    
    @property
    def num_waypoints(self):
        """Get number of waypoints in mission"""
        if isinstance(self.waypoints, dict) and 'features' in self.waypoints:
            return len(self.waypoints['features'])
        elif isinstance(self.waypoints, list):
            return len(self.waypoints)
        return 0
    
    @property
    def total_distance(self):
        """Calculate total mission distance in meters"""
        # TODO: Implement distance calculation from waypoints
        return 0.0
    
    def to_geojson(self):
        """Convert mission to GeoJSON format"""
        return {
            'type': 'FeatureCollection',
            'properties': {
                'name': self.name,
                'mission_type': self.mission_type,
                'status': self.status,
                'default_altitude': self.default_altitude,
                'default_speed': self.default_speed,
                'return_to_home': self.return_to_home,
            },
            'features': self.waypoints.get('features', []) if isinstance(self.waypoints, dict) else self.waypoints
        }


class MissionWaypoint(models.Model):
    """Individual waypoint in a mission"""
    WAYPOINT_TYPES = [
        ('WAYPOINT', 'Waypoint'),
        ('TAKEOFF', 'Takeoff'),
        ('LAND', 'Land'),
        ('RETURN_TO_LAUNCH', 'Return to Launch'),
        ('LOITER', 'Loiter'),
        ('LOITER_TIME', 'Loiter Time'),
        ('LOITER_TURNS', 'Loiter Turns'),
        ('LOITER_UNLIM', 'Loiter Unlimited'),
    ]
    
    mission = models.ForeignKey(Mission, on_delete=models.CASCADE, related_name='waypoint_items')
    
    # Sequence number (order in mission)
    sequence = models.PositiveIntegerField()
    
    # Position
    latitude = models.DecimalField(max_digits=17, decimal_places=14)
    longitude = models.DecimalField(max_digits=17, decimal_places=14)
    altitude = models.FloatField(help_text="Altitude in meters")
    
    # Waypoint Type
    waypoint_type = models.CharField(max_length=50, choices=WAYPOINT_TYPES, default='WAYPOINT')
    
    # MAVLink Command Parameters
    command = models.IntegerField(default=16, help_text="MAVLink command ID (16=WAYPOINT)")
    param1 = models.FloatField(default=0.0, help_text="MAVLink parameter 1")
    param2 = models.FloatField(default=0.0, help_text="MAVLink parameter 2")
    param3 = models.FloatField(default=0.0, help_text="MAVLink parameter 3")
    param4 = models.FloatField(default=0.0, help_text="MAVLink parameter 4")
    
    # Additional Parameters
    speed = models.FloatField(null=True, blank=True, help_text="Speed at this waypoint (m/s)")
    yaw = models.FloatField(null=True, blank=True, help_text="Yaw angle at waypoint (degrees)")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['mission', 'sequence']
        unique_together = ('mission', 'sequence')
        indexes = [
            models.Index(fields=['mission', 'sequence']),
        ]
        verbose_name = 'Mission Waypoint'
        verbose_name_plural = 'Mission Waypoints'
    
    def __str__(self):
        return f'{self.mission.name} - WP{self.sequence} ({self.latitude:.4f}, {self.longitude:.4f})'
    
    def to_geojson(self):
        """Convert waypoint to GeoJSON Feature"""
        return {
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [float(self.longitude), float(self.latitude), float(self.altitude)]
            },
            'properties': {
                'id': self.id,  # Database ID for deletion
                'sequence': self.sequence,
                'waypoint_type': self.waypoint_type,
                'command': self.command,
                'param1': self.param1,
                'param2': self.param2,
                'param3': self.param3,
                'param4': self.param4,
                'speed': self.speed,
                'yaw': self.yaw,
            }
        }


# ===== MASK2FORMER TRAINING MODELS =====

class TrainingDataset(models.Model):
    """Metadata for organizing labels into training datasets.

    The original purpose was Mask2Former retraining; ``kind`` widens that so
    the same table also drives rock Mask R-CNN retraining (4-channel-stack
    .npy tiles emitted by the rock label editor — see
    `deepgis_xr.apps.web.views.rock_label`).
    """
    KIND_CHOICES = [
        ('mask2former', 'Mask2Former (semantic)'),
        ('rock_maskrcnn', 'Rock Mask R-CNN (400×400 tiles)'),
    ]

    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, default='mask2former')
    # When num_annotations >= min_tiles_for_training and status=='draft',
    # the rock_label save endpoint flips status to 'ready' and writes a
    # RETRAIN_READY sentinel into the corpus directory.
    min_tiles_for_training = models.PositiveIntegerField(default=50)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    status = models.CharField(max_length=20, choices=[
        ('draft', 'Draft'),
        ('ready', 'Ready for Training'),
        ('training', 'Training in Progress'),
        ('completed', 'Training Completed'),
    ], default='draft')
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Training Dataset'
        verbose_name_plural = 'Training Datasets'
    
    def __str__(self):
        return self.name
    
    @property
    def num_annotations(self):
        """Get count of annotations in this dataset"""
        return self.training_labels.count()
    
    @property
    def num_images(self):
        """Get count of unique images in this dataset"""
        return self.training_labels.values('image_label__image').distinct().count()


class TrainingLabel(models.Model):
    """Links existing ImageLabels to training datasets"""
    dataset = models.ForeignKey(TrainingDataset, on_delete=models.CASCADE, related_name='training_labels')
    image_label = models.ForeignKey(ImageLabel, on_delete=models.CASCADE, related_name='training_datasets')
    
    # Metadata
    source_prediction_id = models.CharField(max_length=200, blank=True, null=True, 
                                          help_text="Original Mask2Former session_id")
    corrections_made = models.JSONField(default=dict, blank=True, 
                                       help_text="Track what corrections were made")
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('dataset', 'image_label')
        ordering = ['-created_at']
        verbose_name = 'Training Label'
        verbose_name_plural = 'Training Labels'
        indexes = [
            models.Index(fields=['dataset', '-created_at']),
            models.Index(fields=['source_prediction_id']),
        ]
    
    def __str__(self):
        return f"{self.dataset.name} - {self.image_label}"


class ModelVersion(models.Model):
    """Trained model versions"""
    name = models.CharField(max_length=200, help_text="Model name (e.g., 'Custom Mask2Former')")
    version = models.CharField(max_length=50, help_text="Version string (e.g., '1.0', '2.1')")
    description = models.TextField(blank=True)
    
    training_dataset = models.ForeignKey(TrainingDataset, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='model_versions')
    base_model = models.CharField(max_length=100, default='mask2former_coco',
                                help_text="Base model used for fine-tuning")
    
    model_path = models.CharField(max_length=500, help_text="Path to trained model .pth file")
    config_path = models.CharField(max_length=500, blank=True, help_text="Path to model config file")
    
    # Training metrics
    training_loss = models.FloatField(null=True, blank=True)
    validation_loss = models.FloatField(null=True, blank=True)
    mAP_score = models.FloatField(null=True, blank=True, help_text="Mean Average Precision")
    
    status = models.CharField(max_length=20, choices=[
        ('training', 'Training'),
        ('completed', 'Completed'),
        ('deployed', 'Deployed'),
        ('archived', 'Archived'),
    ], default='training')
    
    trained_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='trained_models')
    trained_at = models.DateTimeField(auto_now_add=True)
    deployed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ('name', 'version')
        ordering = ['-trained_at']
        verbose_name = 'Model Version'
        verbose_name_plural = 'Model Versions'
        indexes = [
            models.Index(fields=['name', 'version']),
            models.Index(fields=['status']),
            models.Index(fields=['-trained_at']),
        ]
    
    def __str__(self):
        return f"{self.name} v{self.version}"
    
    @property
    def is_deployed(self):
        """Check if this model version is currently deployed"""
        return self.status == 'deployed'