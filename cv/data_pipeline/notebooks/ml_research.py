"""Editable, human-centered MGTS cabinet photo review and ML workspace."""

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _():
    import hashlib
    import os
    from mgts_data_pipeline.mlp_predict import predict_upload_head
    mlp_path = os.environ.get("MGTS_MLP_HEAD", "/data/archive/mgts-final/cabinet-mlp-head-v1.json")
    from html import escape
    from io import BytesIO

    import marimo as mo
    from PIL import Image

    from mgts_data_pipeline.cabinet_baseline import (
        build_reference_index,
        embed_photo,
        evaluate_leave_group_out,
        load_embedder,
        load_reference_index,
        retrieve,
    )
    from mgts_data_pipeline.dataset_review import (
        AuditDataError,
        build_audit_rows,
        load_optional_json,
        oof_metrics,
        proposal_preview_bytes,
        sha256_file,
    )
    from mgts_data_pipeline.research import (
        ResearchError,
        binary_damage_summary,
        load_material_manifest,
        load_material_sample,
        preview_image_bytes,
    )

    manifest_path = os.environ.get("MGTS_FINAL_MANIFEST", "/data/archive/mgts-final/final-materials.json")
    model_path = os.environ.get("MGTS_MODEL_PATH", "/models/best.pt")
    index_path = os.environ.get("MGTS_REFERENCE_INDEX", "/data/output/cabinet-reference-index.json")
    oof_path = os.environ.get("MGTS_CABINET_OOF", "/data/output/cabinet-oof-predictions-v1.json")
    box_report_path = os.environ.get("MGTS_BOX_REPORT", "/data/archive/mgts-final/cabinet-boxes.json")
    return (
        mlp_path, predict_upload_head,
        AuditDataError,
        BytesIO,
        escape,
        Image,
        ResearchError,
        binary_damage_summary,
        build_reference_index,
        build_audit_rows,
        embed_photo,
        evaluate_leave_group_out,
        hashlib,
        index_path,
        load_embedder,
        load_material_manifest,
        load_material_sample,
        load_optional_json,
        load_reference_index,
        manifest_path,
        model_path,
        mo,
        oof_metrics,
        oof_path,
        box_report_path,
        proposal_preview_bytes,
        preview_image_bytes,
        sha256_file,
        retrieve,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Осмотр шкафов и распределительных щитов МГТС

    **Все 62 фотографии открыты ниже без загрузки и запуска.** Листайте галерею, ищите по ID или пути, фильтруйте исходные состояния и ошибки «повреждение → норма». На каждой карточке рядом показаны исходный кадр и обработка; рамки детектора — только предложения объекта, не разметка дефекта.

    МГТС задаёт исходную метку состояния. kNN, линейная модель и MLP показывают групповые out-of-fold прогнозы, если готовый артефакт доступен. «Норма» при подтверждённом повреждении отмечена как false negative. Ни одна оценка не является независимой полевой проверкой или решением о ремонте.
    """)
    return


@app.cell(hide_code=True)
def _():
    condition_ru = {
        "normal": "Норма", "mechanical_damage": "Механическое повреждение",
        "coating_damage": "Дефект покрытия", "unknown": "Без разметки",
    }
    return (condition_ru,)


@app.cell(hide_code=True)
def _(AuditDataError, ResearchError, build_audit_rows, condition_ru, index_path, load_material_manifest, load_optional_json, load_reference_index, manifest_path, mo, oof_path, box_report_path, sha256_file):
    """Read validated metadata and optional result artifacts on open."""
    try:
        materials = load_material_manifest(manifest_path)
    except (ResearchError, OSError, ValueError) as error:
        materials = None
        manifest_sha256 = None
        inventory_error = str(error)
        inventory_message = mo.callout(mo.md("Не удалось прочитать подготовленный реестр фотографий."), kind="danger")
        index, index_sha256, index_error = None, None, "реестр фотографий недоступен"
        oof, oof_error = None, None
        box_report, box_error = None, None
        audit_rows = []
    else:
        manifest_sha256 = sha256_file(materials["path"])
        inventory_error = None
        inventory_message = mo.md(
            f"Реестр: **{materials['sample_count']} фото** · SHA-256 `{manifest_sha256}`. "
            "Кадр без подписи остаётся в галерее и исключён из оценки."
        )
        try:
            index = load_reference_index(index_path)
            index_sha256 = sha256_file(index_path)
            index_error = None
        except (ValueError, OSError, AuditDataError) as error:
            index, index_sha256, index_error = None, None, str(error)
        try:
            oof = load_optional_json(oof_path, label="grouped OOF predictions")
            oof_error = None
        except AuditDataError as error:
            oof, oof_error = None, str(error)
        try:
            box_report = load_optional_json(box_report_path, label="cabinet detector report")
            box_error = None
        except AuditDataError as error:
            box_report, box_error = None, str(error)

        audit_manifest = {"schema_version": 1, "samples": materials["samples"]}
        audit_index = index
        accepted_oof = oof if index is not None else None
        try:
            audit_rows = build_audit_rows(
                audit_manifest,
                audit_index,
                accepted_oof,
                manifest_sha256=manifest_sha256,
                index_sha256=index_sha256,
            )
        except AuditDataError as error:
            if accepted_oof is not None:
                oof_error = str(error)
                accepted_oof = None
                audit_rows = build_audit_rows(
                    audit_manifest,
                    audit_index,
                    None,
                    manifest_sha256=manifest_sha256,
                    index_sha256=index_sha256,
                )
            else:
                index_error = index_error or str(error)
                index = None
                audit_rows = build_audit_rows(
                    audit_manifest,
                    None,
                    None,
                    manifest_sha256=manifest_sha256,
                )
        if box_report is not None:
            try:
                audit_rows = build_audit_rows(
                    audit_manifest,
                    index,
                    accepted_oof,
                    box_report=box_report,
                    manifest_sha256=manifest_sha256,
                    index_sha256=index_sha256,
                )
            except AuditDataError as error:
                box_error = str(error)
        if box_error:
            box_report = None

        _rows = []
        for _code, _caption in condition_ru.items():
            _records = [r for r in materials["samples"] if r["condition"] == _code]
            _rows.append({
                "Состояние по МГТС": _caption,
                "ТКШ": sum(r["object_type"] == "ТКШ" for r in _records),
                "РЩ": sum(r["object_type"] == "РЩ" for r in _records),
                "Тип не указан": sum(r["object_type"] not in {"ТКШ", "РЩ"} for r in _records),
                "Всего фото": len(_records),
            })
        _summary_table = mo.ui.table(
            _rows, selection=None, pagination=False, show_search=False,
            show_column_summaries=False, show_data_types=False,
            label=f"Состав выборки · {materials['sample_count']} фото",
        )
        inventory_message = mo.vstack([inventory_message, _summary_table])
    if materials is not None and not inventory_error:
        _notices = []
        if index_error:
            _notices.append(mo.callout(mo.md("Групповой индекс kNN недоступен; не выполняется новое извлечение признаков."), kind="warn"))
        if oof_error:
            _notices.append(mo.callout(mo.md("OOF прогнозы не прошли проверку идентичности и групповой изоляции; выводится «не вычислено»."), kind="warn"))
        elif oof is None:
            _notices.append(mo.callout(mo.md("Артефакт grouped OOF пока не найден; вместо него не подставляется прогноз kNN или MLP."), kind="warn"))
        if box_error:
            _notices.append(mo.callout(mo.md("Отчёт детектора не прошёл проверку; рамки не показываются."), kind="warn"))
        elif box_report is None:
            _notices.append(mo.callout(mo.md("Детектор ещё не запускался для текущего набора."), kind="warn"))
        if _notices:
            inventory_message = mo.vstack([inventory_message, *_notices])
    inventory_message
    return audit_rows, box_error, box_report, index, index_error, inventory_error, manifest_sha256, materials, oof, oof_error


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Галерея данных, групповых прогнозов и предложений рамок

    Фильтры влияют только на видимые карточки. Вся выборка остаётся в аудите: каждая строка определяется точной парой относительного пути и SHA-256, а не именем файла. Сетка показывает 12 фото за страницу, чтобы не выгружать все исходные изображения одновременно.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    filter_options = {
        "Все фото": "all",
        "Повреждение → «норма»": "false_normal",
        "Исходно нормальные": "normal",
        "Механическое повреждение": "mechanical_damage",
        "Дефект покрытия": "coating_damage",
        "Без разметки": "unknown",
        "Детектор без рамок": "no_boxes",
    }
    audit_search = mo.ui.text(label="Поиск по ID, пути, исходной подписи", placeholder="Например, 40035403")
    audit_filter = mo.ui.dropdown(options=filter_options, value="Все фото", label="Показывать")
    gallery_controls = mo.hstack([audit_search, audit_filter], widths="equal", align="end")
    gallery_controls
    return audit_filter, audit_search, gallery_controls


@app.cell(hide_code=True)
def _(audit_filter, audit_rows, audit_search, mo):
    _query = (audit_search.value or "").strip().casefold()
    _filter_value = audit_filter.value
    filtered_rows = []
    for _row in audit_rows:
        _sample = _row["sample"]
        if _filter_value == "false_normal" and not _row["false_normal_methods"]:
            continue
        if _filter_value == "normal" and _row["true"]["condition"] != "normal":
            continue
        if _filter_value in {"mechanical_damage", "coating_damage", "unknown"} and _row["true"]["condition"] != _filter_value:
            continue
        if _filter_value == "no_boxes" and _row["box_status"] == "proposals":
            continue
        _searchable = " ".join(str(_sample.get(_key, "")) for _key in
                               ("object_id", "image_path", "object_type", "condition", "status", "description")).casefold()
        if _query and _query not in _searchable:
            continue
        filtered_rows.append(_row)

    # Keep the requested confirmed false-normal example visible first when it exists.
    _focused = [row for row in filtered_rows if row["sample"].get("object_id") == "40035403"]
    if _focused:
        filtered_rows = _focused + [row for row in filtered_rows if row not in _focused]
    gallery_page_size = 12
    page_count = max(1, (len(filtered_rows) + gallery_page_size - 1) // gallery_page_size)
    audit_page = mo.ui.slider(
        steps=list(range(page_count)), value=0, show_value=True,
        label=f"Страница · {len(filtered_rows)} из {len(audit_rows)} фото",
    )
    audit_page
    return audit_page, filtered_rows, gallery_page_size


@app.cell(hide_code=True)
def _(BytesIO, ResearchError, AuditDataError, audit_page, audit_rows, condition_ru, escape, filtered_rows, gallery_page_size, load_material_sample, materials, mo, preview_image_bytes, proposal_preview_bytes):
    audit_by_path = {row["identity"][0]: row for row in audit_rows}
    _start = int(audit_page.value or 0) * gallery_page_size
    page_rows = filtered_rows[_start:_start + gallery_page_size]
    gallery_tiles = []
    try:
        for _row in page_rows:
            _sample = _row["sample"]
            _manifest_index = next(
                i for i, item in enumerate(materials["samples"])
                if item["image_path"] == _row["identity"][0]
                and item["sha256"].lower() == _row["identity"][1]
            )
            _loaded = load_material_sample(materials["path"], _manifest_index)
            # The manifest index remains the stable display key; exact path+digest were validated before this read.
            _original_bytes = preview_image_bytes(_loaded["image"], max_edge=280, max_bytes=16_000)
            _processed_bytes = None
            if _row["box_status"] == "proposals":
                _processed_bytes = proposal_preview_bytes(
                    _loaded["image"], _row["boxes"], expected_size=(_loaded["width"], _loaded["height"]),
                    max_edge=280, max_bytes=16_000,
                )
            elif _row["box_status"] == "empty":
                _processed_bytes = _original_bytes
            _original = mo.image(BytesIO(_original_bytes), alt="Исходное фото", width="100%")
            if _processed_bytes is None:
                _processed = mo.callout(mo.md("Детектор ещё не запускался"), kind="warn")
            else:
                _processed = mo.image(BytesIO(_processed_bytes), alt="Фото после обработки детектором", width="100%")

            _status = {
                "not_run": "детектор не запускался",
                "empty": "объект не найден",
                "proposals": f"рамок: {len(_row['boxes'])} · предложения объекта, не дефекта",
            }[_row["box_status"]]
            _truth = f"{_sample['object_type']} · {condition_ru.get(_sample['condition'], 'Без разметки')}"
            _predictions = []
            for _method, _name in (("knn_k5", "kNN"), ("linear_ridge", "Ridge"), ("supervised_mlp", "MLP")):
                _prediction = _row["predictions"][_method]
                _label = "не вычислено" if _prediction is None else condition_ru.get(_prediction["condition"], "не классифицировано")
                _predictions.append(f"{_name}: {_label}")
            _description = escape(str(_sample.get("description") or "Описание не предоставлено"))
            _source = escape(str(_sample.get("source_folder", "")))
            _fn_notice = "**FALSE NORMAL — нужен разбор специалиста.**  \n" if _row["false_normal_methods"] else ""
            _card_text = mo.md(
                f"**Фото № {escape(str(_sample['object_id']))} · {escape(str(_sample['image_path']))}**  \n"
                f"МГТС: **{escape(_truth)}**  \n"
                f"{' · '.join(_predictions)}  \n"
                f"**Рамки:** {_status}  \n"
                f"{_fn_notice}"
                f"Папка: {_source}  \n{_description}"
            )
            gallery_tiles.append(
                mo.vstack([
                    mo.hstack([_original, _processed], widths="equal", align="start"),
                    _card_text,
                ])
            )
    except (ResearchError, AuditDataError, OSError, ValueError, RuntimeError, StopIteration) as _error:
        gallery = mo.callout(mo.md("Не удалось подготовить ограниченные миниатюры галереи."), kind="danger")
    else:
        _rows_of_tiles = [mo.hstack(gallery_tiles[i:i + 2], widths="equal", align="start")
                          for i in range(0, len(gallery_tiles), 2)]
        if not _rows_of_tiles:
            gallery = mo.md("По заданным фильтрам фотографий нет.")
        else:
            gallery = mo.vstack(_rows_of_tiles)
    gallery_view = mo.vstack([audit_page, gallery])
    gallery_view
    return audit_by_path, gallery_view, page_rows


@app.cell(hide_code=True)
def _(audit_by_path, materials, mo):
    if not audit_by_path:
        detail_picker = None
        detail_picker_view = mo.md("Подробный просмотр появится, когда будет доступен реестр фотографий.")
    else:
        detail_options = {
            f"№ {sample['object_id']} · {sample['image_path']}": sample["image_path"]
            for sample in materials["samples"]
        }
        focus_key = next(
            (label for label, path in detail_options.items()
             if audit_by_path[path]["sample"].get("object_id") == "40035403"),
            next(iter(detail_options)),
        )
        detail_picker = mo.ui.dropdown(
            options=detail_options,
            value=focus_key,
            searchable=True,
            label="Фото для крупного просмотра (исходное / обработанное)",
        )
        detail_picker_view = detail_picker
    detail_picker_view
    return (detail_picker,)


@app.cell(hide_code=True)
def _(BytesIO, AuditDataError, ResearchError, audit_by_path, condition_ru, detail_picker, escape, index, load_material_sample, materials, mo, preview_image_bytes, proposal_preview_bytes, retrieve):
    from collections import Counter

    if not audit_by_path or detail_picker is None:
        detail_view = mo.md("Подробный просмотр появится, когда будет доступен реестр фотографий.")
    else:
        detail_path = detail_picker.value
        detail_row = audit_by_path[detail_path]
        _sample = detail_row["sample"]
        _manifest_index = next(
            i for i, item in enumerate(materials["samples"])
            if item["image_path"] == detail_row["identity"][0]
            and item["sha256"].lower() == detail_row["identity"][1]
        )
        try:
            _loaded = load_material_sample(materials["path"], _manifest_index)
            _source_bytes = preview_image_bytes(_loaded["image"], max_edge=900, max_bytes=100_000)
            _original_view = mo.image(BytesIO(_source_bytes), alt="Исходная фотография", width="100%")
            if detail_row["box_status"] == "proposals":
                _processed_bytes = proposal_preview_bytes(
                    _loaded["image"], detail_row["boxes"],
                    expected_size=(_loaded["width"], _loaded["height"]),
                    max_edge=900, max_bytes=100_000,
                )
                _processed_view = mo.image(BytesIO(_processed_bytes), alt="Фото с наложенными предложениями детектора", width="100%")
            elif detail_row["box_status"] == "empty":
                _processed_view = mo.vstack([
                    mo.image(BytesIO(_source_bytes), alt="Исходное фото без рамок детектора", width="100%"),
                    mo.md("**Объект не найден:** для этого фото детектор завершился, список рамок пуст.")
                ])
            else:
                _processed_view = mo.callout(
                    mo.md("**Детектор ещё не запускался для этого фото.** Исходный кадр не изменён."),
                    kind="warn",
                )
            _original_column = mo.vstack([
                mo.md("### Исходный кадр"),
                _original_view,
                mo.md(f"**МГТС:** {escape(str(_sample['object_type']))} · "
                      f"{escape(condition_ru.get(_sample['condition'], 'Без разметки'))}  \n"
                      f"**Исходное описание:** {escape(str(_sample.get('description') or 'не предоставлено'))}"),
            ])
            _processed_column = mo.vstack([
                mo.md("### Детектор объекта"),
                _processed_view,
                mo.md("Рамки локализуют только предполагаемый объект. Они не локализуют повреждение и не являются размёткой качества."),
            ])
            _prediction_rows = []
            for _method, _title in (("knn_k5", "kNN k=5"), ("linear_ridge", "Linear Ridge"), ("supervised_mlp", "MLP")):
                _prediction = detail_row["predictions"][_method]
                _prediction_rows.append({
                    "Модель": _title,
                    "Тип объекта": "не вычислено" if _prediction is None else _prediction["object_type"],
                    "Состояние": "не вычислено" if _prediction is None else condition_ru.get(_prediction["condition"], "не классифицировано"),
                })
            detail_parts = [
                detail_picker,
                mo.md(f"## Фото № {escape(str(_sample['object_id']))}  \n`{escape(detail_path)}` · SHA-256 `{detail_row['identity'][1]}`"),
                mo.hstack([_original_column, _processed_column], widths="equal", align="start"),
                mo.md("### Истина МГТС и out-of-fold прогнозы (групповая оценка)"),
                mo.ui.table(_prediction_rows, selection=None, pagination=False, show_search=False,
                            show_data_types=False, show_download=False),
            ]
            _condition_truth = detail_row["true"]["condition"]
            _predicted_normal = [
                _title for _method, _title in (("knn_k5", "kNN"), ("linear_ridge", "Linear Ridge"), ("supervised_mlp", "MLP"))
                if (detail_row["predictions"][_method] or {}).get("condition") == "normal"
            ]
            if _condition_truth in {"mechanical_damage", "coating_damage"} and _predicted_normal:
                detail_parts.append(mo.callout(
                    mo.md("**FALSE NORMAL:** исходная метка указывает повреждение, а прогноз «норма» дали "
                          + ", ".join(_predicted_normal) + ". Этот случай требует экспертной проверки."),
                    kind="danger",
                ))
            _cached = detail_row["index_record"]
            if index is None or _cached is None:
                neighbor_view = mo.md("Пять ближайших групп недоступны: готовый локальный индекс не найден.")
            else:
                _neighbor_result = retrieve(index, _cached["embedding"], top_k=5,
                                           exclude_group_id=detail_row["group_id"])
                _neighbors = _neighbor_result["matches"]
                _votes = Counter(item["condition"] for item in _neighbors)
                _vote_summary = " · ".join(
                    f"{condition_ru.get(label, label)} — {count}"
                    for label, count in sorted(_votes.items(), key=lambda pair: (-pair[1], pair[0]))
                ) or "нет независимых соседей"
                _neighbor_rows = [
                    {
                        "№": position,
                        "ID примера": item["object_id"],
                        "Исходная метка": condition_ru.get(item["condition"], "Без разметки"),
                        "Группа": item["group_id"],
                        "Косинус (не вероятность)": f"{item['similarity']:.4f}",
                    }
                    for position, item in enumerate(_neighbors, start=1)
                ]
                _neighbor_view = mo.vstack([
                    mo.md(f"#### Голоса ближайших пяти: **{escape(_vote_summary)}**. "
                          "Группа выбранного объекта исключена из поиска."),
                    mo.ui.table(_neighbor_rows, selection=None, pagination=False,
                                show_search=False, show_data_types=False, show_download=False),
                ])
                if _sample.get("object_id") == "40035403":
                    detail_parts.append(mo.callout(
                        mo.md("Для № 40035403 подтверждён false negative: исходная метка — "
                              "механическое повреждение, kNN — «норма»; голоса 5 ближайших: "
                              f"**{escape(_vote_summary)}**."),
                        kind="danger",
                    ))
                neighbor_view = _neighbor_view
            detail_parts.extend([mo.md("### Ближайшие примеры и голосование kNN"), neighbor_view])
            detail_view = mo.vstack(detail_parts)
        except (ResearchError, AuditDataError, OSError, ValueError, RuntimeError, StopIteration) as error:
            detail_view = mo.callout(mo.md("Не удалось подготовить крупный просмотр и сведения о соседях."), kind="danger")
    detail_view
    return detail_view,


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Как работает поиск и построение повторного индекса

    Галерея не запускает модель. Все подписи предсказаний взяты из сохранённых grouped OOF fold-артефактов; неизвестный кадр не классифицируется. Только ручное раскрытие подробностей вычисляет топ-5 по уже кэшированному вектору выбранного изображения.

    Существующий pole checkpoint не обучался на шкафах или повреждениях. Он только ранее получил frozen image features для сравнительных экспериментов. Сходство — **не вероятность, диагноз или прогноз ремонта**. Никакие веса не скачиваются, снимки не передаются, а новый индекс не строится без явного подтверждения.
    """)
    return


