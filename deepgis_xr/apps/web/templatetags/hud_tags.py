"""Template tags for the shared HUD (templates/web/hud/)."""
from django import template
from django.utils.html import json_script

from ..views.pilot import layer_catalog

register = template.Library()


@register.simple_tag
def hud_layer_catalog(body):
    """The Layers panel's data-layer catalog, as the JSON script element #hudLayerCatalog."""
    return json_script(layer_catalog(body), "hudLayerCatalog")


@register.simple_tag
def hud_has_layers(body):
    """Whether the Layers panel has anything to offer on this body."""
    return body == "earth" or bool(layer_catalog(body)["kinds"])
