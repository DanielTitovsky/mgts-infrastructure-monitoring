from __future__ import annotations

import ast
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
import sys
import zlib

from PIL import Image
import pytest

from mgts_data_pipeline import inference


def test_selected_repository_checkpoint_matches_the_verified_artifact_sha256() -> None:
    checkpoint = Path(__file__).parents[3] / "cv" / "ml" / "best.pt"

    assert sha256(checkpoint.read_bytes()).hexdigest() == (
        "17fa86e2c49de2e125f84b7badfb2f6983aa8a607dedee5eede4743d92d3883d"
    )


def _image_bytes(size: tuple[int, int] = (24, 16)) -> bytes:
    image = Image.new("RGB", size, color=(0, 0, 0))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class _Tensor:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def cpu(self) -> _Tensor:
        return self

    def tolist(self) -> list[object]:
        return self.values


class _FakeModel:
    task = "detect"
    names = {0: "odn_pole"}

    def __init__(self) -> None:
        self.call: dict[str, object] | None = None

    def predict(self, **kwargs: object) -> list[object]:
        self.call = kwargs
        return [
            type(
                "Result",
                (),
                {
                    "boxes": type(
                        "Boxes",
                        (),
                        {
                            "xyxy": _Tensor([[1.0, 2.0, 20.0, 15.0]]),
                            "conf": _Tensor([0.83]),
                            "cls": _Tensor([0.0]),
                        },
                    )(),
                },
            )()
        ]


def test_inference_uses_local_detection_model_and_maps_actual_class_metadata(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"local-checkpoint")
    constructed: list[str] = []
    model = _FakeModel()

    def factory(path: str) -> _FakeModel:
        constructed.append(path)
        return model

    report = inference.infer_photo(
        filename="capture.png",
        contents=_image_bytes(),
        model_path=checkpoint,
        predictor_factory=factory,
    )

    assert constructed == [str(checkpoint.resolve())]
    assert report == {
        "model_sha256": sha256(b"local-checkpoint").hexdigest(),
        "task": "detect",
        "class_names": ["odn_pole"],
        "image": {"filename": "capture.png", "width": 24, "height": 16},
        "confidence_threshold": 0.25,
        "detections": [
            {
                "class_id": 0,
                "class": "odn_pole",
                "confidence": 0.83,
                "bbox_xyxy_px": [1.0, 2.0, 20.0, 15.0],
            }
        ],
    }
    assert model.call is not None
    assert model.call["device"] == "cpu"
    assert model.call["imgsz"] == 640
    assert model.call["conf"] == 0.25
    assert model.call["max_det"] == 100
    assert model.call["save"] is False
    assert model.call["verbose"] is False


def test_missing_checkpoint_fails_before_predictor_construction(tmp_path: Path) -> None:
    constructed: list[str] = []
    with pytest.raises(inference.InferenceError, match="configured local model checkpoint"):
        inference.infer_photo(
            filename="capture.png",
            contents=_image_bytes(),
            model_path=tmp_path / "missing.pt",
            predictor_factory=lambda path: constructed.append(path),
        )
    assert constructed == []


