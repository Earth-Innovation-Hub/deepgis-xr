"""
Simple page renderers for the web app.

Moved out of the legacy `views.py` monolith in the Tier B refactor.
These are the thin template wrappers routed by `apps/web/urls.py`
(`/`, `/label/`, `/label/3d/`, `/results/`, …).

Historical note: an older class-based implementation (IndexView,
LabelView, etc.) lived above the function renderers and its aliases
(`index = IndexView.as_view()` …) were immediately overridden by the
function-style handlers that follow. The class definitions are kept
here for API parity (some callers or subclasses may still import them)
but the dead `index = IndexView.as_view()` aliases have been removed —
the function renderers are what `urls.py` actually binds.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.views.generic import TemplateView

from deepgis_xr.apps.core.models import CategoryType, Image


class BaseView(LoginRequiredMixin, TemplateView):
    """Base class for all web views"""
    
    def get_context_data(self, **kwargs):
        """Get base context data"""
        context = super().get_context_data(**kwargs)
        context['categories'] = {
            cat.category_name: str(cat.color) 
            for cat in CategoryType.objects.all()
        }
        return context


class IndexView(BaseView):
    """Main landing page"""
    template_name = 'web/index.html'


class LabelView(BaseView):
    """Image labeling interface"""
    template_name = 'web/label.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        latest_images = Image.objects.all()
        
        if latest_images:
            context.update({
                'latest_image_list': latest_images,
                'selected_image': latest_images[0],
            })
        
        return context


class Label3DView(BaseView):
    """3D model labeling interface"""
    template_name = 'web/label_3d.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context


class ViewLabelView(BaseView):
    """View existing labels"""
    template_name = 'web/view_label.html'


class ResultsView(BaseView):
    """View labeling results"""
    template_name = 'web/results.html'


def simple_render(request, template_name):
    """Render a simple template without additional context."""
    return render(request, template_name)


def index(request):
    return simple_render(request, 'web/index.html')


def label(request):
    return simple_render(request, 'web/label.html')


def stl_viewer(request):
    """
    Renders the modular Three.js STL viewer page.
    This is a cleaner reimplementation of the 3D model viewer functionality.
    """
    return simple_render(request, 'web/stl_viewer.html')


def label_3d(request):
    return simple_render(request, 'web/label_3d.html')


def label_3d_dev(request):
    return simple_render(request, 'web/label_3d_dev.html')


def view_label(request):
    return simple_render(request, 'web/view_label.html')


def results(request):
    return simple_render(request, 'web/results.html')
