-- init.sql
BEGIN;


-- users
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    email       VARCHAR(255) NOT NULL UNIQUE,
    phone       VARCHAR(50),
    username    VARCHAR(100) NOT NULL UNIQUE,
    role        VARCHAR(50)  NOT NULL DEFAULT 'user',
    update_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

-- statuses
CREATE TABLE IF NOT EXISTS statuses (
    id          SERIAL PRIMARY KEY,
    type        VARCHAR(100) NOT NULL,
    description TEXT
);

-- infrastructure_objects
CREATE TABLE IF NOT EXISTS infrastructure_objects (
    id          SERIAL PRIMARY KEY,
    "imgUrl"    TEXT,
    type        VARCHAR(100),
    "statusId"  INTEGER REFERENCES statuses(id) ON DELETE SET NULL,
    place       TEXT
);

COMMIT;