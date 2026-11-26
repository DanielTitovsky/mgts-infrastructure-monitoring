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
def _(ResearchError, load_material_manifest, manifest_path, mo):
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
        inventory_message = mo.vstack(
            [
                mo.md(
                    "## Реестр: 62 фотографии шкафов и распределительных щитов\n\n"
                    "Подписи взяты из папок и исходных таблиц: 21 механическое повреждение, "
                    "20 дефектов ЛКП, 20 исходно удовлетворительных объектов и 1 неизвестный снимок. "
                    "Это метки уровня фотографии, **рамок объектов нет**. ЛКП и механические дефекты "
                    "могут сосуществовать; `unknown` не означает «норма»."
                ),
                mo.callout(
                    mo.md(
                        "**Человеческая проверка обязательна.** Отдельно указывайте объект, "
                        "наблюдаемое состояние и рекомендацию по осмотру/ремонту. Сходство или "
                        "уверенность модели не означает исправность и не является основанием для выезда."
                    ),
                    kind="warn",
                ),
                mo.json(
                    {
                        "объект": materials["summary"]["object_type"],
                        "исходная метка состояния": materials["summary"]["condition"],
                        "разбиение": materials["summary"]["split"],
                        "предупреждения источника": materials["warnings"],
                    }
                ),
            ]
        )
        photo_options = {
            (
                f"{sample['object_type']} · {sample['condition']} · "
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
def _(ResearchError, load_material_sample, materials, mo, photo_picker):
    if materials is None or photo_picker is None or photo_picker.value is None:
        photo_review = mo.md("Выберите фото, чтобы открыть оригинал и подписи источника.")
    else:
        try:
            selected_sample = load_material_sample(materials["path"], photo_picker.value)
        except (ResearchError, OSError, ValueError) as error:
            photo_review = mo.callout(mo.md(f"Не удалось открыть фотографию: {error}"), kind="danger")
        else:
            record = selected_sample["sample"]
            photo_review = mo.vstack(
                [
                    mo.image(
                        BytesIO(preview_image_bytes(selected_sample["image"])),
                        alt="Оригинальная фотография объекта, показана в компактном размере",
                        width="100%",
                    ),
                    mo.callout(mo.md(selected_sample["warning"]), kind="warn"),
                    mo.md("### Исходные подписи — не результат распознавания"),
                    mo.json(
                        {
                            "тип объекта": record["object_type"],
                            "исходная метка состояния": record["condition"],
                            "исходная папка": record["source_folder"],
                            "ID объекта": record["object_id"],
                            "статус из таблицы": record["status"],
                            "описание из таблицы": record["description"],
                            "папочная метка": record.get("folder_condition"),
                            "размер пикселей": [selected_sample["width"], selected_sample["height"]],
                            "разбиение": record.get("split", "unassigned"),
                            "bbox": None,
                        }
                    ),
                ]
            )
    photo_review
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Эксперимент: локальный поиск похожих фотографий

    Следующие кнопки запускают вычисления только после отправки формы.
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
    build_form
    return (build_form,)


@app.cell(hide_code=True)
def _(ResearchError, build_form, build_reference_index, mo):
    if build_form.value is None:
        build_result = mo.md("Индекс ещё не строился. Для явного CPU-запуска отправьте форму выше.")
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
                    mo.json(
                        {
                            "путь": index_report["output"],
                            "образцов": index_report["build"]["record_count"],
                            "исключено неизвестных": index_report["build"]["unknown_samples_excluded"],
                            "checkpoint_sha256": index_report["provenance"]["checkpoint_sha256"],
                            "ограничения": index_report["limitations"],
                        }
                    ),
                ]
            )
    build_result
    return


@app.cell(hide_code=True)
def _(index_path, mo):
    evaluate_path = mo.ui.text(value=index_path, label="Существующий локальный индекс")
    evaluate_form = mo.ui.form(
        mo.md("Индекс: {index}").batch(index=evaluate_path),
        submit_button_label="Оценить поиск с исключением всей группы object_id / SHA-256",
        bordered=True,
    )
    evaluate_form
    return (evaluate_form,)


