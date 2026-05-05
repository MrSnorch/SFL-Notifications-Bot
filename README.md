# 🌻 SFL Farm Notifier — Мульти-пользовательская версия

Бот для мониторинга ферм Sunflower Land. Каждый пользователь настраивает
свою ферму прямо в Telegram — уведомления приходят в личку.

## Архитектура

```
Telegram Bot (команды пользователей)
        ↕
   Supabase (хранит пользователей, настройки, состояние)
        ↕
GitHub Actions (сканер + бот работают бесплатно)
        ↕
Telegram DM (личные сообщения каждому пользователю)
```

**Бесплатно:** публичный GitHub репозиторий = безлимитные Actions минуты.

---

## Установка — 4 шага

### 1. Создать бота в Telegram

1. Написать [@BotFather](https://t.me/BotFather)
2. `/newbot` → дать имя → получить токен: `7123456789:AAF...`
3. `/setcommands` → вставить:
```
start - Начать / перерегистрироваться
setfarm - Установить ID фермы
setkey - Установить API ключ
settings - Настройки отслеживания
status - Статус фермы прямо сейчас
stop - Приостановить уведомления
resume - Возобновить уведомления
help - Помощь
```

### 2. Создать базу данных в Supabase

1. Зайти на [supabase.com](https://supabase.com) → New project
2. В SQL Editor выполнить содержимое `supabase_schema.sql`
3. Скопировать из Settings → API:
   - **Project URL** → `SUPABASE_URL`
   - **anon public** key → `SUPABASE_KEY`

### 3. Залить на GitHub

```bash
git init
git add .
git commit -m "SFL Notifier multi-user"
git remote add origin https://github.com/ТВОЙакк/sfl-notifier
git push -u origin main
```

⚠️ Репозиторий должен быть **публичным** (для бесплатных Actions).

### 4. Добавить секреты в GitHub

`Settings → Secrets and variables → Actions → New repository secret`:

| Имя | Значение |
|-----|---------|
| `TELEGRAM_BOT_TOKEN` | Токен от BotFather |
| `SUPABASE_URL` | URL проекта из Supabase |
| `SUPABASE_KEY` | anon key из Supabase |

### 5. Запустить

В GitHub → Actions:
- **SFL Bot** → Run workflow (запустить вручную первый раз)
- **SFL Scanner** → Run workflow (запустить вручную первый раз)

Дальше они будут перезапускаться автоматически каждые 6 часов.

---

## Как пользователи подключаются

1. Найти бота в Telegram по @username
2. `/start`
3. `/setfarm 12345` — ID фермы (число из URL на сайте)
4. `/setkey abc123...` — API ключ (бот сразу удалит сообщение)
5. Готово! Первый статус придёт в течение 5 минут.

---

## Что получают пользователи

**Статус-сообщение** (обновляется без уведомления):
```
🌻 Ферма 12345

🌾 Sunflower [3] — через 00:45:23 — 14:30
🪵 Trees [5] — через 01:12:00 — 15:00
🍎 Apple [2] — через 3д 12:00:00 — завтра

✅ Готово к сбору:
  🌾 Carrot [2/4]

Обновлено: 05.05 13:44
```

**Алерт** (с уведомлением) когда что-то готово:
```
🌾 Carrot [4/4] — готово к сбору ✅
```

Алерт удаляется автоматически когда пользователь собрал урожай.

---

## Файлы проекта

| Файл | Описание |
|------|---------|
| `sfl_core.py` | Логика сканирования фермы, константы роста |
| `sfl_supabase.py` | Клиент Supabase (REST API) |
| `sfl_scanner.py` | Мульти-пользовательский сканер |
| `sfl_bot.py` | Telegram бот с командами |
| `supabase_schema.sql` | SQL схема базы данных |
| `.github/workflows/scanner.yml` | Workflow сканера |
| `.github/workflows/bot.yml` | Workflow бота |

---

## FAQ

**Как долго работают jobs?**
Каждый job работает ~5ч 50м, потом GitHub автоматически запускает следующий по cron.

**Есть ли задержка при рестарте?**
До 10 минут каждые 6 часов — GitHub Actions запускается не мгновенно.

**Максимум пользователей?**
Supabase free tier: 500MB хватит на тысячи пользователей.
GitHub Actions: параллельные jobs без лимита для публичных репо.

**Пользователи видят API ключи друг друга?**
Нет. Каждый ключ привязан к telegram_id. RLS в Supabase защищает данные.
