from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from PIL import Image

from mgts_data_pipeline.final_materials import prepare_materials


def archive(path, name='Датасет-ДСС/Удовлетворительное состояние РЩ/123.jpg'):
    image = BytesIO()
    Image.new('RGB', (12, 8)).save(image, format='JPEG')
    with ZipFile(path, 'w') as z:
        z.writestr(name, image.getvalue())


def test_inventory_without_spreadsheets_is_unknown_not_assumed_healthy(tmp_path):
    source = tmp_path / 'source.zip'
    archive(source)
    result = prepare_materials([source], tmp_path / 'output')
    assert len(result['samples']) == 1
    sample = result['samples'][0]
    assert sample['condition'] == 'unknown'
    assert sample['folder_condition'] == 'normal'
    assert sample['object_type'] == 'РЩ'
    assert sample['coordinates'] is None
    assert sample['split'] == 'unassigned'
    assert (tmp_path / 'output' / sample['image_path']).is_file()
    assert (tmp_path / 'output' / 'final-materials.json').is_file()


def test_safe_paths_and_no_overwrite(tmp_path):
    source = tmp_path / 'source.zip'
    archive(source, '../evil.jpg')
    with pytest.raises(ValueError, match='unsafe'):
        prepare_materials([source], tmp_path / 'out')
    assert not (tmp_path / 'evil.jpg').exists()
    archive(source)
    prepare_materials([source], tmp_path / 'good')
    with pytest.raises(ValueError, match='exists'):
        prepare_materials([source], tmp_path / 'good')


def test_missing_source_and_unsupported_files(tmp_path):
    with pytest.raises(ValueError, match='missing'):
        prepare_materials([tmp_path/'missing.zip'], tmp_path/'out')
    source=tmp_path/'source.zip'
    with ZipFile(source,'w') as z:
        z.writestr('run.exe',b'do not execute')
    result=prepare_materials([source],tmp_path/'out')
    assert result['samples']==[]
    assert not (tmp_path/'out'/'source'/'run.exe').exists()


def test_spreadsheet_labels_are_folder_qualified_and_png_supported(tmp_path):
    sheet = BytesIO()
    with ZipFile(sheet, 'w') as x:
        x.writestr('xl/worksheets/sheet1.xml', '''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
        <row><c r="A1" t="inlineStr"><is><t>Имя файла</t></is></c></row>
        <row><c r="A2"><v>123</v></c><c r="B2" t="inlineStr"><is><t>Деформация</t></is></c><c r="C2" t="inlineStr"><is><t>МП двери</t></is></c></row>
        </sheetData></worksheet>''')
    source = tmp_path/'source.zip'
    image=BytesIO();Image.new('RGB',(5,7)).save(image,format='PNG')
    with ZipFile(source,'w') as z:
        z.writestr('Датасет-ДСС/МП. ТКШ/123.png',image.getvalue())
        z.writestr('Датасет-ДСС/МП. ТКШ/meta.xlsx',sheet.getvalue())
        z.writestr('Датасет-ДСС/Фото.1.jpg',image.getvalue())
    result=prepare_materials([source],tmp_path/'out')
    assert result['counts']=={'mechanical_damage':1,'unknown':1}
    assert result['samples'][0]['description']=='МП двери'
    assert result['samples'][0]['object_type']=='ТКШ'
    assert result['samples'][0]['height']==7
