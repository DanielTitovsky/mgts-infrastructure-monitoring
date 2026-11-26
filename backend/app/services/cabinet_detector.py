"""Offline cabinet localization; object boxes do not assess condition or cabinet subtype."""
from __future__ import annotations

import hashlib
import logging
import math
import os
from functools import lru_cache
from pathlib import Path

from app.services.cv_logic import Detection

# Pinned IDEA-Research/grounding-dino-tiny, revision a2bb814dd30d776dcf7e30523b00659f4f141c71.
WEIGHTS_SHA256 = "1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3"
CAPTION = (
    "an electrical cabinet. an electrical distribution cabinet. an electrical panel. "
    "an electrical switchboard enclosure. a metal electrical control cabinet."
)
BOX_THRESHOLD = 0.25
TEXT_THRESHOLD = 0.20
NMS_IOU_THRESHOLD = 0.50
MAX_DETECTIONS = 10


@lru_cache(maxsize=1)
def _load_detector(path: Path):
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    with (path / "model.safetensors").open("rb") as weights:
        if hashlib.file_digest(weights, "sha256").hexdigest() != WEIGHTS_SHA256:
            raise RuntimeError("Cabinet detector weights do not match the pinned Grounding DINO checkpoint")
    processor = AutoProcessor.from_pretrained(path, local_files_only=True, use_fast=False)
    processor.image_processor.size = {"shortest_edge": 512, "longest_edge": 768}
    model = AutoModelForZeroShotObjectDetection.from_pretrained(
        path, local_files_only=True, use_safetensors=True
    ).to("cpu").eval()
    logging.getLogger(__name__).info("Loaded verified Grounding DINO cabinet detector from %s", path)
    return processor, model


def _iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0


def cabinet_boxes(scores, labels, boxes, *, width: int, height: int) -> list[Detection]:
    """Map actual XYXY pixel predictions to normalized object-only detections after NMS."""
    candidates = []
    for score, label, coords in zip(scores, labels, boxes, strict=True):
        score = float(score)
        if not BOX_THRESHOLD <= score <= 1 or not isinstance(label, str) or not label.strip():
            continue
        x1, y1, x2, y2 = map(float, coords)
        if not all(map(math.isfinite, (x1, y1, x2, y2))):
            continue
        bbox = tuple(min(1.0, max(0.0, v)) for v in (x1 / width, y1 / height, x2 / width, y2 / height))
        if bbox[2] > bbox[0] and bbox[3] > bbox[1]:
            candidates.append((-score, label, bbox))

    kept = []
    for neg_score, _, bbox in sorted(candidates):
        if all(_iou(bbox, previous.bbox) <= NMS_IOU_THRESHOLD for previous in kept):
            kept.append(Detection("cabinet", round(-neg_score, 6), bbox))
            if len(kept) == MAX_DETECTIONS:
                break
    return kept


def detect_cabinets(frame) -> list[Detection]:
    """Infer on the very same oriented BGR frame that the worker will annotate."""
    import torch
    from PIL import Image

    processor, model = _load_detector(Path(os.environ.get("CABINET_DETECTOR_PATH", "/models/cabinet-detector")))
    image = Image.fromarray(frame[:, :, ::-1])
    inputs = processor(images=image, text=CAPTION, return_tensors="pt")
    with torch.inference_mode():
        outputs = model(**inputs)
    result = processor.post_process_grounded_object_detection(
        outputs, inputs.input_ids, threshold=BOX_THRESHOLD, text_threshold=TEXT_THRESHOLD,
        target_sizes=[(image.height, image.width)],
    )[0]
    if result.get("text_labels") is None:
        raise RuntimeError("Cabinet detector did not return grounded text labels")
    return cabinet_boxes(result["scores"], result["text_labels"], result["boxes"],
                         width=image.width, height=image.height)


def draw_cabinets(frame, detections: list[Detection]) -> None:
    import cv2

    height, width = frame.shape[:2]
    scale = max(0.5, min(height, width) / 640)
    thickness = max(1, round(2 * scale))
    for det in detections:
        x1, y1, x2, y2 = (min(size - 1, round(v * size)) for v, size in zip(det.bbox, (width, height, width, height)))
        cv2.rectangle(frame, (x1, y1), (x2, y2), (52, 200, 112), thickness)
        label = f"Cabinet {det.confidence:.0%}"
        (w, h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
        left = min(x1, max(0, width - w - 6))
        bottom = min(height - baseline - 3, max(y1 - 4, h + 3))
        cv2.rectangle(frame, (left, bottom - h - 3), (left + w + 5, bottom + baseline + 2), (22, 60, 35), -1)
        cv2.putText(frame, label, (left + 2, bottom), cv2.FONT_HERSHEY_SIMPLEX, scale,
                    (255, 255, 255), thickness, cv2.LINE_AA)