@app.cell(hide_code=True)
def _(ResearchError, evaluate_form, evaluate_leave_group_out, mo):
    if evaluate_form.value is None:
        evaluation_result = mo.md("Оценка не запускалась. Отправьте форму с существующим индексом.")
    else:
        try:
            evaluation = evaluate_leave_group_out(evaluate_form.value["index"], top_k=5)
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
def _(index_path, manifest_path, model_path, mo):
    query_image = mo.ui.file(
        filetypes=[".jpg", ".jpeg", ".png", ".webp"],
        max_size=10_000_000,
        label="Одна фотография JPEG/PNG/WebP (до 10 МБ и 20 Мп)",
    )
    query_index = mo.ui.text(value=index_path, label="Существующий локальный индекс")
    query_checkpoint = mo.ui.text(value=model_path, label="Доверенный локальный checkpoint")
    query_manifest = mo.ui.text(value=manifest_path, label="Реестр для показа похожих исходных фотографий")
    query_limit = mo.ui.number(value=5, start=1, stop=10, step=1, label="Число примеров для сравнения: 1–10")
    query_form = mo.ui.form(
        mo.md("Фото: {photo}\n\nИндекс: {index}\n\nCheckpoint: {checkpoint}\n\nРеестр: {manifest}\n\nПримеры: {limit}").batch(
            photo=query_image,
            index=query_index,
            checkpoint=query_checkpoint,
            manifest=query_manifest,
            limit=query_limit,
        ),
        submit_button_label="Сравнить фотографию с локальными примерами",
        bordered=True,
    )
    query_form
    return (query_form,)


@app.cell(hide_code=True)
def _(
    BytesIO,
    Image,
    ResearchError,
    embed_photo,
    hashlib,
    load_embedder,
    load_material_manifest,
    load_material_sample,
    load_reference_index,
    mo,
    preview_image_bytes,
    query_form,
    retrieve,
):
    if query_form.value is None:
        query_result = mo.md("Сравнение не выполнялось. Выберите фото и явно отправьте форму.")
    else:
        uploads = query_form.value["photo"]
        if not uploads:
            query_result = mo.callout(mo.md("Сначала выберите одну фотографию."), kind="danger")
        else:
            upload = uploads[0]
            try:
                reference_index = load_reference_index(query_form.value["index"])
                embedder = load_embedder(query_form.value["checkpoint"])
                vector = embed_photo(embedder, upload.name, upload.contents)
                uploaded_sha256 = hashlib.sha256(upload.contents).hexdigest()
                matches = retrieve(
                    reference_index,
                    vector,
                    top_k=query_form.value["limit"],
                    exclude_sha256=uploaded_sha256,
                )
                query_materials = load_material_manifest(query_form.value["manifest"])
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
                    mo.callout(mo.md(matches["message"]), kind="warn"),
                    mo.json(
                        {
                            "ориентир по ближайшим примерам": matches["tentative"],
                            "нужна проверка специалиста": matches["needs_review"],
                            "сходство — вероятность": matches["similarity_is_probability"],
                            "автоматическая рекомендация ремонта": matches["automated_repair"],
                        }
                    ),
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
                                    f"{source['object_type']} · {source['condition']} · "
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
def _(manifest_path, mo):
    mo.md(r"""
    ## Черновик будущего воспроизводимого эксперимента

    Набор мал и не имеет выделенных train/validation/test частей. Сначала —
    просмотр первичных фото и grouped leave-one-object-ID-out retrieval,
    не обучение детектора. Если позже появится классификатор изображения,
    отдельно зафиксируйте цель (тип объекта **или** состояние), исключите
    `unknown`, удерживайте одинаковые `object_id` вместе независимо от папки
    и типа, проверьте пересечение SHA-256, назначьте нетронутую тестовую группу
    до любых экспериментов. Текущий checkpoint не является готовым
    классификатором шкафов.
    """)
    EXPERIMENT_RECIPE = {
        "manifest": manifest_path,
        "task": "image-level retrieval baseline; no supervised training implemented",
        "separate_targets": ["object_type", "condition"],
        "unknown_policy": "exclude_and_report; never convert to normal",
        "group_key": "global object_id plus exact-content SHA-256 closure",
        "held_out_splits": "human-assigned grouped train/validation/test before fitting",
        "checkpoint": "existing trusted local file only; no download",
        "training_run": False,
        "epochs": None,
        "automated_repair_recommendation": False,
    }
    mo.json(EXPERIMENT_RECIPE)
    return (EXPERIMENT_RECIPE,)


if __name__ == "__main__":
    app.run()
