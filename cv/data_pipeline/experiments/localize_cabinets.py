#!/usr/bin/env python3
"""Run pinned, zero-shot cabinet/board localization on the prepared MGTS photos.

The output contains detector predictions, never ground-truth annotations.  The
model weights are public `IDEA-Research/grounding-dino-tiny` at the immutable
Hugging Face revision below (Apache-2.0; the model card and upstream license
are recorded in the output).  No model weights or source images are written to
this repository.

Run with the already-installed CPU torch from the data-pipeline venv and an
isolated uv script environment for Transformers/Pillow, for example:

    PYTHONPATH="$PWD/cv/data_pipeline/.venv/lib/python3.14/site-packages" \
      uv run --isolated --python 3.14 --with transformers==5.1.0 \
      --with pillow==12.1.0 python cv/data_pipeline/experiments/localize_cabinets.py \
      --model-path /tmp/mgts-grounding-dino-tiny \
      --manifest /tmp/mgts-final-materials/prepared/final-materials.json \
      --dataset-root /tmp/mgts-final-materials/prepared \
      --output /tmp/mgts-final-materials/cabinet-boxes.json

For a pre-downloaded snapshot use `--model-path /path/to/snapshot`; otherwise
Transformers downloads the pinned public model revision into its normal cache.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any, Iterable, Sequence

from PIL import Image

MODEL_ID = "IDEA-Research/grounding-dino-tiny"
MODEL_REVISION = "a2bb814dd30d776dcf7e30523b00659f4f141c71"
MODEL_WEIGHTS_SHA256 = "1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3"
MODEL_LICENSE = "Apache-2.0"
MODEL_CARD_URL = "https://huggingface.co/IDEA-Research/grounding-dino-tiny"
UPSTREAM_LICENSE_URL = "https://github.com/IDEA-Research/GroundingDINO/blob/main/LICENSE"
DEFAULT_MANIFEST = Path("/tmp/mgts-final-materials/prepared/final-materials.json")
DEFAULT_DATASET_ROOT = Path("/tmp/mgts-final-materials/prepared")
DEFAULT_OUTPUT = Path("/tmp/mgts-final-materials/cabinet-boxes.json")
EXPECTED_SAMPLE_COUNT = 62
BOX_THRESHOLD = 0.25
TEXT_THRESHOLD = 0.20
NMS_IOU_THRESHOLD = 0.50
MAX_DETECTIONS_PER_IMAGE = 10
IMAGE_SIZE = {"shortest_edge": 512, "longest_edge": 768}
CAPTION = (
    "an electrical cabinet. "
    "an electrical distribution cabinet. "
    "an electrical panel. "
    "an electrical switchboard enclosure. "
    "a metal electrical control cabinet."
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_local_model_path(model_path: str | Path) -> Path:
    weights = Path(model_path) / "model.safetensors"
    if not weights.is_file() or _sha256_file(weights) != MODEL_WEIGHTS_SHA256:
        raise ValueError("local model path must contain the pinned Grounding DINO safetensors checkpoint")
    return weights


def load_verified_manifest(
    manifest_path: Path,
    dataset_root: Path,
    *,
    expected_samples: int | None = EXPECTED_SAMPLE_COUNT,
) -> tuple[dict[str, Any], str, list[tuple[dict[str, Any], Path]]]:
    """Read the exact manifest and fail closed on unsafe/stale image references."""
    root = dataset_root.resolve(strict=True)
    manifest = manifest_path.resolve(strict=True)
    if not manifest.is_file() or not manifest.is_relative_to(root):
        raise ValueError("manifest must be a file within the dataset root")
    manifest_bytes = manifest.read_bytes()
    document = json.loads(manifest_bytes)
    samples = document.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("manifest must contain a non-empty samples array")
    if expected_samples is not None and len(samples) != expected_samples:
        raise ValueError(f"expected {expected_samples} manifest samples, found {len(samples)}")

    verified: list[tuple[dict[str, Any], Path]] = []
    seen_paths: set[str] = set()
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ValueError(f"manifest sample {index} is not an object")
        relative = sample.get("image_path")
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise ValueError(f"manifest sample {index} has an invalid image_path")
        relative_path = PurePosixPath(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts or relative in seen_paths:
            raise ValueError(f"manifest sample {index} has an unsafe or duplicate image_path")
        seen_paths.add(relative)
        expected_hash = sample.get("sha256")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise ValueError(f"manifest sample {index} has no SHA-256")
        try:
            int(expected_hash, 16)
        except ValueError as error:
            raise ValueError(f"manifest sample {index} has an invalid SHA-256") from error
        width, height = sample.get("width"), sample.get("height")
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (width, height)):
            raise ValueError(f"manifest sample {index} has invalid dimensions")
        image_path = (root / Path(*relative_path.parts)).resolve(strict=True)
        if not image_path.is_file() or not image_path.is_relative_to(root):
            raise ValueError(f"manifest sample {index} image escapes the dataset root")
        if _sha256(image_path.read_bytes()) != expected_hash:
            raise ValueError(f"manifest sample {index} image SHA-256 mismatch: {relative}")
        try:
            with Image.open(image_path) as image:
                actual_size = image.size
                image.verify()
        except OSError as error:
            raise ValueError(f"manifest sample {index} image is invalid: {relative}") from error
        if actual_size != (width, height):
            raise ValueError(f"manifest sample {index} image dimensions mismatch: {relative}")
        verified.append((sample, image_path))
    return document, _sha256(manifest_bytes), verified


def _intersection_over_union(a: Sequence[float], b: Sequence[float]) -> float:
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def detections_to_boxes(
    scores: Iterable[Any],
    labels: Iterable[Any],
    boxes: Iterable[Iterable[Any]],
    *,
    width: int,
    height: int,
    threshold: float = BOX_THRESHOLD,
    iou_threshold: float = NMS_IOU_THRESHOLD,
    max_detections: int = MAX_DETECTIONS_PER_IMAGE,
) -> list[dict[str, Any]]:
    """Validate, clamp, and class-agnostically NMS real detector outputs."""
    scored = list(scores)
    named = list(labels)
    coordinates = [list(box) for box in boxes]
    if not (len(scored) == len(named) == len(coordinates)):
        raise ValueError("detector returned mismatched score/label/box arrays")
    if not 0.0 <= threshold <= 1.0 or not 0.0 <= iou_threshold <= 1.0 or max_detections <= 0:
        raise ValueError("invalid filtering parameters")

    candidates = []
    for score_value, label_value, box_value in zip(scored, named, coordinates, strict=True):
        score = float(score_value)
        if not math.isfinite(score) or score < threshold or score > 1.0:
            continue
        if len(box_value) != 4:
            raise ValueError("detector returned a box that is not XYXY")
        x1, y1, x2, y2 = (float(value) for value in box_value)
        if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
            continue
        clipped = [
            min(float(width), max(0.0, x1)),
            min(float(height), max(0.0, y1)),
            min(float(width), max(0.0, x2)),
            min(float(height), max(0.0, y2)),
        ]
        if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
            continue
        label = str(label_value).strip()
        if not label:
            continue
        candidates.append((score, label, clipped))

    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    kept: list[tuple[float, str, list[float]]] = []
    for candidate in candidates:
        if any(_intersection_over_union(candidate[2], prior[2]) > iou_threshold for prior in kept):
            continue
        kept.append(candidate)
        if len(kept) == max_detections:
            break
    return [
        {"label": label, "score": round(score, 6), "xyxy": [round(value, 2) for value in box]}
        for score, label, box in kept
    ]


def make_sample_result(
    sample: dict[str, Any],
    detections: dict[str, Any],
    *,
    threshold: float = BOX_THRESHOLD,
    max_detections: int = MAX_DETECTIONS_PER_IMAGE,
) -> dict[str, Any]:
    """Build a prediction record; an empty detector result stays explicitly negative."""
    boxes = detections_to_boxes(
        detections["scores"],
        detections["labels"],
        detections["boxes"],
        width=sample["width"],
        height=sample["height"],
        threshold=threshold,
        max_detections=max_detections,
    )
    return {
        "sha256": sample["sha256"],
        "image_path": sample["image_path"],
        "width": sample["width"],
        "height": sample["height"],
        "detection_status": "detected" if boxes else "not_detected",
        "boxes": boxes,
    }


def _load_detector(model_path: str | None, device: str):
    try:
        import torch
        import transformers
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
    except ImportError as error:
        raise RuntimeError(
            "inference dependencies are unavailable; use an isolated uv environment with "
            "Transformers 5.1.0 and expose the existing CPU Torch site-packages via PYTHONPATH"
        ) from error

    reference = model_path or MODEL_ID
    if model_path:
        _verify_local_model_path(model_path)
        kwargs = {"local_files_only": True, "use_safetensors": True}
    else:
        kwargs = {"revision": MODEL_REVISION, "use_safetensors": True}
    processor_kwargs = {key: value for key, value in kwargs.items() if key != "use_safetensors"}
    processor = AutoProcessor.from_pretrained(reference, use_fast=False, **processor_kwargs)
    processor.image_processor.size = dict(IMAGE_SIZE)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(reference, **kwargs).to(device).eval()
    return torch, transformers, processor, model


def run_inference(
    manifest_path: Path,
    dataset_root: Path,
    output_path: Path,
    *,
    model_path: str | None = None,
    device: str = "cpu",
    threshold: float = BOX_THRESHOLD,
    text_threshold: float = TEXT_THRESHOLD,
    max_detections: int = MAX_DETECTIONS_PER_IMAGE,
    expected_samples: int | None = EXPECTED_SAMPLE_COUNT,
    force: bool = False,
) -> dict[str, Any]:
    if device != "cpu":
        raise ValueError("this task is intentionally restricted to CPU inference")
    if not 0.0 <= text_threshold <= 1.0 or max_detections <= 0:
        raise ValueError("invalid inference thresholds or max detections")
    manifest, manifest_sha256, sources = load_verified_manifest(
        manifest_path, dataset_root, expected_samples=expected_samples
    )
    output_path = output_path.absolute()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.is_symlink() or (output_path.exists() and not force):
        raise FileExistsError(f"refusing to replace existing output: {output_path}; pass --force explicitly")
    if output_path.resolve(strict=False).is_relative_to(Path(dataset_root).resolve(strict=True)):
        raise ValueError("prediction output must be outside the source dataset root")

    torch, transformers, processor, model = _load_detector(model_path, device)
    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    results = []
    for sample, image_path in sources:
        with Image.open(image_path) as image:
            image = image.convert("RGB")
        inputs = processor(images=image, text=CAPTION, return_tensors="pt")
        with torch.inference_mode():
            outputs = model(**inputs)
        detection = processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            threshold=threshold,
            text_threshold=text_threshold,
            target_sizes=[(image.height, image.width)],
        )[0]
        text_labels = detection.get("text_labels")
        if text_labels is None:
            raise RuntimeError("Grounding DINO did not return text_labels; refusing numeric class IDs")
        results.append(
            make_sample_result(
                sample,
                {"scores": detection["scores"], "labels": text_labels, "boxes": detection["boxes"]},
                threshold=threshold,
                max_detections=max_detections,
            )
        )

    payload = {
        "schema_version": 1,
        "manifest_sha256": manifest_sha256,
        "prediction_type": "zero-shot detector predictions; not ground truth",
        "model": {
            "id": MODEL_ID,
            "revision": MODEL_REVISION,
            "weights_sha256": MODEL_WEIGHTS_SHA256,
            "license": MODEL_LICENSE,
            "model_card_url": MODEL_CARD_URL,
            "upstream_license_url": UPSTREAM_LICENSE_URL,
            "architecture": "Grounding DINO tiny; text-conditioned zero-shot object detection",
            "device": device,
            "torch_version": torch.__version__,
            "transformers_version": transformers.__version__,
            "threshold": threshold,
            "text_threshold": text_threshold,
            "nms_iou_threshold": NMS_IOU_THRESHOLD,
            "max_detections_per_image": max_detections,
            "caption": CAPTION,
            "image_resize": IMAGE_SIZE,
            "xyxy_coordinate_space": "original source image pixels; x right, y down",
        },
        "samples": results,
    }
    write_json_without_overwrite(output_path, payload, force=force)
    return payload


def write_json_without_overwrite(path: Path, payload: dict[str, Any], *, force: bool = False) -> None:
    """Write complete JSON atomically; do not clobber prior output implicitly."""
    data = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if force:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model-path", help="local snapshot directory; otherwise fetch the pinned public revision")
    parser.add_argument("--box-threshold", type=float, default=BOX_THRESHOLD)
    parser.add_argument("--text-threshold", type=float, default=TEXT_THRESHOLD)
    parser.add_argument("--max-detections", type=int, default=MAX_DETECTIONS_PER_IMAGE)
    parser.add_argument("--expected-samples", type=int, default=EXPECTED_SAMPLE_COUNT)
    parser.add_argument("--force", action="store_true", help="replace the output JSON after successful inference")
    return parser


def main() -> int:
    args = _argument_parser().parse_args()
    payload = run_inference(
        args.manifest,
        args.dataset_root,
        args.output,
        model_path=args.model_path,
        threshold=args.box_threshold,
        text_threshold=args.text_threshold,
        max_detections=args.max_detections,
        expected_samples=args.expected_samples,
        force=args.force,
    )
    detected = sum(sample["detection_status"] == "detected" for sample in payload["samples"])
    total_boxes = sum(len(sample["boxes"]) for sample in payload["samples"])
    print(f"wrote {args.output}: {detected}/{len(payload['samples'])} samples detected; {total_boxes} boxes")
    print("Predictions only; inspect boxes for quality and create human-reviewed labels separately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
