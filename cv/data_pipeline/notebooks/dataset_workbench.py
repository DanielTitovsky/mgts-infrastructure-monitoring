"""Local Marimo form for the existing MGTS dataset CLI."""

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    from mgts_data_pipeline.cli import DEFAULT_ARCHIVE_ROOT, DEFAULT_HUB_ROOT
    from mgts_data_pipeline.errors import PipelineError
    from mgts_data_pipeline.registry import SOURCE_IDS
    from mgts_data_pipeline.workbench import run_submission

    return (
        DEFAULT_ARCHIVE_ROOT,
        DEFAULT_HUB_ROOT,
        PipelineError,
        SOURCE_IDS,
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
def _(DEFAULT_ARCHIVE_ROOT, DEFAULT_HUB_ROOT, SOURCE_IDS, mo):
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
        value="/tmp/mgts-normalized-broken-poles-ui",
        label="Новый каталог результата (только normalize; перезапись запрещена)",
    )
    validation_path = mo.ui.text(
        value="/tmp/mgts-normalized-broken-poles-ui",
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


if __name__ == "__main__":
    app.run()