@pytest.mark.parametrize("filename", ["capture.gif", "capture.txt", "no-extension"])
def test_unsupported_file_extensions_are_rejected(filename: str, tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    with pytest.raises(inference.InferenceError, match="JPEG, PNG, or WebP"):
        inference.infer_photo(filename=filename, contents=_image_bytes(), model_path=checkpoint)


def test_corrupt_image_is_rejected_without_loading_the_model(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    constructed: list[str] = []
    with pytest.raises(inference.InferenceError, match="could not be decoded"):
        inference.infer_photo(
            filename="capture.png",
            contents=b"not an image",
            model_path=checkpoint,
            predictor_factory=lambda path: constructed.append(path),
        )
    assert constructed == []


def test_upload_byte_limit_is_enforced_before_model_loading(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    constructed: list[str] = []
    with pytest.raises(inference.InferenceError, match="10 MB limit"):
        inference.infer_photo(
            filename="capture.png",
            contents=b"x" * (inference.MAX_IMAGE_BYTES + 1),
            model_path=checkpoint,
            predictor_factory=lambda path: constructed.append(path),
        )
    assert constructed == []


def test_upload_pixel_limit_is_enforced_before_image_decode_or_model_loading(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    width, height = 4473, 4473
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    def chunk(name: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + name + payload + struct.pack(
            ">I", zlib.crc32(name + payload)
        )

    large_image = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\0\0\0\0")) + chunk(b"IEND", b"")
    constructed: list[str] = []
    with pytest.raises(inference.InferenceError, match="20 MP limit"):
        inference.infer_photo(
            filename="capture.png",
            contents=large_image,
            model_path=checkpoint,
            predictor_factory=lambda path: constructed.append(path),
        )
    assert constructed == []


def test_uploaded_extension_does_not_override_actual_image_format(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    image = BytesIO()
    Image.new("RGB", (1, 1)).save(image, format="GIF")
    with pytest.raises(inference.InferenceError, match="JPEG, PNG, or WebP"):
        inference.infer_photo(filename="capture.png", contents=image.getvalue(), model_path=checkpoint)


def test_empty_upload_is_rejected(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")

    with pytest.raises(inference.InferenceError, match="uploaded image is empty"):
        inference.infer_photo(filename="capture.png", contents=b"", model_path=checkpoint)


def test_non_detection_checkpoints_are_rejected(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    model = _FakeModel()
    model.task = "segment"
    with pytest.raises(inference.InferenceError, match="detection checkpoint"):
        inference.infer_photo(
            filename="capture.png",
            contents=_image_bytes(),
            model_path=checkpoint,
            predictor_factory=lambda _path: model,
        )


def test_names_list_in_checkpoint_metadata_is_used_for_returned_class(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    model = _FakeModel()
    model.names = ["metadata-driven-name"]
    report = inference.infer_photo(
        filename="capture.png",
        contents=_image_bytes(),
        model_path=checkpoint,
        predictor_factory=lambda _path: model,
    )
    assert report["class_names"] == ["metadata-driven-name"]
    assert report["detections"][0]["class"] == "metadata-driven-name"


def test_missing_class_metadata_is_rejected(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    model = _FakeModel()
    model.names = None
    with pytest.raises(inference.InferenceError, match="no detection class metadata"):
        inference.infer_photo(
            filename="capture.png",
            contents=_image_bytes(),
            model_path=checkpoint,
            predictor_factory=lambda _path: model,
        )


def test_absent_optional_runtime_is_reported_without_fallback_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    monkeypatch.setitem(sys.modules, "ultralytics", None)

    with pytest.raises(inference.InferenceError, match="install the .inference. extra"):
        inference.infer_photo(filename="capture.png", contents=_image_bytes(), model_path=checkpoint)


def test_missing_result_boxes_fail_closed(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    model = _FakeModel()
    model.predict = lambda **_kwargs: []
    with pytest.raises(inference.InferenceError, match="no detection results"):
        inference.infer_photo(
            filename="capture.png",
            contents=_image_bytes(),
            model_path=checkpoint,
            predictor_factory=lambda _path: model,
        )


def test_predictor_errors_are_sanitized(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")

    def fail_factory(_path: str) -> _FakeModel:
        raise RuntimeError("private detail")

    with pytest.raises(inference.InferenceError, match="Photo inference failed"):
        inference.infer_photo(
            filename="capture.png",
            contents=_image_bytes(),
            model_path=checkpoint,
            predictor_factory=fail_factory,
        )


def test_unknown_prediction_class_is_rejected(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint")
    model = _FakeModel()
    model.predict = lambda **_kwargs: [
        type(
            "Result",
            (),
            {
                "boxes": type(
                    "Boxes",
                    (),
                    {
                        "xyxy": _Tensor([[1.0, 2.0, 20.0, 15.0]]),
                        "conf": _Tensor([0.83]),
                        "cls": _Tensor([1.0]),
                    },
                )()
            },
        )()
    ]

    with pytest.raises(inference.InferenceError, match="missing from checkpoint metadata"):
        inference.infer_photo(
            filename="capture.png",
            contents=_image_bytes(),
            model_path=checkpoint,
            predictor_factory=lambda _path: model,
        )


def test_notebook_runs_photo_inference_only_after_its_form_is_submitted() -> None:
    notebook = Path(__file__).parents[1] / "notebooks" / "dataset_workbench.py"
    source = notebook.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "photo_form = mo.ui.form(" in source
    assert 'filetypes=[".jpg", ".jpeg", ".png", ".webp"]' in source

    photo_cells = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(call.func, ast.Name) and call.func.id == "infer_photo"
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
        )
    ]
    assert len(photo_cells) == 1
    cell = photo_cells[0]
    inference_branch = next(
        node
        for node in ast.walk(cell)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Attribute)
        and node.test.left.attr == "value"
        and isinstance(node.test.left.value, ast.Name)
        and node.test.left.value.id == "photo_form"
        and any(isinstance(op, ast.Is) for op in node.test.ops)
    )
    assert any(
        isinstance(call.func, ast.Name) and call.func.id == "infer_photo"
        for statement in inference_branch.orelse
        for call in ast.walk(statement)
        if isinstance(call, ast.Call)
    )
