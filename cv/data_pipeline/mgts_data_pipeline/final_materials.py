"""Inventory organizer ZIPs and their XLSX labels, without inventing boxes or splits."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import urllib.request
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from PIL import Image

ORGANIZER_ARCHIVES = {
    'doc-1795639519.zip': '489abe2497e1282d166e56197ff0f61c033ecbf7d4545ad9c57f757eb20302ce',
    'doc-1795639569.zip': '7f343037479cac7340dbc9f912a37713d4b7c2a4a7e6dac0bd1955ab409c56ed',
}


def download_archives(root: Path) -> list[Path]:
    """Explicitly fetch pinned organizer artifacts; verified files are reused."""
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, digest in ORGANIZER_ARCHIVES.items():
        target = root / name
        if target.is_symlink():
            raise ValueError('unsafe archive symlink')
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError(f'archive SHA-256 mismatch: {name}; preserve and investigate this file')
        else:
            fd, pending_name = tempfile.mkstemp(prefix='.'+name, dir=root)
            import os
            pending = Path(pending_name)
            try:
                with os.fdopen(fd, 'wb') as out, urllib.request.urlopen(
                    'https://lk.studchamp.mgts.ru/storage/docs/'+name, timeout=60
                ) as response:
                    size = 0
                    while block := response.read(1024*1024):
                        size += len(block)
                        if size > 100_000_000:
                            raise ValueError('organizer download exceeds 100 MB limit')
                        out.write(block)
                if hashlib.sha256(pending.read_bytes()).hexdigest() != digest:
                    raise ValueError(f'archive SHA-256 mismatch: {name}')
                # Hard link fails rather than replacing a file created concurrently.
                os.link(pending, target)
            finally:
                pending.unlink(missing_ok=True)
        paths.append(target)
    return paths


IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def _sheet_rows(contents: bytes) -> list[list[str]]:
    with ZipFile(BytesIO(contents)) as book:
        strings = []
        if 'xl/sharedStrings.xml' in book.namelist():
            for item in ET.fromstring(book.read('xl/sharedStrings.xml')).findall('s:si', NS):
                strings.append(''.join(item.itertext()))
        rows = []
        for name in sorted(book.namelist()):
            if not name.startswith('xl/worksheets/sheet') or not name.endswith('.xml'):
                continue
            for row in ET.fromstring(book.read(name)).findall('.//s:row', NS):
                values = ['', '', '']
                for cell in row.findall('s:c', NS):
                    col = ''.join(c for c in cell.get('r', '') if c.isalpha())
                    if col not in ('A', 'B', 'C'):
                        continue
                    value = cell.find('s:v', NS)
                    text = value.text if value is not None else ''
                    if cell.get('t') == 's':
                        text = strings[int(text)]
                    elif cell.get('t') == 'inlineStr':
                        text = ''.join(cell.find('s:is', NS).itertext())
                    values[ord(col) - ord('A')] = text or ''
                rows.append(values)
        return rows


def _folder_label(folder: str) -> tuple[str, str]:
    object_type = 'ТКШ' if 'ТКШ' in folder else 'РЩ' if 'РЩ' in folder else 'unknown'
    if folder.startswith('Удовлетворительное'):
        condition = 'normal'
    elif folder.startswith('МП.'):
        condition = 'mechanical_damage'
    elif folder.startswith('Неудовлетворительное') and 'ЛКП' in folder:
        condition = 'coating_damage'
    else:
        condition = 'unknown'
    return object_type, condition


def _gps(image: Image.Image) -> dict[str, float] | None:
    try:
        gps = image.getexif().get_ifd(34853)
        def degrees(values):
            return float(values[0]) + float(values[1])/60 + float(values[2])/3600
        lat = degrees(gps[2]) * (-1 if gps[1] == 'S' else 1)
        lon = degrees(gps[4]) * (-1 if gps[3] == 'W' else 1)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return {'latitude': lat, 'longitude': lon}
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def prepare_materials(archives: list[Path], output: Path) -> dict:
    """Create a new image/manifest directory; no network, pixel interpretation or overwrite."""
    if output.exists() or output.is_symlink():
        raise ValueError(f'output exists: {output}')
    if not archives or any(not p.is_file() for p in archives):
        raise ValueError('missing source ZIP')
    if len({p.stem for p in archives}) != len(archives):
        raise ValueError('archive names must be unique')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.final-materials-', dir=output.parent))
    samples, sources = [], []
    try:
        for archive in archives:
            sources.append({'name': archive.name, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()})
            with ZipFile(archive) as zipped:
                infos = zipped.infolist()
                if sum(i.file_size for i in infos) > 500_000_000:
                    raise ValueError('archive exceeds 500 MB expanded limit')
                for info in infos:
                    path = PurePosixPath(info.filename)
                    if path.is_absolute() or '..' in path.parts or '\\' in info.filename:
                        raise ValueError('unsafe ZIP member path')
                labels = {}
                for info in infos:
                    if info.filename.lower().endswith('.xlsx'):
                        for stem, status, description in _sheet_rows(zipped.read(info)):
                            if stem and stem != 'Имя файла':
                                labels[(str(PurePosixPath(info.filename).parent), stem)] = (status, description)
                for info in infos:
                    path = PurePosixPath(info.filename)
                    if path.suffix.lower() not in IMAGE_EXTENSIONS:
                        continue
                    if info.file_size > 10_000_000:
                        raise ValueError('image exceeds 10 MB limit')
                    contents = zipped.read(info)
                    relative = PurePosixPath(archive.stem) / path
                    target = temporary / str(relative)
                    if target.exists():
                        raise ValueError('duplicate ZIP image path')
                    with Image.open(BytesIO(contents)) as image:
                        if image.width * image.height > 20_000_000:
                            raise ValueError('image exceeds 20 MP limit')
                        width, height, coordinates = image.width, image.height, _gps(image)
                    with Image.open(BytesIO(contents)) as image:
                        image.verify()
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(contents)
                    object_type, folder_condition = _folder_label(path.parent.name)
                    annotation = labels.get((str(path.parent), path.stem))
                    samples.append({
                        'image_path': str(relative), 'object_id': path.stem,
                        'object_type': object_type,
                        'condition': folder_condition if annotation else 'unknown',
                        'folder_condition': folder_condition,
                        'status': annotation[0] if annotation else '',
                        'description': annotation[1] if annotation else '',
                        'source_folder': str(path.parent), 'source_archive': archive.name,
                        'sha256': hashlib.sha256(contents).hexdigest(),
                        'width': width, 'height': height, 'coordinates': coordinates,
                        'split': 'unassigned', 'bbox_annotations': None,
                    })
        report = {
            'schema_version': 1, 'sources': sources, 'samples': samples,
            'counts': dict(Counter(sample['condition'] for sample in samples)),
            'warnings': [
                'Image-level labels from organizer XLSX/folders, not bounding-box annotations.',
                'No organizer train/validation/test assignment; do not report training-set accuracy as test quality.',
                'Preserve original status/description: coating and mechanical defects can coexist.',
                'Repeated object_id (including across folders/types) must stay in one evaluation group.',
                'Missing spreadsheet labels remain unknown; normal is never a fallback.',
                'Coordinates come only from EXIF GPS when present; do not fabricate missing locations.',
            ],
        }
        (temporary/'final-materials.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        if output.exists() or output.is_symlink():
            raise ValueError('output appeared during preparation')
        temporary.rename(output)
        return report
    except BaseException:
        shutil.rmtree(temporary)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, action='append')
    parser.add_argument('--download-root', type=Path, help='explicitly fetch/reuse pinned organizer ZIPs here')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if bool(args.archive) == bool(args.download_root):
        parser.error('choose --archive or --download-root')
    archives = download_archives(args.download_root) if args.download_root else args.archive
    result = prepare_materials(archives, args.output)
    print(json.dumps({'counts': result['counts'], 'sources': result['sources'], 'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