@app.cell(hide_code=True)
def _(index_path, manifest_path, model_path, mo):
    build_manifest = mo.ui.text(value=manifest_path, label="Подготовленный реестр фотографий")
    build_checkpoint = mo.ui.text(value=model_path, label="Доверенный локальный checkpoint (.pt)")
    build_output_path = mo.ui.text(value=index_path, label="Новый путь для JSON-индекса (перезапись запрещена)")
    build_limit = mo.ui.number(value=61, start=1, stop=61, step=1, label="Максимум размеченных фотографий: 1–61")
    build_form = mo.ui.form(
        mo.md("Реестр: {manifest}\n\nCheckpoint: {checkpoint}\n\nВыходной индекс: {output}\n\nЛимит: {limit}").batch(
            manifest=build_manifest,
            checkpoint=build_checkpoint,
            output=build_output_path,
            limit=build_limit,
        ),
        submit_button_label="Построить новый локальный индекс признаков",
        bordered=True,
    )
    mo.accordion({"Дополнительно: собрать новый индекс": build_form})
    return (build_form,)


@app.cell(hide_code=True)
def _(ResearchError, build_form, build_reference_index, mo):
    if build_form.value is None:
        build_result = mo.md("Для просмотра и сравнения используется готовый индекс. Пересобирать его не нужно.")
    else:
        try:
            index_report = build_reference_index(
                build_form.value["manifest"],
                build_form.value["output"],
                build_form.value["checkpoint"],
                max_samples=build_form.value["limit"],
            )
        except (ResearchError, OSError, ValueError, RuntimeError) as error:
            build_result = mo.callout(mo.md(f"Не удалось построить индекс: {error}"), kind="danger")
        else:
            build_result = mo.vstack(
                [
                    mo.md("### Индекс готов: извлечены признаки, модель не обучалась"),
                    mo.ui.table(
                        [{"Фото в индексе": index_report["build"]["record_count"],
                          "Пропущено без метки": index_report["build"]["unknown_samples_excluded"],
                          "Куда сохранено": index_report["output"]}],
                        selection=None, pagination=False, show_data_types=False,
                    ),
                ]
            )
    build_result
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Оценка качества

    Каждое фото сравнивается только с эталонами **других групп**. Смотрите отдельно ошибки в названии дефекта и более опасные случаи: повреждение есть, но прогноз — «норма».
    """)
    return


@app.cell(hide_code=True)
def _(audit_rows, mo, oof_metrics):
    comparison = oof_metrics(audit_rows)
    if comparison is None:
        evaluation_result = mo.callout(
            mo.md("**Grouped OOF не вычислено.** Нет прошедших проверку cross-fitted прогнозов; kNN, Ridge и MLP не подменяют отсутствующий артефакт друг другом."),
            kind="warn",
        )
    else:
        method_names = {
            "knn_k5": "kNN (k=5)",
            "linear_ridge": "Linear Ridge",
            "supervised_mlp": "Supervised MLP",
        }
        comparison_rows = []
        confusion_rows = []
        class_rows = []
        for method, title in method_names.items():
            values = comparison[method]
            condition = values["condition"]
            object_type = values["object_type"]
            binary = values["condition_binary_damage_vs_normal"]
            comparison_rows.append({
                "Модель": title,
                "Покрытие": f"{condition['covered_count']}/{condition['count']} ({condition['coverage']:.1%})",
                "Тип · accuracy": f"{object_type['accuracy']:.3f}",
                "Тип · macro-F1": f"{object_type['macro_f1']:.3f}",
                "Состояние · accuracy": f"{condition['accuracy']:.3f}",
                "Состояние · macro-F1": f"{condition['macro_f1']:.3f}",
                "Бинарный TP/FP/FN/TN": f"{binary['tp']}/{binary['fp']}/{binary['fn']}/{binary['tn']}",
                "Повреждение→норма": values["false_normal"],
                "Бинарный precision / recall / F1": f"{binary['precision']:.3f} / {binary['recall']:.3f} / {binary['f1']:.3f}",
            })
            for target, target_name in (("object_type", "Тип объекта"), ("condition", "Исходная метка состояния")):
                metrics = values[target]
                labels = metrics["labels"]
                matrix = metrics["confusion_matrix"]
                for actual in labels:
                    confusion_rows.append(
                        {"Модель": title, "Цель": target_name, "По МГТС ↓": actual}
                        | {predicted: matrix[actual][predicted] for predicted in labels + ["не вычислено"]}
                    )
                for label, score in metrics["per_class"].items():
                    class_rows.append({
                        "Модель": title,
                        "Цель": target_name,
                        "Класс": label,
                        "Образцов": score["support"],
                        "Precision": f"{score['precision']:.3f}",
                        "Recall": f"{score['recall']:.3f}",
                        "F1": f"{score['f1']:.3f}",
                        "TP/FP/FN/TN": f"{score['tp']}/{score['fp']}/{score['fn']}/{score['tn']}",
                    })
        evaluation_result = mo.vstack([
            mo.callout(
                mo.md("Проверка воспроизводит **leave-one-object-or-exact-SHA-group-out** на 61 размеченном фото и 60 объединённых группах; unknown исключён. kNN, Ridge и MLP получают одни и те же held-out фото. Ridge и MLP переобучены внутри каждого train-fold на frozen features: по 60 фото / 59 групп на fold; полный head не оценивался как independent test."),
                kind="warn",
            ),
            mo.ui.table(comparison_rows, selection=None, pagination=False, show_search=False,
                        show_data_types=False, show_download=False, label="Сравнение моделей · grouped OOF"),
            mo.md("### Ошибки: строки — исходная метка, столбцы — прогноз"),
            mo.ui.table(confusion_rows, selection=None, pagination=False, show_search=False,
                        show_data_types=False, show_download=False),
            mo.md("### Метрики по классам"),
            mo.ui.table(class_rows, selection=None, pagination=False, show_search=False,
                        show_data_types=False, show_download=False),
            mo.md("**Критическое ограничение:** 61 кадр из небольшой организаторской выборки, 60 ID/SHA-групп; нет независимой полевой выборки. Высокая точность здесь не доказывает переносимость. Любой FN требует отдельной проверки специалистом."),
        ])
    evaluation_result
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Дополнительно: своё фото

    Выберите один JPEG, PNG или WebP: под ним появится прогноз и ближайшие размеченные примеры. Снимок обрабатывается локально, без отправки во внешний ИИ-сервис.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    query_image = mo.ui.file(filetypes=[".jpg", ".jpeg", ".png", ".webp"],
                             max_size=10_000_000, label="Фото для анализа (до 10 МБ)")
    mo.accordion({"Загрузить своё фото (необязательно)": query_image})
    return (query_image,)


@app.cell(hide_code=True)
def _(
    BytesIO,
    Image,
    ResearchError,
    condition_ru,
    embed_photo,
    hashlib,
    load_embedder,
    load_material_manifest,
    load_material_sample,
    load_reference_index,
    mo,
    preview_image_bytes,
    query_image,
    audit_rows, mlp_path, predict_upload_head, sha256_file,
    index_path,
    model_path,
    manifest_path,
    retrieve,
):
    if not query_image.value:
        query_result = mo.md("")
    else:
        uploads = query_image.value
        if not uploads:
            query_result = mo.callout(mo.md("Сначала выберите одну фотографию."), kind="danger")
        else:
            upload = uploads[0]
            try:
                reference_index = load_reference_index(index_path)
                embedder = load_embedder(model_path)
                vector = embed_photo(embedder, upload.name, upload.contents)
                uploaded_sha256 = hashlib.sha256(upload.contents).hexdigest()
                _known = next((r for r in audit_rows if r["sample"]["sha256"] == uploaded_sha256), None)
                matches = retrieve(
                    reference_index,
                    vector,
                    top_k=5,
                    exclude_sha256=uploaded_sha256,
                    exclude_group_id=_known["group_id"] if _known else None,
                )
                if _known and _known["evaluation_status"] == "evaluated":
                    _mlp = _known["predictions"]["supervised_mlp"]
                elif _known and _known["true"]["condition"] != "unknown":
                    _mlp = None
                else:
                    try:
                        _mlp = predict_upload_head(mlp_path, vector, checkpoint_sha256=sha256_file(model_path))
                    except (ValueError, OSError):
                        _mlp = None
                query_materials = load_material_manifest(manifest_path)
                with Image.open(BytesIO(upload.contents)) as source_image:
                    upload_preview = preview_image_bytes(source_image)
            except (ResearchError, OSError, ValueError, RuntimeError) as error:
                query_result = mo.callout(mo.md(f"Не удалось сравнить фотографию: {error}"), kind="danger")
            else:
                result_parts = [
                    mo.image(
                        BytesIO(upload_preview),
                        alt="Исходная загруженная фотография, показана в компактном размере",
                        width="100%",
                    ),
                    mo.md("### Предварительный результат"),
                    mo.ui.table(
                        [{"Модель":"kNN", "Тип объекта": matches["tentative"]["object_type"] or "Не определён",
                          "Состояние": condition_ru.get(matches["tentative"]["condition"], "Не определено"),
                          "Рекомендация": "Проверить вручную"},
                         {"Модель":"MLP", "Тип объекта": (_mlp or {}).get("object_type") or "Не вычислено",
                          "Состояние": condition_ru.get((_mlp or {}).get("condition"), "Не вычислено"),
                          "Рекомендация":"Проверить вручную"}],
                        selection=None, pagination=False, show_data_types=False,
                    ),
                    mo.md("Ниже — похожие размеченные фото. Сходство не равно вероятности повреждения."),
                ]
                manifest_indices = {
                    sample["image_path"]: sample_index
                    for sample_index, sample in enumerate(query_materials["samples"])
                }
                for match in matches["matches"]:
                    reference_row = manifest_indices.get(match["image_path"])
                    if reference_row is None:
                        continue
                    reference = load_material_sample(query_materials["path"], reference_row)
                    source = reference["sample"]
                    result_parts.append(
                        mo.vstack(
                            [
                                mo.md(
                                    f"**Похожий исходный пример (сходство {match['similarity']:.3f}, не вероятность):** "
                                    f"{source['object_type']} · {condition_ru.get(source['condition'], 'Без разметки')} · "
                                    f"{source['object_id']} · {source['source_folder']}"
                                ),
                                mo.image(
                                    BytesIO(preview_image_bytes(reference["image"])),
                                    alt="Исходная фотография похожего размеченного примера, компактный показ",
                                    width="100%",
                                ),
                                mo.md(f"Статус: {source['status']}\n\nОписание: {source['description']}"),
                            ]
                        )
                    )
                query_result = mo.vstack(result_parts)
    query_result
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Что проверить перед обучением

    1. **Разметка.** У фото есть подпись о состоянии, но нет рамок дефектов. Повреждение корпуса и покрытия могут встречаться вместе.
    2. **Выборка.** Фото одного объекта и точные дубли нельзя делить между обучением и проверкой. Кадр без разметки не считается исправным.
    3. **Критерий.** Сравнивайте precision и recall по каждому виду повреждений и отдельно считайте повреждённые объекты, которые алгоритм назвал нормальными. До полевой проверки решение о ремонте принимает специалист.
    """)
    return


if __name__ == "__main__":
    app.run()
