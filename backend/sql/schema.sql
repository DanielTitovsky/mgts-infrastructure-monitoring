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
