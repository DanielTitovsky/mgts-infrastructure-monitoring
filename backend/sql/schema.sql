-- Дополнение к корневому migrations.sql.
-- Файл идемпотентный: применяется при старте приложения (DB_BOOTSTRAP=true).

-- Пользователям нужен хеш пароля для входа.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);

-- Объектам нужны внешний идентификатор и координаты для карты.
ALTER TABLE infrastructure_objects
    ADD COLUMN IF NOT EXISTS external_id VARCHAR(100),
    ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS lon DOUBLE PRECISION;

-- Очередь обработки фото ИИ-воркером.
-- processing_status: awaiting_processing -> processing -> done|failed.
ALTER TABLE infrastructure_objects
    ADD COLUMN IF NOT EXISTS processing_status VARCHAR(32),
    ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS processing_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS processing_error TEXT,
    ADD COLUMN IF NOT EXISTS processed_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS processed_img_url TEXT;

CREATE INDEX IF NOT EXISTS infrastructure_objects_processing_status_idx
    ON infrastructure_objects (processing_status);

-- Признаки дефектов, найденные воркером/ИИ.
CREATE TABLE IF NOT EXISTS defects (
    id                  SERIAL PRIMARY KEY,
    object_id           INTEGER REFERENCES infrastructure_objects(id) ON DELETE SET NULL,
    detection_id        INTEGER,
    defect_type         VARCHAR(100) NOT NULL,
    defect_confidence   DOUBLE PRECISION,
    severity            VARCHAR(50),
    recommended_action  VARCHAR(50),
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Догоняем колонки, добавленные в модель после первого создания таблицы:
-- bbox — рамка дефекта в долях изображения, source — откуда дефект ('cv' или 'manual').
ALTER TABLE defects
    ADD COLUMN IF NOT EXISTS bbox JSONB,
    ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'manual';

CREATE INDEX IF NOT EXISTS defects_object_id_idx
    ON defects (object_id);

CREATE INDEX IF NOT EXISTS infrastructure_objects_status_id_idx
    ON infrastructure_objects ("statusId");

-- Статус для случая, когда фото обработано, но модель ничего не распознала.
-- Вставляется идемпотентно при каждом старте API/воркера.
INSERT INTO statuses (type, description)
SELECT 'unrecognized', 'Не распознано'
WHERE NOT EXISTS (SELECT 1 FROM statuses WHERE type = 'unrecognized');
