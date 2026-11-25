"""Explicit, local-checkpoint photo detection for the optional workbench."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError


MAX_IMAGE_BYTES = 10_000_000
MAX_IMAGE_PIXELS = 20_000_000
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
CONFIDENCE_THRESHOLD = 0.25


class InferenceError(ValueError):
    """An invalid upload, model configuration, or inference result."""


def _decode_image(filename: str, contents: bytes) -> Image.Image:
    if Path(filename).suffix.lower() not in IMAGE_SUFFIXES:
        raise InferenceError("Upload a JPEG, PNG, or WebP image.")
    if not contents:
        raise InferenceError("The uploaded image is empty.")
    if len(contents) > MAX_IMAGE_BYTES:
        raise InferenceError("The uploaded image exceeds the 10 MB limit.")

    try:
        with Image.open(BytesIO(contents)) as image:
            if image.format not in IMAGE_FORMATS:
                raise InferenceError("Upload a JPEG, PNG, or WebP image.")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise InferenceError("The uploaded image exceeds the 20 MP limit.")
            image.verify()

        with Image.open(BytesIO(contents)) as image:
            if image.format not in IMAGE_FORMATS:
                raise InferenceError("Upload a JPEG, PNG, or WebP image.")
            image.load()
            return image.convert("RGB")
    except InferenceError:
        raise
    except (Image.DecompressionBombError, OSError, UnidentifiedImageError, ValueError) as error:
        raise InferenceError("The uploaded file could not be decoded as an image.") from error


def _as_list(value: Any) -> list[Any]:
    if hasattr(value, "cpu"):
        value = value.cpu()
    return value.tolist()


def _class_names(names: Any) -> dict[int, str]:
    if isinstance(names, dict):
        items = names.items()
    elif isinstance(names, (list, tuple)):
        items = enumerate(names)
    else:
        raise InferenceError("The local checkpoint has no detection class metadata.")

    try:
        result = {int(class_id): str(name) for class_id, name in items}
    except (TypeError, ValueError) as error:
        raise InferenceError("The local checkpoint has invalid detection class metadata.") from error
    if not result or any(not name for name in result.values()):
        raise InferenceError("The local checkpoint has no detection class metadata.")
    return result


def infer_photo(
    *,
    filename: str,
    contents: bytes,
    model_path: str | Path,
    predictor_factory: Callable[[str], Any] | None = None,
) -> dict[str, object]:
    """Run one bounded CPU detection using an explicitly configured local model."""
    image = _decode_image(filename, contents)
    checkpoint = Path(model_path).expanduser()
    if not checkpoint.is_file():
        raise InferenceError(
            "The configured local model checkpoint is missing; mount a trusted detection .pt file and set MGTS_MODEL_PATH."
        )
    checkpoint = checkpoint.resolve()

    if predictor_factory is None:
        try:
            from ultralytics import YOLO
        except ImportError as error:
            raise InferenceError(
                "Photo inference requires the optional CPU dependency; install the `inference` extra."
            ) from error
        predictor_factory = YOLO

    try:
        model = predictor_factory(str(checkpoint))
        task = getattr(model, "task", None)
        if task != "detect":
            raise InferenceError("The configured checkpoint must be a detection checkpoint.")
        names = _class_names(getattr(model, "names", None))
        prediction = model.predict(
            source=image,
            device="cpu",
            imgsz=640,
            conf=CONFIDENCE_THRESHOLD,
            max_det=100,
            save=False,
            verbose=False,
        )
        boxes = prediction[0].boxes if prediction else None
        if boxes is None:
            raise InferenceError("The configured detector returned no detection results.")

        coordinates = _as_list(boxes.xyxy)
        confidences = _as_list(boxes.conf)
        class_ids = _as_list(boxes.cls)
        if not (len(coordinates) == len(confidences) == len(class_ids)):
            raise InferenceError("The configured detector returned inconsistent detection results.")

        detections: list[dict[str, object]] = []
        for raw_box, raw_confidence, raw_class_id in zip(coordinates, confidences, class_ids):
            box = [float(coordinate) for coordinate in raw_box]
            confidence = float(raw_confidence)
            numeric_class_id = float(raw_class_id)
            if (
                len(box) != 4
                or not all(math.isfinite(coordinate) for coordinate in box)
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
                or not math.isfinite(numeric_class_id)
                or not numeric_class_id.is_integer()
            ):
                raise InferenceError("The configured detector returned invalid detection values.")
            class_id = int(numeric_class_id)
            if class_id not in names:
                raise InferenceError("The configured detector returned a class missing from checkpoint metadata.")
            detections.append(
                {
                    "class_id": class_id,
                    "class": names[class_id],
                    "confidence": confidence,
                    "bbox_xyxy_px": box,
                }
            )
    except InferenceError:
        raise
    except Exception as error:
        raise InferenceError(
            "Photo inference failed while loading the configured local checkpoint or running CPU detection."
        ) from error

    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    return {
        "model_sha256": digest,
        "task": task,
        "class_names": [names[class_id] for class_id in sorted(names)],
        "image": {"filename": Path(filename).name, "width": image.width, "height": image.height},
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "detections": detections,
    }
