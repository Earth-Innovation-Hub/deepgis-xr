"""
model.py — Mask R-CNN rock detector factory.

Derived from Zhiang Chen's original recipe in
Zhiang_mask_rcnn/mask_rcnn_pytorch/model.py (Dec 2019 – Feb 2020), which every
one of our `.param` checkpoints under /mnt/22tb-hdd/maskrcnn/terrestrial/ was
produced with.

The `.param` files are `torch.save(state_dict)` pickles (verified by magic
bytes); despite the extension there is no MXNet involvement.  They are all
torchvision `maskrcnn_resnet50_fpn` instance-segmentation networks with:

  * `roi_heads.box_predictor`   replaced with a 2-class FastRCNNPredictor
    (background + rock).
  * `roi_heads.mask_predictor`  replaced with a 2-class MaskRCNNPredictor.
  * `rpn.anchor_generator`      rescaled to rock-scale anchors
    (16/32/64/128/256) × (0.5, 1.0, 2.0).
  * `backbone.body.conv1`       replaced with an N-channel Conv2d that matches
    the training modality (RGB=3, DEM=1 or 3, RGB+DEM=4 or 6, 5-band
    Micasense=5, 8-channel multispectral=8).

We *auto-detect* `input_channel` at load time by inspecting the shape of
`backbone.body.conv1.weight` in the checkpoint's state_dict, so the caller
never has to guess from filenames.
"""

from __future__ import annotations

from typing import Iterable, Optional

import torch
import torch.nn as nn
import torchvision
from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
from torchvision.models.detection.mask_rcnn import MaskRCNNPredictor
from torchvision.models.detection.rpn import AnchorGenerator


ROCK_ANCHOR_SIZES = ((16,), (32,), (64,), (128,), (256,))
ROCK_ASPECT_RATIOS = ((0.5, 1.0, 2.0),) * 5
ROCK_DETECTIONS_PER_IMG = 256


def build_rock_maskrcnn(
    num_classes: int = 2,
    input_channel: int = 3,
    image_mean: Optional[Iterable[float]] = None,
    image_std: Optional[Iterable[float]] = None,
    pretrained: bool = False,
) -> nn.Module:
    """Construct a rock-tuned torchvision Mask R-CNN.

    ``pretrained=False`` is the serving default: we always overwrite the
    random weights with our trained checkpoint via ``load_state_dict``.
    Set ``pretrained=True`` only when retraining from COCO.
    """
    weights = None
    weights_backbone = None
    if pretrained:
        weights = (
            torchvision.models.detection.MaskRCNN_ResNet50_FPN_Weights.DEFAULT
        )

    model = torchvision.models.detection.maskrcnn_resnet50_fpn(
        weights=weights,
        weights_backbone=weights_backbone,
    )

    in_features = model.roi_heads.box_predictor.cls_score.in_features
    model.roi_heads.box_predictor = FastRCNNPredictor(in_features, num_classes)

    model.rpn.anchor_generator = AnchorGenerator(
        sizes=ROCK_ANCHOR_SIZES,
        aspect_ratios=ROCK_ASPECT_RATIOS,
    )

    in_features_mask = model.roi_heads.mask_predictor.conv5_mask.in_channels
    model.roi_heads.mask_predictor = MaskRCNNPredictor(
        in_features_mask, 256, num_classes
    )

    model.roi_heads.detections_per_img = ROCK_DETECTIONS_PER_IMG

    if input_channel != 3:
        model.backbone.body.conv1 = nn.Conv2d(
            input_channel, 64,
            kernel_size=(7, 7), stride=(2, 2), padding=(3, 3), bias=False,
        )

    # torchvision's GeneralizedRCNNTransform normalizes by a fixed image_mean /
    # image_std whose length must match the input channel count.  The default
    # (ImageNet 3-ch) crashes as soon as we swap conv1 to N channels, so we
    # pad with sensible neutral values (0.5 / 0.25) for the extra channels.
    # Callers can override via ``image_mean`` / ``image_std`` when the true
    # training statistics are known.
    if image_mean is None:
        base_mean = [0.485, 0.456, 0.406]
        image_mean = base_mean + [0.5] * max(0, input_channel - 3)
        image_mean = image_mean[:input_channel] if input_channel >= 1 else base_mean
    if image_std is None:
        base_std = [0.229, 0.224, 0.225]
        image_std = base_std + [0.25] * max(0, input_channel - 3)
        image_std = image_std[:input_channel] if input_channel >= 1 else base_std

    model.transform.image_mean = list(image_mean)
    model.transform.image_std = list(image_std)

    return model


def infer_input_channel(state_dict: dict) -> int:
    """Read input channel count from the conv1 weight shape."""
    key_candidates = (
        "backbone.body.conv1.weight",
        "module.backbone.body.conv1.weight",
    )
    for k in key_candidates:
        if k in state_dict:
            return int(state_dict[k].shape[1])
    raise KeyError(
        "Could not find backbone.body.conv1.weight in state_dict; "
        "is this really a rock Mask R-CNN checkpoint?"
    )


def infer_num_classes(state_dict: dict) -> int:
    """Read num_classes from the box predictor weight."""
    for k in (
        "roi_heads.box_predictor.cls_score.weight",
        "module.roi_heads.box_predictor.cls_score.weight",
    ):
        if k in state_dict:
            return int(state_dict[k].shape[0])
    return 2


def load_from_checkpoint(
    checkpoint_path: str,
    device: torch.device,
    image_mean: Optional[Iterable[float]] = None,
    image_std: Optional[Iterable[float]] = None,
) -> tuple[nn.Module, dict]:
    """Load a `.param` checkpoint and build a matching model.

    Returns ``(model, meta)`` where ``meta`` carries the auto-detected
    ``input_channel`` and ``num_classes``.
    """
    state_dict = torch.load(checkpoint_path, map_location="cpu")
    if isinstance(state_dict, dict) and "model" in state_dict and "state_dict" not in state_dict:
        state_dict = state_dict["model"]
    if isinstance(state_dict, dict) and "state_dict" in state_dict:
        state_dict = state_dict["state_dict"]

    input_channel = infer_input_channel(state_dict)
    num_classes = infer_num_classes(state_dict)

    model = build_rock_maskrcnn(
        num_classes=num_classes,
        input_channel=input_channel,
        image_mean=image_mean,
        image_std=image_std,
        pretrained=False,
    )

    stripped = {k[len("module."):] if k.startswith("module.") else k: v
                for k, v in state_dict.items()}
    missing, unexpected = model.load_state_dict(stripped, strict=False)
    model.eval().to(device)

    return model, {
        "input_channel": input_channel,
        "num_classes": num_classes,
        "missing_keys": list(missing),
        "unexpected_keys": list(unexpected),
    }
