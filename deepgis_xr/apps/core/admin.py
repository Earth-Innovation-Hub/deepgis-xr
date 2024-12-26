from django.contrib import admin
from django import forms
from django.utils.html import format_html

from .models import (
    Image, ImageLabel, ImageSourceType, CategoryType, ImageFilter,
    Color, TiledGISLabel, RasterImage, CategoryLabel, Labeler
)

admin.site.register(Image)
admin.site.register(ImageSourceType)
admin.site.register(CategoryType)
admin.site.register(ImageFilter)
admin.site.register(Color)
admin.site.register(TiledGISLabel)
admin.site.register(RasterImage)

class CategoryLabelInline(admin.TabularInline):
    model = CategoryLabel
    fields = ('category', 'label_shapes')
    readonly_fields = ('category', 'label_shapes')
    extra = 0
    show_change_link = True
    can_delete = False
    ordering = ['category']

class ImageLabelInline(admin.TabularInline):
    model = ImageLabel
    fields = ('image', 'window', 'pub_date')
    readonly_fields = ('image', 'window', 'pub_date')
    extra = 0
    show_change_link = True
    can_delete = False
    ordering = ['pub_date']

@admin.register(Labeler)
class LabelerAdmin(admin.ModelAdmin):
    fieldsets = [
        ('User', {'fields': ['user']}),
        ('Label Stats', {'fields': ['number_labeled']})
    ]
    readonly_fields = ('number_labeled',)
    inlines = [ImageLabelInline]

    def number_labeled(self, obj):
        return ImageLabel.objects.filter(labeler=obj).count()

class ImageLabelAdminForm(forms.ModelForm):
    class Meta:
        fields = "__all__"
        model = ImageLabel

@admin.register(CategoryLabel)
class CategoryLabelAdmin(admin.ModelAdmin):
    list_display = ('get_category', 'get_label_shapes', 'get_parent_label')
    readonly_fields = ('overlay_image',)

    def get_category(self, obj):
        return obj.category.category_name if obj.category else ''
    get_category.short_description = 'Category'

    def get_label_shapes(self, obj):
        return str(obj.label_shapes)[:50] + '...' if obj.label_shapes else ''
    get_label_shapes.short_description = 'Label Shapes'

    def get_parent_label(self, obj):
        return str(obj.parent_label)
    get_parent_label.short_description = 'Parent Label'

    def overlay_image(self, obj):
        return format_html('<img src="/api/v1/category-labels/{}/overlay" alt="Rendered Label">', obj.id)

@admin.register(ImageLabel)
class ImageLabelAdmin(admin.ModelAdmin):
    list_display = ('get_image', 'get_window', 'get_labeler', 'get_time_taken', 'get_pub_date')
    readonly_fields = ('overlay_image',)
    inlines = [CategoryLabelInline]

    def get_image(self, obj):
        return str(obj.image)
    get_image.short_description = 'Image'

    def get_window(self, obj):
        return str(obj.window)
    get_window.short_description = 'Window'

    def get_labeler(self, obj):
        return str(obj.labeler)
    get_labeler.short_description = 'Labeler'

    def get_time_taken(self, obj):
        return obj.time_taken if obj.time_taken else ''
    get_time_taken.short_description = 'Time Taken'

    def get_pub_date(self, obj):
        return obj.pub_date
    get_pub_date.short_description = 'Publication Date'

    def overlay_image(self, obj):
        return format_html('<img src="/api/v1/image-labels/{}/overlay" alt="Rendered Label">', obj.id)
