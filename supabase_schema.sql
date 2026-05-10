-- ============================================================
-- SFL Notifier — Supabase Schema
-- Выполни это в SQL Editor: https://supabase.com/dashboard
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    -- Telegram user ID (он же chat_id для личных сообщений)
    telegram_id   BIGINT PRIMARY KEY,

    -- Данные из Telegram
    username      TEXT    DEFAULT '',
    first_name    TEXT    DEFAULT '',

    -- X (Twitter) аккаунт для отслеживания Share & Earn
    x_username    TEXT    DEFAULT '',

    -- Настройки фермы
    farm_id       TEXT    DEFAULT '',
    api_key       TEXT    DEFAULT '',   -- шифруем на уровне Row Security

    -- Что отслеживать (json объект)
    tracking      JSONB   DEFAULT '{
        "crops":      true,
        "trees":      true,
        "stones":     true,
        "iron":       true,
        "gold":       true,
        "crimstones": false,
        "oil":        false,
        "salt":       true,
        "sunstones":  false,
        "fruits":     true,
        "flowers":    true,
        "honey":      true,
        "mushrooms":  false,
        "animals":    false
    }'::jsonb,

    -- Состояние: status_msg_id, ready_alerts
    state         JSONB   DEFAULT '{}'::jsonb,

    -- Активен ли мониторинг
    active        BOOLEAN DEFAULT FALSE,

    -- Флаг: был ли юзер уже запущен в матрице/runner
    -- FALSE = новый юзер, ожидает запуска launcher'ом
    -- TRUE  = runner уже работает (выставляет prepare / full run)
    scanner_dispatched BOOLEAN DEFAULT FALSE,

    -- Служебные поля
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Автообновление updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS users_updated_at ON users;
CREATE TRIGGER users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- Индексы
CREATE INDEX IF NOT EXISTS idx_users_active ON users(active) WHERE active = TRUE;
CREATE INDEX IF NOT EXISTS idx_users_pending_dispatch ON users(active, scanner_dispatched)
    WHERE active = TRUE AND scanner_dispatched = FALSE;

-- ============================================================
-- Миграция для существующих баз (выполни если таблица уже есть)
-- ============================================================
-- ALTER TABLE users ADD COLUMN IF NOT EXISTS scanner_dispatched BOOLEAN DEFAULT FALSE;
-- UPDATE users SET scanner_dispatched = TRUE WHERE active = TRUE;
-- ALTER TABLE users ADD COLUMN IF NOT EXISTS x_username TEXT DEFAULT '';

-- ============================================================
-- Row Level Security
-- Включи RLS и разреши только service_role (твой бот/сканер
-- использует anon key с правами ниже, либо service_role key)
-- ============================================================

-- RLS включён. Публичных политик нет намеренно.
-- Бот/сканер использует SUPABASE_SERVICE_KEY из GitHub Secrets,
-- который обходит RLS полностью. Никогда не кладите service_role key
-- в клиентский код или Telegram-сообщения.
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- Проверка после создания
-- ============================================================
-- SELECT * FROM users;
-- SELECT count(*) FROM users WHERE active = true;
