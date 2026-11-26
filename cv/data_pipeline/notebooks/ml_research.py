"""Editable, human-centered MGTS cabinet photo review and ML workspace."""

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _():
    import hashlib
    import os
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
    return (
        BytesIO,
        Image,
        ResearchError,
        binary_damage_summary,
        build_reference_index,
        embed_photo,
        evaluate_leave_group_out,
        hashlib,
        index_path,
        load_embedder,
        load_material_manifest,
        load_material_sample,
        load_reference_index,
        manifest_path,
        model_path,
        mo,
        preview_image_bytes,
        retrieve,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Осмотр шкафов и распределительных щитов МГТС

    **Первый снимок уже открыт.** Выберите другой в списке: исходное фото, прогноз модели и ближайший пример сменятся автоматически. Загружать датасет не нужно.
    Для проверки нового снимка используйте раздел **«Сравнить фотографию»**.
    Разметка МГТС — эталон; результат алгоритма — предварительная рекомендация.
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
def _(ResearchError, condition_ru, load_material_manifest, manifest_path, mo):
    """Read only the small JSON inventory on open; do not open photos here."""
    try:
        materials = load_material_manifest(manifest_path)
    except (ResearchError, OSError, ValueError) as error:
        materials = None
        inventory_message = mo.callout(
            mo.md(f"Не удалось прочитать подготовленный реестр фотографий: {error}"),
            kind="danger",
        )
        photo_options = {}
    else:
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
        inventory_message = mo.ui.table(
            _rows, selection=None, pagination=False, show_search=False,
            show_column_summaries=False, show_data_types=False,
            label=f"Состав выборки · {materials['sample_count']} фото",
        )
        photo_options = {
            (
                f"{sample['object_type']} · {condition_ru.get(sample['condition'], 'Без разметки')} · "
                f"{sample['object_id']} · {sample['source_folder']}"
            ): index
            for index, sample in enumerate(materials["samples"])
        }
    inventory_message
    return materials, photo_options


@app.cell(hide_code=True)
def _(materials, mo, photo_options):
    if not photo_options:
        photo_picker = None
        photo_selector = mo.md("Фотографии недоступны: проверьте реестр и каталог исходных снимков.")
    else:
        photo_picker = mo.ui.dropdown(
            options=photo_options,
            value=next(iter(photo_options)),
            searchable=True,
            label="Выберите фотографию по типу объекта, исходной метке, ID и папке",
        )
        photo_selector = photo_picker
    photo_selector
    return (photo_picker,)


@app.cell(hide_code=True)
def _(index_path, load_reference_index):
    try:
        cabinet_index = load_reference_index(index_path)
        by_sha = {r["sha256"]: r for r in cabinet_index["records"]}
        index_error = None
    except (ValueError, OSError) as _err:
        cabinet_index, by_sha, index_error = None, {}, str(_err)
    return by_sha, cabinet_index, index_error


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Фото и прогноз

    Слева — выбранное фото, его разметка МГТС и прогноз алгоритма. Справа — ближайший пример, по которому можно проверить вывод. При сравнении известного фото исключается вся группа этого объекта. **Рамок дефекта нет:** метод оценивает снимок целиком, а не место повреждения.
    """)
    return


@app.cell(hide_code=True)
def _(BytesIO, ResearchError, by_sha, cabinet_index, condition_ru, embed_photo, index_error, load_embedder, load_material_sample, materials, mo, model_path, photo_picker, preview_image_bytes, retrieve):
    if materials is None or photo_picker is None or photo_picker.value is None:
        photo_review = mo.md("Нет фото для просмотра.")
    else:
        try:
            _sample = load_material_sample(materials["path"], photo_picker.value)
            _rec = _sample["sample"]
            _preview = mo.image(
                BytesIO(preview_image_bytes(_sample["image"], max_edge=800, max_bytes=45000)),
                alt="Выбранное фото МГТС", width="100%",
            )
            _truth = condition_ru.get(_rec["condition"], "Без разметки")
            _left = [mo.md(f"**Фото № {_rec['object_id']}**"), _preview,
                     mo.md(f"**Разметка МГТС:** {_rec['object_type']} · {_truth}"),
                     mo.plain(_rec["description"] or "Описание не предоставлено")]
            if cabinet_index is None:
                photo_review = mo.vstack(_left + [mo.callout(mo.md(f"Прогноз недоступен: {index_error}"), kind="warn")])
            else:
                _cached = by_sha.get(_sample["sha256"])
                _vec = (_cached["embedding"] if _cached else embed_photo(
                    load_embedder(model_path), _rec["image_path"], _sample["image_bytes"]))
                _prediction = retrieve(cabinet_index, _vec, top_k=5,
                    exclude_sha256=_sample["sha256"], exclude_object_id=_rec["object_id"],
                    exclude_group_id=_cached["group_id"] if _cached else None)
                _type = _prediction["tentative"]["object_type"] or "Не определён"
                _condition = condition_ru.get(_prediction["tentative"]["condition"], "Не определено")
                _left += [mo.md(f"**Прогноз модели:** {_type} · {_condition}"),
                          mo.md("**Действие:** требуется проверка специалиста.")]
                _matches = _prediction["matches"]
                if _matches:
                    _nearest = _matches[0]
                    _idx = next(i for i,r in enumerate(materials["samples"]) if r["image_path"] == _nearest["image_path"])
                    _ref = load_material_sample(materials["path"], _idx)
                    _right = [mo.md(f"**Ближайший пример · № {_nearest['object_id']}**"),
                              mo.image(BytesIO(preview_image_bytes(_ref["image"], max_edge=800, max_bytes=45000)),
                                       alt="Ближайший эталон, найденный моделью", width="100%"),
                              mo.md(f"**Разметка эталона:** {_nearest['object_type']} · "
                                    f"{condition_ru.get(_nearest['condition'], 'Без разметки')}"),
                              mo.md(f"Косинусное сходство: **{_nearest['similarity']:.3f}** (не вероятность).")]
                    photo_review = mo.hstack([mo.vstack(_left), mo.vstack(_right)], widths="equal", align="start")
                else:
                    photo_review = mo.vstack(_left)
        except (ResearchError, OSError, ValueError, RuntimeError, StopIteration) as _err:
            photo_review = mo.callout(mo.md(f"Не удалось сравнить выбранное фото с эталонами: {_err}"), kind="danger")
    photo_review
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Как работает поиск по разметке

    Оценка по готовому индексу выводится автоматически. Только построение нового индекса требует подтверждения.
    Существующий checkpoint не обучался на шкафах или их повреждениях. Здесь
    он используется только как источник
    векторных признаков для поиска похожих примеров. Сходство — **не
    вероятность, не диагноз и не прогноз ремонта**. Никакие веса не скачиваются,
    модель не переобучается, файлы фотографий не копируются в индекс.
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
def _(ResearchError, binary_damage_summary, cabinet_index, evaluate_leave_group_out, mo):
    if cabinet_index is None:
        evaluation_result = mo.md("Для оценки нужен готовый индекс примеров.")
    else:
        try:
            evaluation = evaluate_leave_group_out(cabinet_index, top_k=5)
        except (ResearchError, OSError, ValueError, RuntimeError) as error:
            evaluation_result = mo.callout(mo.md(f"Не удалось оценить индекс: {error}"), kind="danger")
        else:
            def metric_table(label: str, metrics: dict) -> tuple[object, object]:
                classes = metrics["labels"]
                columns = classes + (["unretrieved"] if metrics["no_independent_reference"] else [])
                confusion = metrics["confusion_matrix"]
                class_rows = []
                for class_name in classes:
                    true_positive = confusion[class_name][class_name]
                    support = sum(confusion[class_name].values())
                    false_positive = sum(
                        confusion[other].get(class_name, 0)
                        for other in classes
                        if other != class_name
                    )
                    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
                    recall = true_positive / support if support else 0.0
                    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
                    class_rows.append(
                        {
                            "Класс": class_name,
                            "Образцов": support,
                            "Precision": f"{precision:.3f}",
                            "Recall": f"{recall:.3f}",
                            "F1": f"{f1:.3f}",
                        }
                    )
                confusion_rows = [
                    {"Исходный класс ↓ / найденный пример →": actual}
                    | {predicted: confusion[actual][predicted] for predicted in columns}
                    for actual in classes
                ]
                class_table = mo.ui.table(
                    class_rows,
                    selection=None,
                    show_search=False,
                    show_data_types=False,
                    show_download=False,
                    label=f"Метрики по классам: {label}",
                )
                confusion_table = mo.ui.table(
                    confusion_rows,
                    selection=None,
                    show_search=False,
                    show_data_types=False,
                    show_download=False,
                    label=f"Таблица ошибок: {label}",
                )
                return class_table, confusion_table

            object_tables = metric_table("тип объекта", evaluation["metrics"]["object_type"])
            condition_metrics = evaluation["metrics"]["condition"]
            condition_tables = metric_table("исходная метка состояния", condition_metrics)
            dispatcher = binary_damage_summary(condition_metrics)
            if dispatcher is None:
                dispatch_view = mo.callout(
                    mo.md(
                        "Диспетчерская сводка «повреждение / исходно нормальное» не рассчитана: "
                        "в наборе должны присутствовать все три исходные метки `coating_damage`, "
                        "`mechanical_damage` и `normal`."
                    ),
                    kind="warn",
                )
            else:
                dispatch_view = mo.ui.table(
                    [
                        {
                            "TP": dispatcher["tp"],
                            "FP": dispatcher["fp"],
                            "FN": dispatcher["fn"],
                            "TN": dispatcher["tn"],
                            "Не классифицировано": dispatcher["unclassified"],
                            "Precision": f"{dispatcher['precision']:.3f}",
                            "Recall": f"{dispatcher['recall']:.3f}",
                            "F1": f"{dispatcher['f1']:.3f}",
                        }
                    ],
                    selection=None,
                    show_search=False,
                    show_data_types=False,
                    show_download=False,
                    label="Диспетчерская сводка: повреждение против исходно нормального",
                )
            evaluation_result = mo.vstack(
                [
                    mo.callout(
                        mo.md(
                            "Только исследовательская оценка малого набора с группировкой по ID/SHA-256. "
                            "Это не независимая полевая проверка и не гарантия качества на новых районах."
                        ),
                        kind="warn",
                    ),
                    mo.md(
                        f"Проверено образцов: **{evaluation['reference_count']}**; независимых групп ID/SHA-256: "
                        f"**{evaluation['groups']}**. Точность поиска по типу объекта: "
                        f"**{evaluation['metrics']['object_type']['accuracy']:.3f}**; по исходной метке состояния: "
                        f"**{evaluation['metrics']['condition']['accuracy']:.3f}**; macro-F1 по трём исходным меткам: "
                        f"**{evaluation['metrics']['condition']['macro_f1']:.3f}**. "
                        "Эти цифры описывают только текущий небольшой набор."
                    ),
                    mo.md("### Диспетчерская бинарная сводка: два вида повреждения объединены против `normal`"),
                    dispatch_view,
                    mo.md("### Тип объекта: метрики по классам"),
                    object_tables[0],
                    mo.md("#### Матрица ошибок: строки — исходные подписи, столбцы — найденная подпись"),
                    object_tables[1],
                    mo.md("### Исходная метка состояния: метрики по классам"),
                    condition_tables[0],
                    mo.md("#### Матрица ошибок: строки — исходные подписи, столбцы — найденная подпись"),
                    condition_tables[1],
                    mo.md("**Ограничения:**\n\n" + "\n".join(f"- {item}" for item in evaluation["limitations"])),
                ]
            )
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
                matches = retrieve(
                    reference_index,
                    vector,
                    top_k=5,
                    exclude_sha256=uploaded_sha256,
                )
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
                        [{"Тип объекта": matches["tentative"]["object_type"] or "Не определён",
                          "Состояние": condition_ru.get(matches["tentative"]["condition"], "Не определено"),
                          "Рекомендация": "Проверить вручную"}],
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
