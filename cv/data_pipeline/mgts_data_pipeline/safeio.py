from __future__ import annotations

import hashlib
import io
import stat
import zipfile
from pathlib import Path, PurePosixPath

from PIL import Image, UnidentifiedImageError

from .errors import PipelineError


MAX_ARCHIVE_FILES = 100_000
MAX_ARCHIVE_BYTES = 50_000_000_000
MAX_ARCHIVE_MEMBER_BYTES = 2_000_000_000
MAX_EXPANSION_RATIO = 1_000
MAX_IMAGE_PIXELS = 80_000_000
IMAGE_EXTENSIONS = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "BMP": ".bmp",
    "TIFF": ".tif",
}


def safe_member_name(name: str) -> str:
    if not name or "\x00" in name or "\\" in name:
        raise PipelineError(f"unsafe archive path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise PipelineError(f"unsafe archive path: {name!r}")
    if path.parts and ":" in path.parts[0]:
        raise PipelineError(f"unsafe archive path: {name!r}")
    return path.as_posix()


def validate_zip(
    archive_path: Path,
    *,
    max_files: int = MAX_ARCHIVE_FILES,
    max_uncompressed_bytes: int = MAX_ARCHIVE_BYTES,
    max_member_bytes: int = MAX_ARCHIVE_MEMBER_BYTES,
    max_expansion_ratio: int = MAX_EXPANSION_RATIO,
) -> list[zipfile.ZipInfo]:
    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PipelineError(f"not a readable ZIP archive: {archive_path}") from exc
    with archive:
        entries = archive.infolist()
        if len(entries) > max_files:
            raise PipelineError(f"archive file-count limit exceeded: {len(entries)}")
        total_size = 0
        names: set[str] = set()
        for info in entries:
            name = safe_member_name(info.filename.rstrip("/") if info.is_dir() else info.filename)
            if name in names:
                raise PipelineError(f"duplicate archive member: {name}")
            names.add(name)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise PipelineError(f"archive symlink is not allowed: {name}")
            if info.file_size < 0 or info.compress_size < 0:
                raise PipelineError(f"invalid archive member sizes: {name}")
            if info.file_size > max_member_bytes:
                raise PipelineError(f"archive member size limit exceeded: {name}")
            total_size += info.file_size
            if total_size > max_uncompressed_bytes:
                raise PipelineError(f"archive expansion limit exceeded: more than {max_uncompressed_bytes} bytes")
            if info.file_size and not info.compress_size:
                raise PipelineError(f"archive expansion limit exceeded: zero-sized compressed member {name}")
            if info.compress_size and info.file_size / info.compress_size > max_expansion_ratio:
                raise PipelineError(f"archive expansion limit exceeded: compression ratio for {name}")
        return entries


def image_dimensions(data: bytes) -> tuple[int, int, str, int | None]:
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image_format = image.format
            orientation = image.getexif().get(274)
            if not width or not height or width * height > MAX_IMAGE_PIXELS:
                raise PipelineError(f"image dimensions exceed safety limit: {width}x{height}")
            if image_format not in IMAGE_EXTENSIONS:
                raise PipelineError(f"unsupported image format: {image_format!r}")
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except PipelineError:
        raise
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise PipelineError("invalid or corrupt image bytes") from exc
    return width, height, image_format, orientation


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_regular_file(path: Path) -> None:
    try:
        if path.is_symlink() or not path.is_file():
            raise PipelineError(f"expected regular file, got unsafe or missing path: {path}")
    except OSError as exc:
        raise PipelineError(f"cannot inspect input path: {path}") from exc
