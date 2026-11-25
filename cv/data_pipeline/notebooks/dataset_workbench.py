"""Local Marimo form for the existing MGTS dataset CLI."""

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import os
    import marimo as mo

    from mgts_data_pipeline.cli import DEFAULT_ARCHIVE_ROOT, DEFAULT_HUB_ROOT
    from mgts_data_pipeline.errors import PipelineError
    from mgts_data_pipeline.inference import InferenceError, MAX_IMAGE_BYTES, infer_photo
    from mgts_data_pipeline.registry import SOURCE_IDS
    from mgts_data_pipeline.workbench import DEFAULT_OUTPUT_PATH, run_submission

    model_path = os.environ.get("MGTS_MODEL_PATH", "/models/best.pt")
    return (
        DEFAULT_ARCHIVE_ROOT,
        DEFAULT_HUB_ROOT,
        DEFAULT_OUTPUT_PATH,
        InferenceError,
        MAX_IMAGE_BYTES,
        PipelineError,
        SOURCE_IDS,
        infer_photo,
        model_path,
        mo,
        run_submission,
    )


@app.cell
def _(mo):
    mo.md("""
    # Подготовка датасетов МГТС

    Локальная панель над `mgts-datasets`: аудит источников, загрузка,
    нормализация и проверка готового набора. **Операция запускается только
    после отправки формы внизу** — открытие панели и изменение полей ничего
    не загружают и не обрабатывают.

    Это не обучение модели: классы не смешиваются, исходные файлы не
    перезаписываются, снимки здесь не показываются. Для закрытого Hub нужен
    `HF_TOKEN` в окружении процесса; токен не вводится в форму.

    ### Ограничения источников

    - `broken_poles_v2` выбран по умолчанию: это проверенный стартовый
      вариант, но он **train-only** и не подходит для честной оценки без
      отдельной валидационной выборки.
    - `pd_defect` размечает наклон столба, а не поломку; исходные снимки
      сделаны со смартфона и перенос на кадры с автомобиля не проверен.
    - `utility_pole_y8w7k_v3` использует `Compromised-Pole/Stable` — это не
      те же классы, что `broken/normal`.
    - `ohl_uk` и `streetlevel_poles` — обнаружение объектов, не дефектов;
      у выбранного OHL-UK Fold 0 нет тестовой части.
    - `powerline_faults` требует явной карантинизации невалидных строк и
      всё ещё блокируется конфликтующими дубликатами разметки.
    - `all` намеренно не предлагается: этот общий запуск сейчас не является
      рабочим рецептом. Источники и их словари классов остаются раздельными.
    """)
    return


@app.cell
def _(DEFAULT_ARCHIVE_ROOT, DEFAULT_HUB_ROOT, DEFAULT_OUTPUT_PATH, SOURCE_IDS, mo):
    action = mo.ui.dropdown(
        options=["inspect", "fetch", "normalize", "validate"],
        value="inspect",
        label="Действие",
    )
    sources = mo.ui.multiselect(
        options=list(SOURCE_IDS),
        value=["broken_poles_v2"],
        label="Источники (для inspect / fetch / normalize)",
    )
    archive_root = mo.ui.text(value=str(DEFAULT_ARCHIVE_ROOT), label="Папка ZIP-архивов")
    hub_root = mo.ui.text(value=str(DEFAULT_HUB_ROOT), label="Локальный кэш Hugging Face")
    output_path = mo.ui.text(
        value=str(DEFAULT_OUTPUT_PATH),
        label="Новый каталог результата (только normalize; перезапись запрещена)",
    )
    validation_path = mo.ui.text(
        value=str(DEFAULT_OUTPUT_PATH),
        label="Каталог для validate",
    )
    strict_invalid = mo.ui.checkbox(label="Остановиться на первой невалидной разметке")
    quarantine_invalid = mo.ui.checkbox(
        label="Разрешить карантин невалидных строк Powerline (конфликт дубликатов всё равно остановит запуск)"
    )

    submitted_form = mo.ui.form(
        mo.md(
            """
            ### Настройки

            **Действие** {action}

            **Источники** {sources}

            **Архивы** {archive_root}

            **Кэш Hub** {hub_root}

            **Каталог результата** {output_path}

            **Каталог проверки** {validation_path}

            {strict_invalid}

            {quarantine_invalid}
            """
        ).batch(
            action=action,
            sources=sources,
            archive_root=archive_root,
            hub_root=hub_root,
            output_path=output_path,
            validation_path=validation_path,
            strict_invalid=strict_invalid,
            quarantine_invalid=quarantine_invalid,
        ),
        submit_button_label="Выполнить выбранное действие",
        bordered=True,
    )
    submitted_form
    return (submitted_form,)


@app.cell
def _(PipelineError, mo, run_submission, submitted_form):
    if submitted_form.value is None:
        output = mo.md("Ничего не запускалось. Выбери действие и нажми кнопку отправки формы.")
    else:
        try:
            report = run_submission(submitted_form.value)
        except (PipelineError, OSError, ValueError) as error:
            output = mo.vstack(
                [
                    mo.callout(mo.md("Операция завершилась ошибкой."), kind="danger"),
                    mo.plain(str(error)),
                ]
            )
        else:
            output = mo.vstack([mo.md("### Результат (структурированный отчёт)"), mo.json(report)])
    output
    return


@app.cell
def _(MAX_IMAGE_BYTES, mo):
    photo_upload = mo.ui.file(
        filetypes=[".jpg", ".jpeg", ".png", ".webp"],
        max_size=MAX_IMAGE_BYTES,
        label="Фото (JPEG, PNG или WebP; до 10 MB)",
    )
    photo_form = mo.ui.form(
        mo.md("""
        ### Распознавание объектов на фото (опционально)

        Загрузи одно фото и явно отправь форму. Изменение поля само по себе
        ничего не запускает. Модель локально обнаруживает объекты класса
        odn_pole; это не оценка повреждений и не измерение точности.

        Ultralytics 8.4.214 использует лицензию AGPL-3.0
        ([исходный код и лицензия](https://github.com/ultralytics/ultralytics/blob/main/LICENSE)).
        Источник и лицензия данных обучения этого checkpoint в репозитории
        не зафиксированы.

        **Файл** {photo}
        """).batch(photo=photo_upload),
        submit_button_label="Найти столбы на фото",
        bordered=True,
    )
    photo_form
    return (photo_form,)


@app.cell
def _(InferenceError, infer_photo, mo, model_path, photo_form):
    if photo_form.value is None:
        photo_output = mo.md("Загрузи фото и нажми кнопку отправки, чтобы выполнить локальное распознавание.")
    else:
        uploaded_files = photo_form.value["photo"]
        if not uploaded_files:
            photo_output = mo.callout(mo.md("Сначала выбери фото."), kind="danger")
        else:
            uploaded = uploaded_files[0]
            try:
                photo_report = infer_photo(
                    filename=uploaded.name,
                    contents=uploaded.contents,
                    model_path=model_path,
                )
            except InferenceError as error:
                photo_output = mo.callout(mo.md(str(error)), kind="danger")
            else:
                photo_output = mo.vstack(
                    [
                        mo.md("### Результат (класс, confidence, bbox в пикселях)"),
                        mo.json(photo_report),
                    ]
                )
    photo_output
    return


if __name__ == "__main__":
    app.run()
