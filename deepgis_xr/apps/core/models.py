from __future__ import unicode_literals

from datetime import datetime
from django.contrib.auth.models import User
from django.db import models
from django.core.validators import MaxValueValidator
import random
from django.db.models import JSONField
from django.conf import settings
from django.utils.translation import gettext_lazy as _


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