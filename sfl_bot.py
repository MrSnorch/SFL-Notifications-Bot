#!/usr/bin/env python3
"""
sfl_bot.py — Telegram бот для управления настройками SFL Notifier.

Команды:
  /start   — регистрация
  /setfarm — установить ID фермы
  /setkey  — установить API ключ (бот удалит сообщение)
  /settings — настройки отслеживания (inline кнопки)
  /status  — текущий статус фермы прямо сейчас
  /stop    — приостановить уведомления
  /resume  — возобновить уведомления
  /lang    — сменить язык / change language / змінити мову
  /help    — помощь

Бот использует long-polling и работает в цикле 5ч 50м.
GitHub Actions перезапускает его каждые 6 часов по cron.
"""

import json, os, sys, time, logging

def _pip(pkg):
    os.system(f'"{sys.executable}" -m pip install {pkg} -q')

try:
    import requests
except ImportError:
    _pip("requests"); import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("SFL_BOT")

from sfl_core import (
    scan_farm, load_from_api, format_status_message,
    DEFAULT_TRACKING, TRACK_LABELS,
    discover_dynamic_resources, merge_discovered,
    TIMEZONES, get_tz, tz_display_name,
    panel_keyboard,
)
from sfl_supabase import (
    get_or_create_user, get_user, update_user,
    activate_user_if_ready, upsert_user,
)

TG_TOKEN       = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
SHARED_API_KEY = os.environ.get("SFL_API_KEY", "").strip()
GH_TOKEN       = os.environ.get("GH_DISPATCH_TOKEN", "").strip()
GH_REPO        = os.environ.get("GH_REPOSITORY", "").strip()   # формат: owner/repo
GH_BRANCH      = os.environ.get("GH_BRANCH", "main").strip()
API_BASE = f"https://api.telegram.org/bot{TG_TOKEN}"

def dispatch_new_user_runner(telegram_id: int):
    """Запускает scanner_matrix.yml для нового юзера через GitHub API dispatch.
    Не бросает исключений — фейл логируется и игнорируется."""
    if not GH_TOKEN or not GH_REPO:
        log.warning("GH_DISPATCH_TOKEN или GH_REPOSITORY не заданы — dispatch пропущен")
        return
    url = f"https://api.github.com/repos/{GH_REPO}/actions/workflows/scanner_matrix.yml/dispatches"
    payload = {"ref": GH_BRANCH, "inputs": {"single_user": str(telegram_id)}}
    try:
        r = requests.post(url, json=payload,
                          headers={"Authorization": f"Bearer {GH_TOKEN}",
                                   "Accept": "application/vnd.github+json"},
                          timeout=10)
        if r.status_code == 204:
            log.info(f"[dispatch] 🚀 Runner запущен для юзера {telegram_id}")
        else:
            log.warning(f"[dispatch] GitHub ответил {r.status_code}: {r.text[:200]}")
    except Exception as e:
        log.warning(f"[dispatch] Ошибка запуска runner: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# ЛОКАЛИЗАЦИЯ
# ══════════════════════════════════════════════════════════════════════════════

SUPPORTED_LANGS = {
    "ru": ("🇷🇺", "Русский"),
    "en": ("🇬🇧", "English"),
    "uk": ("🇺🇦", "Українська"),
}

DEFAULT_LANG = "ru"

STRINGS = {
    "welcome": {
        "ru": (
            "🌻 <b>SFL Farm Notifier</b>\n\n"
            "Привет! Я буду следить за твоей фермой в Sunflower Land и присылать уведомления когда ресурсы готовы.\n\n"
            "Введи <b>ID своей фермы</b> (только цифры):"
        ),
        "en": (
            "🌻 <b>SFL Farm Notifier</b>\n\n"
            "Hello! I'll monitor your Sunflower Land farm and send notifications when resources are ready.\n\n"
            "Please enter your <b>Farm ID</b> (numbers only):"
        ),
        "uk": (
            "🌻 <b>SFL Farm Notifier</b>\n\n"
            "Привіт! Я стежитиму за твоєю фермою у Sunflower Land і надсилатиму сповіщення, коли ресурси готові.\n\n"
            "Введи <b>ID своєї ферми</b> (тільки цифри):"
        ),
    },
    "help": {
        "ru": (
            "🌻 <b>SFL Farm Notifier — Команды</b>\n\n"
            "/start — перезапустить бота\n"
            "/setfarm <code>ID</code> — установить ID фермы\n"
            "/settings — настроить что отслеживать\n"
            "/status — проверить ферму прямо сейчас\n"
            "/stop — приостановить уведомления\n"
            "/resume — возобновить уведомления\n"
            "/lang — сменить язык\n"
            "/reset — сбросить все данные и начать заново\n"
            "/help — это сообщение"
        ),
        "en": (
            "🌻 <b>SFL Farm Notifier — Commands</b>\n\n"
            "/start — restart the bot\n"
            "/setfarm <code>ID</code> — set farm ID\n"
            "/settings — configure what to track\n"
            "/status — check farm right now\n"
            "/stop — pause notifications\n"
            "/resume — resume notifications\n"
            "/lang — change language\n"
            "/reset — reset all data and start over\n"
            "/help — this message"
        ),
        "uk": (
            "🌻 <b>SFL Farm Notifier — Команди</b>\n\n"
            "/start — перезапустити бота\n"
            "/setfarm <code>ID</code> — встановити ID ферми\n"
            "/settings — налаштувати що відстежувати\n"
            "/status — перевірити ферму прямо зараз\n"
            "/stop — призупинити сповіщення\n"
            "/resume — поновити сповіщення\n"
            "/lang — змінити мову\n"
            "/reset — скинути всі дані та почати заново\n"
            "/help — це повідомлення"
        ),
    },
    "reset_confirm": {
        "ru": "⚠️ <b>Полный сброс</b>\n\nЭто удалит твои данные: ферма, ключ, все настройки и состояние бота.\nПосле сброса бот запустится заново.\n\nПродолжить?",
        "en": "⚠️ <b>Full reset</b>\n\nThis will delete your data: farm, key, all settings and bot state.\nAfter reset the bot will restart.\n\nContinue?",
        "uk": "⚠️ <b>Повне скидання</b>\n\nЦе видалить твої дані: ферма, ключ, всі налаштування та стан бота.\nПісля скидання бот запуститься заново.\n\nПродовжити?",
    },
    "reset_done": {
        "ru": "✅ Данные сброшены.",
        "en": "✅ Data has been reset.",
        "uk": "✅ Дані скинуто.",
    },
    "reset_cancel": {
        "ru": "❌ Сброс отменён.",
        "en": "❌ Reset cancelled.",
        "uk": "❌ Скидання скасовано.",
    },
    "reset_yes_btn": {"ru": "✅ Да, сбросить", "en": "✅ Yes, reset", "uk": "✅ Так, скинути"},
    "reset_no_btn":  {"ru": "❌ Отмена",        "en": "❌ Cancel",     "uk": "❌ Скасувати"},
    "setfarm_usage": {
        "ru": "❌ Укажи ID фермы:\n<code>/setfarm 12345</code>",
        "en": "❌ Please provide your farm ID:\n<code>/setfarm 12345</code>",
        "uk": "❌ Вкажи ID ферми:\n<code>/setfarm 12345</code>",
    },
    "setfarm_not_number": {
        "ru": "❌ ID фермы должен быть числом.\nПример: <code>/setfarm 12345</code>",
        "en": "❌ Farm ID must be a number.\nExample: <code>/setfarm 12345</code>",
        "uk": "❌ ID ферми має бути числом.\nПриклад: <code>/setfarm 12345</code>",
    },
    "setfarm_ok_active": {
        "ru": "✅ Ферма <b>{farm_id}</b> установлена!\n\n🔔 Уведомления <b>включены</b> — первый статус придёт через несколько минут.",
        "en": "✅ Farm <b>{farm_id}</b> has been set!\n\n🔔 Notifications <b>enabled</b> — first status update will arrive in a few minutes.",
        "uk": "✅ Ферму <b>{farm_id}</b> встановлено!\n\n🔔 Сповіщення <b>увімкнено</b> — перший статус надійде за кілька хвилин.",
    },
    "setfarm_ok_pending": {
        "ru": "✅ Ферма <b>{farm_id}</b> установлена!\n\n⏳ Осталось указать API ключ:\n<code>/setkey твой_ключ</code>",
        "en": "✅ Farm <b>{farm_id}</b> has been set!\n\n⏳ Now provide your API key:\n<code>/setkey your_key</code>",
        "uk": "✅ Ферму <b>{farm_id}</b> встановлено!\n\n⏳ Залишилось вказати API ключ:\n<code>/setkey твій_ключ</code>",
    },
    "setkey_usage": {
        "ru": "❌ Укажи API ключ:\n<code>/setkey твой_ключ</code>",
        "en": "❌ Please provide your API key:\n<code>/setkey your_key</code>",
        "uk": "❌ Вкажи API ключ:\n<code>/setkey твій_ключ</code>",
    },
    "setkey_ok_active": {
        "ru": "✅ API ключ сохранён! (твоё сообщение удалено для безопасности)\n\n🔔 Уведомления <b>включены</b> — первый статус придёт через несколько минут.",
        "en": "✅ API key saved! (your message was deleted for security)\n\n🔔 Notifications <b>enabled</b> — first status update will arrive in a few minutes.",
        "uk": "✅ API ключ збережено! (твоє повідомлення видалено для безпеки)\n\n🔔 Сповіщення <b>увімкнено</b> — перший статус надійде за кілька хвилин.",
    },
    "setkey_ok_need_farm": {
        "ru": "✅ API ключ сохранён! (твоё сообщение удалено для безопасности)\n\n⏳ Осталось указать ID фермы:\n<code>/setfarm 12345</code>",
        "en": "✅ API key saved! (your message was deleted for security)\n\n⏳ Now provide your farm ID:\n<code>/setfarm 12345</code>",
        "uk": "✅ API ключ збережено! (твоє повідомлення видалено для безпеки)\n\n⏳ Залишилось вказати ID ферми:\n<code>/setfarm 12345</code>",
    },
    "setkey_ok": {
        "ru": "✅ API ключ сохранён! (твоё сообщение удалено для безопасности)",
        "en": "✅ API key saved! (your message was deleted for security)",
        "uk": "✅ API ключ збережено! (твоє повідомлення видалено для безпеки)",
    },
    "settings_title": {
        "ru": "⚙️ <b>Настройки отслеживания</b>\n\nВыбери что отслеживать:",
        "en": "⚙️ <b>Tracking Settings</b>\n\nChoose what to track:",
        "uk": "⚙️ <b>Налаштування відстеження</b>\n\nОбери що відстежувати:",
    },
    "settings_dynamic_note": {
        "ru": "\n\n🔍 <i>Найдено новых ресурсов: {count}</i>",
        "en": "\n\n🔍 <i>New resources found: {count}</i>",
        "uk": "\n\n🔍 <i>Знайдено нових ресурсів: {count}</i>",
    },
    "settings_saved": {
        "ru": "✅ Сохранено!",
        "en": "✅ Saved!",
        "uk": "✅ Збережено!",
    },
    "settings_saved_title": {
        "ru": "✅ <b>Настройки сохранены!</b>",
        "en": "✅ <b>Settings saved!</b>",
        "uk": "✅ <b>Налаштування збережено!</b>",
    },
    "settings_btn_save": {
        "ru": "💾 Сохранить и закрыть",
        "en": "💾 Save and close",
        "uk": "💾 Зберегти і закрити",
    },
    "settings_btn_back": {
        "ru": "◀️ Назад к настройкам",
        "en": "◀️ Back to settings",
        "uk": "◀️ Назад до налаштувань",
    },
    "show_clock_btn": {
        "ru": "⏱ Формат времени: {label}",
        "en": "⏱ Time format: {label}",
        "uk": "⏱ Формат часу: {label}",
    },
    "time_format_menu_title": {
        "ru": "⏱ <b>Формат времени в статусе</b>\n\nКак показывать время до готовности:",
        "en": "⏱ <b>Time format in status</b>\n\nHow to display time until ready:",
        "uk": "⏱ <b>Формат часу у статусі</b>\n\nЯк показувати час до готовності:",
    },
    "time_format_both": {
        "ru": "⏱ через 6м — 05:45",
        "en": "⏱ in 6m — 05:45",
        "uk": "⏱ через 6хв — 05:45",
    },
    "time_format_countdown": {
        "ru": "⏱ через 6м",
        "en": "⏱ in 6m",
        "uk": "⏱ через 6хв",
    },
    "time_format_clock": {
        "ru": "🕐 05:45",
        "en": "🕐 05:45",
        "uk": "🕐 05:45",
    },
    "setfarm_btn_change": {
        "ru": "🏡 Изменить ферму: {farm_id}",
        "en": "🏡 Change farm: {farm_id}",
        "uk": "🏡 Змінити ферму: {farm_id}",
    },
    "setfarm_prompt": {
        "ru": "🏡 <b>Изменить ID фермы</b>\n\nТекущий: <code>{farm_id}</code>\n\nОтправь мне новый ID фермы (только цифры):",
        "en": "🏡 <b>Change Farm ID</b>\n\nCurrent: <code>{farm_id}</code>\n\nSend me your new farm ID (numbers only):",
        "uk": "🏡 <b>Змінити ID ферми</b>\n\nПоточний: <code>{farm_id}</code>\n\nНадішли мені новий ID ферми (тільки цифри):",
    },
    "setfarm_prompt_cancel": {
        "ru": "❌ Отмена",
        "en": "❌ Cancel",
        "uk": "❌ Скасувати",
    },
    "setfarm_changed": {
        "ru": "✅ Ферма изменена на <b>{farm_id}</b>",
        "en": "✅ Farm changed to <b>{farm_id}</b>",
        "uk": "✅ Ферму змінено на <b>{farm_id}</b>",
    },
    "setfarm_invalid": {
        "ru": "❌ ID фермы должен быть числом. Попробуй снова:",
        "en": "❌ Farm ID must be a number. Try again:",
        "uk": "❌ ID ферми має бути числом. Спробуй ще раз:",
    },
    "settings_unknown_resource": {
        "ru": "Неизвестный ресурс",
        "en": "Unknown resource",
        "uk": "Невідомий ресурс",
    },
    "repeat_btn_label": {
        "ru": "🔁 Повторы: {count}× / {interval}м",
        "en": "🔁 Repeats: {count}× / {interval}m",
        "uk": "🔁 Повтори: {count}× / {interval}хв",
    },
    "repeat_btn_off_label": {
        "ru": "🔕 Повторы: выкл",
        "en": "🔕 Repeats: off",
        "uk": "🔕 Повтори: вимк",
    },
    "repeat_off_btn": {
        "ru": "🔕 Выкл",
        "en": "🔕 Off",
        "uk": "🔕 Вимк",
    },
    "repeat_on_btn": {
        "ru": "🔔 Вкл",
        "en": "🔔 On",
        "uk": "🔔 Увімк",
    },
    "repeat_off_toast": {
        "ru": "🔕 Повторы отключены",
        "en": "🔕 Repeats disabled",
        "uk": "🔕 Повтори вимкнено",
    },
    "repeat_on_toast": {
        "ru": "🔔 Повторы включены",
        "en": "🔔 Repeats enabled",
        "uk": "🔔 Повтори увімкнено",
    },
    "repeat_menu_title": {
        "ru": "🔁 <b>Повтор уведомлений</b>\n\nЕсли не собрал — напомним ещё раз.",
        "en": "🔁 <b>Repeat notifications</b>\n\nWe'll remind you again if not collected.",
        "uk": "🔁 <b>Повтор сповіщень</b>\n\nНагадаємо ще раз, якщо не зібрав.",
    },
    "repeat_count_label": {
        "ru": "🔁 Повторов:",
        "en": "🔁 Repeats:",
        "uk": "🔁 Повторів:",
    },
    "repeat_interval_label": {
        "ru": "⏳ Інтервал:",
        "en": "⏳ Interval:",
        "uk": "⏳ Інтервал:",
    },
    "repeat_count_toast": {
        "ru": "🔔 Повторов: {n}×",
        "en": "🔔 Repeats: {n}×",
        "uk": "🔔 Повторів: {n}×",
    },
    "repeat_interval_toast": {
        "ru": "⏱ Интервал: {m}м",
        "en": "⏱ Interval: {m}m",
        "uk": "⏱ Інтервал: {m}хв",
    },
    "repeat_summary": {
        "ru": "🔁 Повторов: {count}× / каждые {interval}м",
        "en": "🔁 Repeats: {count}× / every {interval}m",
        "uk": "🔁 Повторів: {count}× / кожні {interval}хв",
    },
    "repeat_summary_off": {
        "ru": "🔕 Повторы: выкл",
        "en": "🔕 Repeats: off",
        "uk": "🔕 Повтори: вимк",
    },
    "status_no_farm": {
        "ru": "❌ Ферма не настроена.\nИспользуй /setfarm и /setkey",
        "en": "❌ Farm is not set up.\nUse /setfarm and /setkey",
        "uk": "❌ Ферму не налаштовано.\nВикористай /setfarm та /setkey",
    },
    "status_loading": {
        "ru": "⏳ Загружаю данные фермы...",
        "en": "⏳ Loading farm data...",
        "uk": "⏳ Завантажую дані ферми...",
    },
    "status_error": {
        "ru": "❌ Ошибка при загрузке фермы:\n<code>{error}</code>",
        "en": "❌ Error loading farm:\n<code>{error}</code>",
        "uk": "❌ Помилка при завантаженні ферми:\n<code>{error}</code>",
    },
    "status_new_resources": {
        "ru": "🔍 <b>Найдены новые ресурсы для отслеживания:</b> {labels}\nВключи их в /settings если нужно.",
        "en": "🔍 <b>New trackable resources found:</b> {labels}\nEnable them in /settings if needed.",
        "uk": "🔍 <b>Знайдено нові ресурси для відстеження:</b> {labels}\nУвімкни їх у /settings якщо потрібно.",
    },
    "not_registered": {
        "ru": "❌ Сначала зарегистрируйся: /start",
        "en": "❌ Please register first: /start",
        "uk": "❌ Спочатку зареєструйся: /start",
    },
    "stop_ok": {
        "ru": "⏸️ Уведомления <b>приостановлены</b>.\nЧтобы возобновить — /resume",
        "en": "⏸️ Notifications <b>paused</b>.\nTo resume — /resume",
        "uk": "⏸️ Сповіщення <b>призупинено</b>.\nЩоб поновити — /resume",
    },
    "resume_no_farm": {
        "ru": "❌ Сначала настрой ферму:\n/setfarm и /setkey",
        "en": "❌ Please set up your farm first:\n/setfarm and /setkey",
        "uk": "❌ Спочатку налаштуй ферму:\n/setfarm та /setkey",
    },
    "resume_ok": {
        "ru": "▶️ Уведомления <b>возобновлены</b>!\nПервый статус придёт через несколько минут.",
        "en": "▶️ Notifications <b>resumed</b>!\nFirst status update will arrive in a few minutes.",
        "uk": "▶️ Сповіщення <b>поновлено</b>!\nПерший статус надійде за кілька хвилин.",
    },
    "lang_choose": {
        "ru": "🌐 <b>Выбери язык</b>\n\nТекущий язык: <b>{current}</b>",
        "en": "🌐 <b>Choose language</b>\n\nCurrent language: <b>{current}</b>",
        "uk": "🌐 <b>Обери мову</b>\n\nПоточна мова: <b>{current}</b>",
    },
    "lang_set": {
        "ru": "✅ Язык изменён на <b>{lang_name}</b>",
        "en": "✅ Language changed to <b>{lang_name}</b>",
        "uk": "✅ Мову змінено на <b>{lang_name}</b>",
    },
    "tz_title": {
        "ru": "🕐 <b>Выбери часовой пояс</b>\n\nТекущий: <b>{current_tz}</b>\n\nВремя в статусе и уведомлениях будет отображаться в выбранном поясе.",
        "en": "🕐 <b>Choose timezone</b>\n\nCurrent: <b>{current_tz}</b>\n\nStatus and notification times will be shown in the selected timezone.",
        "uk": "🕐 <b>Оберіть часовий пояс</b>\n\nПоточний: <b>{current_tz}</b>\n\nЧас у статусі та сповіщеннях буде відображатися у вибраному поясі.",
    },
    "tz_btn_label": {
        "ru": "🕐 Часовой пояс: {tz}",
        "en": "🕐 Timezone: {tz}",
        "uk": "🕐 Часовий пояс: {tz}",
    },
    "tz_saved_toast": {
        "ru": "✅ {tz}",
        "en": "✅ {tz}",
        "uk": "✅ {tz}",
    },
    "repeat_list_title": {
        "ru": "🔁 <b>Повторы уведомлений по ресурсам</b>\n\nНастрой повторы отдельно для каждого ресурса.\nРесурсы без настройки используют <b>глобальный</b> повтор.",
        "en": "🔁 <b>Repeat notifications per resource</b>\n\nConfigure repeats for each resource individually.\nResources without a setting use the <b>global</b> repeat.",
        "uk": "🔁 <b>Повтори сповіщень по ресурсах</b>\n\nНалаштуй повтори окремо для кожного ресурсу.\nРесурси без налаштування використовують <b>глобальний</b> повтор.",
    },
    "repeat_global_btn": {
        "ru": "⚙️ По умолчанию: {summary}",
        "en": "⚙️ Default: {summary}",
        "uk": "⚙️ За замовч.: {summary}",
    },
    "repeat_res_btn": {
        "ru": "{label} — {summary}",
        "en": "{label} — {summary}",
        "uk": "{label} — {summary}",
    },
    "repeat_res_title": {
        "ru": "🔁 <b>Повторы: {label}</b>\n\nНастройки повтора именно для этого ресурса.\nЕсли выкл — используется глобальный повтор.",
        "en": "🔁 <b>Repeats: {label}</b>\n\nRepeat settings for this resource specifically.\nIf off — the global repeat is used.",
        "uk": "🔁 <b>Повтори: {label}</b>\n\nНалаштування повтору саме для цього ресурсу.\nЯкщо вимк — використовується глобальний повтор.",
    },
    "repeat_res_reset_btn": {
        "ru": "↩️ Сбросить (использовать глобальный)",
        "en": "↩️ Reset (use global setting)",
        "uk": "↩️ Скинути (використати глобальний)",
    },
    "repeat_res_reset_toast": {
        "ru": "↩️ Сброшено — используется глобальный повтор",
        "en": "↩️ Reset — using global repeat",
        "uk": "↩️ Скинуто — використовується глобальний повтор",
    },
    "repeat_inherited": {
        "ru": "глоб.",
        "en": "global",
        "uk": "глоб.",
    },
    "unknown_command": {
        "ru": "❓ Неизвестная команда.\n",
        "en": "❓ Unknown command.\n",
        "uk": "❓ Невідома команда.\n",
    },
    "callback_not_registered": {
        "ru": "Сначала /start",
        "en": "Please /start first",
        "uk": "Спочатку /start",
    },

    # ── Twitter Gift ────────────────────────────────────────────────────────
    "twitter_gift_btn": {
        "ru": "🐦 Twitter Gift",
        "en": "🐦 Twitter Gift",
        "uk": "🐦 Twitter Gift",
    },
    "twitter_gift_title": {
        "ru": (
            "🐦 <b>Twitter Gift</b>\n\n"
            "Делай твит каждые 7 дней и получай награду в игре!\n\n"
            "{status}"
        ),
        "en": (
            "🐦 <b>Twitter Gift</b>\n\n"
            "Post on Twitter every 7 days and earn in-game rewards!\n\n"
            "{status}"
        ),
        "uk": (
            "🐦 <b>Twitter Gift</b>\n\n"
            "Роби твіт кожні 7 днів та отримуй нагороду в грі!\n\n"
            "{status}"
        ),
    },
    "twitter_gift_status_disabled": {
        "ru": "❌ <b>Статус:</b> отключено",
        "en": "❌ <b>Status:</b> disabled",
        "uk": "❌ <b>Статус:</b> вимкнено",
    },
    "twitter_gift_status_no_post": {
        "ru": "⚠️ <b>Статус:</b> включено, но дата последнего поста не задана\n\nНажми «📅 Задать дату последнего поста» чтобы начать отсчёт.",
        "en": "⚠️ <b>Status:</b> enabled, but last post date is not set\n\nPress «📅 Set last post date» to start the timer.",
        "uk": "⚠️ <b>Статус:</b> увімкнено, але дата останнього посту не задана\n\nНатисни «📅 Задати дату останнього посту» щоб почати відлік.",
    },
    "twitter_gift_status_ready": {
        "ru": "✅ <b>Статус:</b> <b>ГОТОВО К СБОРУ!</b>\n\nНажми «✅ Выполнено» после публикации твита.",
        "en": "✅ <b>Status:</b> <b>READY TO COLLECT!</b>\n\nPress «✅ Done» after posting your tweet.",
        "uk": "✅ <b>Статус:</b> <b>ГОТОВО ДО ЗБОРУ!</b>\n\nНатисни «✅ Виконано» після публікації твіту.",
    },
    "twitter_gift_status_countdown": {
        "ru": "⏳ <b>Статус:</b> следующий твит через <b>{countdown}</b>\n\nПоследний пост: {last_post}",
        "en": "⏳ <b>Status:</b> next tweet in <b>{countdown}</b>\n\nLast post: {last_post}",
        "uk": "⏳ <b>Статус:</b> наступний твіт через <b>{countdown}</b>\n\nОстанній пост: {last_post}",
    },
    "twitter_gift_btn_enable": {
        "ru": "✅ Включить",
        "en": "✅ Enable",
        "uk": "✅ Увімкнути",
    },
    "twitter_gift_btn_disable": {
        "ru": "❌ Отключить",
        "en": "❌ Disable",
        "uk": "❌ Вимкнути",
    },
    "twitter_gift_btn_done": {
        "ru": "✅ Выполнено (сброс таймера)",
        "en": "✅ Done (reset timer)",
        "uk": "✅ Виконано (скинути таймер)",
    },
    "twitter_gift_btn_set_time": {
        "ru": "📅 Задать дату последнего поста",
        "en": "📅 Set last post date",
        "uk": "📅 Задати дату останнього посту",
    },
    "twitter_gift_done_toast": {
        "ru": "✅ Таймер сброшен! Следующий твит через 7 дней.",
        "en": "✅ Timer reset! Next tweet in 7 days.",
        "uk": "✅ Таймер скинуто! Наступний твіт через 7 днів.",
    },
    "twitter_gift_enabled_toast": {
        "ru": "🐦 Twitter Gift включён",
        "en": "🐦 Twitter Gift enabled",
        "uk": "🐦 Twitter Gift увімкнено",
    },
    "twitter_gift_disabled_toast": {
        "ru": "🐦 Twitter Gift отключён",
        "en": "🐦 Twitter Gift disabled",
        "uk": "🐦 Twitter Gift вимкнено",
    },
    "twitter_gift_set_time_prompt": {
        "ru": (
            "📅 <b>Дата и время последнего твита</b>\n\n"
            "Введи дату и время в формате:\n"
            "<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
            "Примеры:\n"
            "<code>07.05.2026 04:07</code>\n"
            "<code>2026-05-07 04:07</code>\n\n"
            "Время вводится в твоём часовом поясе ({tz})."
        ),
        "en": (
            "📅 <b>Last tweet date and time</b>\n\n"
            "Enter the date and time in format:\n"
            "<code>DD.MM.YYYY HH:MM</code>\n\n"
            "Examples:\n"
            "<code>07.05.2026 04:07</code>\n"
            "<code>2026-05-07 04:07</code>\n\n"
            "Time is in your timezone ({tz})."
        ),
        "uk": (
            "📅 <b>Дата і час останнього твіту</b>\n\n"
            "Введи дату і час у форматі:\n"
            "<code>ДД.ММ.РРРР ГГ:ХХ</code>\n\n"
            "Приклади:\n"
            "<code>07.05.2026 04:07</code>\n"
            "<code>2026-05-07 04:07</code>\n\n"
            "Час вказується у твоєму часовому поясі ({tz})."
        ),
    },
    "twitter_gift_set_time_invalid": {
        "ru": "❌ Не удалось распознать дату. Попробуй ещё раз:\n<code>07.05.2026 04:07</code> или <code>2026-05-07 04:07</code>",
        "en": "❌ Could not parse the date. Try again:\n<code>07.05.2026 04:07</code> or <code>2026-05-07 04:07</code>",
        "uk": "❌ Не вдалось розпізнати дату. Спробуй ще раз:\n<code>07.05.2026 04:07</code> або <code>2026-05-07 04:07</code>",
    },
    "twitter_gift_set_time_ok": {
        "ru": "✅ Дата сохранена! Отсчёт начался.",
        "en": "✅ Date saved! Timer started.",
        "uk": "✅ Дату збережено! Відлік розпочато.",
    },
    "twitter_gift_btn_cancel": {
        "ru": "❌ Отмена",
        "en": "❌ Cancel",
        "uk": "❌ Скасувати",
    },
}


def t(key, lang, **kwargs):
    """Вернуть строку на нужном языке с подстановкой параметров."""
    lang = lang if lang in SUPPORTED_LANGS else DEFAULT_LANG
    variants = STRINGS.get(key, {})
    text = variants.get(lang) or variants.get(DEFAULT_LANG, "[{}]".format(key))
    return text.format(**kwargs) if kwargs else text


def get_lang(user):
    """Вернуть язык пользователя из state."""
    if not user:
        return DEFAULT_LANG
    state = user.get("state") or {}
    lang = state.get("lang", DEFAULT_LANG)
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM API HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def tg(method, **kwargs):
    try:
        polling_timeout = kwargs.get("timeout", 0)
        http_timeout = polling_timeout + 10 if polling_timeout else 20
        r = requests.post(f"{API_BASE}/{method}", json=kwargs, timeout=http_timeout)
        if r.ok:
            return r.json().get("result")
        log.warning(f"TG {method} failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        log.warning(f"TG {method} error: {e}")
    return None


def send(chat_id, text, reply_markup=None, silent=False):
    kwargs = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_notification": silent,
    }
    if reply_markup:
        kwargs["reply_markup"] = reply_markup
    return tg("sendMessage", **kwargs)


def edit_text(chat_id, message_id, text, reply_markup=None):
    kwargs = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        kwargs["reply_markup"] = reply_markup
    return tg("editMessageText", **kwargs)


def answer_callback(callback_query_id, text=""):
    tg("answerCallbackQuery",
       callback_query_id=callback_query_id, text=text, show_alert=False)


def delete_msg(chat_id, message_id):
    tg("deleteMessage", chat_id=chat_id, message_id=message_id)

def track_msg(chat_id, message_id):
    """Сохранить ID сервисного сообщения для последующей очистки."""
    user = get_user(chat_id)
    if not user:
        return
    state = user.get("state") or {}
    ids = state.get("service_msg_ids", [])
    ids.append(message_id)
    state["service_msg_ids"] = ids[-200:]  # хранить последние 200
    update_user(chat_id, state=state)


def send_service(chat_id, text, reply_markup=None, silent=False):
    """Отправить сообщение и запомнить его ID (для возможной будущей очистки)."""
    result = send(chat_id, text, reply_markup=reply_markup, silent=silent)
    if result and result.get("message_id"):
        track_msg(chat_id, result["message_id"])
    return result



# ══════════════════════════════════════════════════════════════════════════════
# КЛАВИАТУРЫ
# ══════════════════════════════════════════════════════════════════════════════

def lang_keyboard(current_lang, back_to_panel=False):
    """Inline-клавиатура выбора языка."""
    buttons = []
    for code, (flag, name) in SUPPORTED_LANGS.items():
        marker = "🔘 " if code == current_lang else ""
        buttons.append([{
            "text": f"{marker}{flag} {name}",
            "callback_data": f"set_lang:{code}",
        }])
    if back_to_panel:
        back_labels = {"ru": "◀️ Назад", "en": "◀️ Back", "uk": "◀️ Назад"}
        buttons.append([{
            "text": back_labels.get(current_lang, "◀️ Back"),
            "callback_data": "panel:close",
        }])
    return {"inline_keyboard": buttons}


def tz_keyboard(current_tz, lang):
    """Клавиатура выбора часового пояса — 2 кнопки в ряд."""
    buttons = []
    row = []
    for i, (tz_name, flag, label, utc) in enumerate(TIMEZONES):
        marker = "🔘 " if tz_name == (current_tz or "Europe/Kiev") else ""
        btn = {
            "text": f"{marker}{flag} {label} ({utc})",
            "callback_data": f"set_tz:{tz_name}",
        }
        row.append(btn)
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([{
        "text": t("settings_btn_back", lang),
        "callback_data": "settings:open",
    }])
    return {"inline_keyboard": buttons}


def repeat_keyboard(lang, repeat_count=1, repeat_interval_min=10):
    """Подменю настройки повторных уведомлений."""
    if repeat_count == 0:
        off_row = [{"text": t("repeat_on_btn", lang), "callback_data": "repeat_count:2"}]
    else:
        off_row = [{"text": t("repeat_off_btn", lang), "callback_data": "repeat_count:0"}]
    count_row = [
        {"text": f"{'✅ ' if n == repeat_count else ''}{n}×", "callback_data": f"repeat_count:{n}"}
        for n in range(1, 6)
    ]
    interval_row = [
        {"text": f"{'✅ ' if m == repeat_interval_min else ''}{m}{'м' if lang != 'en' else 'm'}",
         "callback_data": f"repeat_interval:{m}"}
        for m in (5, 10, 15, 30)
    ]
    rows = [off_row]
    if repeat_count > 0:
        rows.append(count_row)
        rows.append(interval_row)
    rows.append([{"text": t("settings_btn_back", lang), "callback_data": "settings:open"}])
    return {"inline_keyboard": rows}



def get_resource_repeat(state: dict, resource_key: str) -> dict | None:
    """
    Возвращает per-resource настройки повтора или None если используется глобальный.
    """
    return (state.get("repeat_per_resource") or {}).get(resource_key)


def _repeat_summary(lang: str, count: int, interval_min: int, inherited: bool = False) -> str:
    """Короткая строка вида '2×/15м' или '🔕 выкл' для кнопки."""
    if inherited:
        return t("repeat_inherited", lang)
    if count == 0:
        return t("repeat_summary_off", lang)
    suffix = "хв" if lang == "uk" else ("m" if lang == "en" else "м")
    return f"{count}×/{interval_min}{suffix}"


def repeat_resource_list_keyboard(tracking: dict, dynamic_resources: list,
                                   state: dict, lang: str) -> dict:
    """
    Список ресурсов с их индивидуальными настройками повтора.
    Первая строка — глобальный повтор (по умолчанию).
    Остальные — только отслеживаемые ресурсы.
    """
    buttons = []
    global_repeat  = state.get("repeat", {})
    g_count        = int(global_repeat.get("count", 1))
    g_interval     = int(global_repeat.get("interval_min", 10))
    g_summary      = _repeat_summary(lang, g_count, g_interval)
    buttons.append([{
        "text": t("repeat_global_btn", lang, summary=g_summary),
        "callback_data": "repeat_res:__global__",
    }])

    per_res = state.get("repeat_per_resource") or {}

    all_resources = list(TRACK_LABELS) + [
        (dr["key"], f"{dr['emoji']} {dr['label']}") for dr in (dynamic_resources or [])
    ]
    for key, label in all_resources:
        if not tracking.get(key, False):
            continue
        custom = per_res.get(key)
        if custom is not None:
            summary = _repeat_summary(lang, int(custom.get("count", 1)),
                                      int(custom.get("interval_min", 10)))
        else:
            summary = _repeat_summary(lang, g_count, g_interval, inherited=True)
        buttons.append([{
            "text": t("repeat_res_btn", lang, label=label, summary=summary),
            "callback_data": f"repeat_res:{key}",
        }])

    buttons.append([{
        "text": t("settings_btn_back", lang),
        "callback_data": "settings:open",
    }])
    return {"inline_keyboard": buttons}


def repeat_resource_keyboard(lang: str, resource_key: str,
                              count: int = 1, interval_min: int = 10,
                              has_custom: bool = False) -> dict:
    """
    Клавиатура настройки повтора для конкретного ресурса.
    has_custom=True — показывает кнопку сброса к глобальному.
    """
    if count == 0:
        off_row = [{"text": t("repeat_on_btn", lang),
                    "callback_data": f"repeat_res_count:{resource_key}:2"}]
    else:
        off_row = [{"text": t("repeat_off_btn", lang),
                    "callback_data": f"repeat_res_count:{resource_key}:0"}]
    count_row = [
        {"text": f"{'✅ ' if n == count else ''}{n}×",
         "callback_data": f"repeat_res_count:{resource_key}:{n}"}
        for n in range(1, 6)
    ]
    interval_row = [
        {"text": f"{'✅ ' if m == interval_min else ''}{m}{'м' if lang != 'en' else 'm'}",
         "callback_data": f"repeat_res_interval:{resource_key}:{m}"}
        for m in (5, 10, 15, 30)
    ]
    rows = [off_row]
    if count > 0:
        rows.append(count_row)
        rows.append(interval_row)
    if has_custom and resource_key != "__global__":
        rows.append([{
            "text": t("repeat_res_reset_btn", lang),
            "callback_data": f"repeat_res_reset:{resource_key}",
        }])
    rows.append([{
        "text": t("settings_btn_back", lang),
        "callback_data": "repeat_list",
    }])
    return {"inline_keyboard": rows}


def settings_keyboard(tracking, dynamic_resources, current_tz, lang,
                      repeat_count=3, repeat_interval_min=10, farm_id="?",
                      time_format="both"):
    """Inline-клавиатура для /settings."""
    buttons = []
    for key, label in TRACK_LABELS:
        enabled = tracking.get(key, DEFAULT_TRACKING.get(key, False))
        icon = "✅" if enabled else "❌"
        buttons.append([{"text": f"{icon} {label}", "callback_data": f"toggle:{key}"}])
    for dr in (dynamic_resources or []):
        key   = dr["key"]
        label = f"{dr['emoji']} {dr['label']}"
        icon  = "✅" if tracking.get(key, False) else "❌"
        buttons.append([{"text": f"{icon} {label}", "callback_data": f"toggle:{key}"}])
    tz_label = tz_display_name(current_tz)
    buttons.append([{
        "text": t("tz_btn_label", lang, tz=tz_label),
        "callback_data": "tz_menu",
    }])
    repeat_label = (
        t("repeat_btn_off_label", lang)
        if repeat_count == 0
        else t("repeat_btn_label", lang, count=repeat_count, interval=repeat_interval_min)
    )
    buttons.append([{
        "text": repeat_label,
        "callback_data": "repeat_list",
    }])
    buttons.append([{
        "text": t("setfarm_btn_change", lang, farm_id=farm_id),
        "callback_data": "setfarm_prompt",
    }])
    tf_label = t(f"time_format_{time_format}", lang)
    buttons.append([{
        "text": t("show_clock_btn", lang, label=tf_label),
        "callback_data": "time_format_menu",
    }])
    buttons.append([{
        "text": t("twitter_gift_btn", lang),
        "callback_data": "twitter_gift:open",
    }])
    buttons.append([{
        "text": t("settings_btn_save", lang),
        "callback_data": "settings:close",
    }])
    return {"inline_keyboard": buttons}


# ── Twitter Gift helpers ───────────────────────────────────────────────────

TWITTER_GIFT_PERIOD = 168 * 3600  # 7 days in seconds


def _parse_tweet_datetime(text: str, user_tz=None):
    """Parse user-entered date/time string in user's local timezone, return UTC unix timestamp or None."""
    from datetime import datetime as _dt, timezone as _utc
    text = text.strip()
    formats = [
        "%d.%m.%Y %H:%M",
        "%Y-%m-%d %H:%M",
        "%d.%m.%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%d/%m/%Y %H:%M",
    ]
    tz = user_tz or _utc
    for fmt in formats:
        try:
            dt = _dt.strptime(text, fmt)
            return int(dt.replace(tzinfo=tz).timestamp())
        except ValueError:
            pass
    return None


def _fmt_twitter_countdown(seconds_left: int, lang: str) -> str:
    """Format seconds remaining as Xd Xh Xm."""
    seconds_left = max(0, int(seconds_left))
    d = seconds_left // 86400
    h = (seconds_left % 86400) // 3600
    m = (seconds_left % 3600) // 60
    if d > 0:
        return f"{d}d {h}h {m}m"
    elif h > 0:
        return f"{h}h {m}m"
    else:
        return f"{m}m"


def _twitter_gift_status_text(tg_state: dict, lang: str, user_tz=None) -> str:
    """Return status string for Twitter Gift menu."""
    import time as _time
    from datetime import datetime as _dt, timezone as _utc
    enabled = tg_state.get("enabled", False)
    last_ts = tg_state.get("last_post_ts", 0)
    if not enabled:
        return t("twitter_gift_status_disabled", lang)
    if not last_ts:
        return t("twitter_gift_status_no_post", lang)
    elapsed = _time.time() - last_ts
    remaining = TWITTER_GIFT_PERIOD - elapsed
    if remaining <= 0:
        return t("twitter_gift_status_ready", lang)
    display_tz = user_tz or _utc
    tz_label = display_tz.tzname(None) if hasattr(display_tz, "tzname") else "UTC"
    last_dt = _dt.fromtimestamp(last_ts, tz=display_tz).strftime(f"%d.%m.%Y %H:%M {tz_label}")
    return t("twitter_gift_status_countdown", lang,
             countdown=_fmt_twitter_countdown(remaining, lang),
             last_post=last_dt)


def twitter_gift_keyboard(tg_state: dict, lang: str) -> dict:
    """Inline keyboard for Twitter Gift settings screen."""
    import time as _time
    enabled = tg_state.get("enabled", False)
    last_ts = tg_state.get("last_post_ts", 0)
    buttons = []
    if enabled:
        elapsed = _time.time() - last_ts if last_ts else TWITTER_GIFT_PERIOD + 1
        remaining = TWITTER_GIFT_PERIOD - elapsed
        if remaining <= 0 and last_ts:
            buttons.append([{
                "text": t("twitter_gift_btn_done", lang),
                "callback_data": "twitter_gift:done",
            }])
        buttons.append([{
            "text": t("twitter_gift_btn_set_time", lang),
            "callback_data": "twitter_gift:set_time",
        }])
        buttons.append([{
            "text": t("twitter_gift_btn_disable", lang),
            "callback_data": "twitter_gift:toggle",
        }])
    else:
        buttons.append([{
            "text": t("twitter_gift_btn_enable", lang),
            "callback_data": "twitter_gift:toggle",
        }])
        buttons.append([{
            "text": t("twitter_gift_btn_set_time", lang),
            "callback_data": "twitter_gift:set_time",
        }])
    buttons.append([{
        "text": t("settings_btn_back", lang),
        "callback_data": "settings:open",
    }])
    return {"inline_keyboard": buttons}



# ══════════════════════════════════════════════════════════════════════════════
# ОБРАБОТЧИКИ КОМАНД
# ══════════════════════════════════════════════════════════════════════════════

def handle_start(chat_id, user_from):
    get_or_create_user(
        chat_id,
        username=user_from.get("username", ""),
        first_name=user_from.get("first_name", ""),
    )
    user = get_user(chat_id)
    lang = get_lang(user)
    msg = send_service(chat_id, t("welcome", lang), silent=True)
    # Сразу ждём ввода farm_id — пользователь просто отправляет число
    state = (user.get("state") or {})
    state["awaiting"] = "farm_id"
    state["awaiting_msg_id"] = msg["message_id"] if msg else None
    update_user(chat_id, state=state)


def handle_setfarm(chat_id, text):
    user = get_user(chat_id)
    lang = get_lang(user)
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        send_service(chat_id, t("setfarm_usage", lang))
        return
    farm_id = parts[1].strip()
    if not farm_id.isdigit():
        send_service(chat_id, t("setfarm_not_number", lang))
        return
    get_or_create_user(chat_id)
    update_user(chat_id, farm_id=farm_id)
    was_activated = activate_user_if_ready(chat_id)
    if was_activated:
        dispatch_new_user_runner(chat_id)
        send_service(chat_id, t("setfarm_ok_active", lang, farm_id=farm_id))
    else:
        send_service(chat_id, t("setfarm_ok_pending", lang, farm_id=farm_id))


def handle_setkey(chat_id, message_id, text):
    user = get_user(chat_id)
    lang = get_lang(user)
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        send_service(chat_id, t("setkey_usage", lang))
        return
    api_key = parts[1].strip()
    delete_msg(chat_id, message_id)
    get_or_create_user(chat_id)
    update_user(chat_id, api_key=api_key)
    was_activated = activate_user_if_ready(chat_id)
    if was_activated:
        send_service(chat_id, t("setkey_ok_active", lang))
    else:
        user = get_user(chat_id)
        if not user or not user.get("farm_id"):
            send_service(chat_id, t("setkey_ok_need_farm", lang))
        else:
            send_service(chat_id, t("setkey_ok", lang))


def handle_settings(chat_id):
    user = get_user(chat_id)
    if not user:
        send_service(chat_id, t("not_registered", DEFAULT_LANG))
        return
    lang              = get_lang(user)
    tracking          = user.get("tracking") or DEFAULT_TRACKING
    state             = user.get("state") or {}
    dynamic_resources = state.get("discovered_resources", [])
    current_tz        = state.get("timezone")
    repeat            = state.get("repeat", {})
    repeat_count      = int(repeat.get("count", 1))
    repeat_interval   = int(repeat.get("interval_min", 10))
    text = t("settings_title", lang)
    if dynamic_resources:
        text += t("settings_dynamic_note", lang, count=len(dynamic_resources))
    send_service(chat_id, text,
         reply_markup=settings_keyboard(tracking, dynamic_resources, current_tz, lang,
                                        repeat_count, repeat_interval,
                                        farm_id=user.get("farm_id", "?"),
                                        time_format=state.get("time_format", "both")))


def handle_status(chat_id):
    user = get_user(chat_id)
    lang = get_lang(user)
    if not user or not user.get("farm_id"):
        send_service(chat_id, t("status_no_farm", lang))
        return
    if not SHARED_API_KEY:
        send_service(chat_id, t("status_no_farm", lang))
        return
    msg = send_service(chat_id, t("status_loading", lang))
    loading_msg_id = msg["message_id"] if msg else None
    try:
        farm     = load_from_api(user["farm_id"], SHARED_API_KEY)
        tracking = user.get("tracking") or DEFAULT_TRACKING
        state    = user.get("state") or {}
        newly_found       = discover_dynamic_resources(farm)
        existing          = state.get("discovered_resources", [])
        dynamic_resources = merge_discovered(existing, newly_found)
        if dynamic_resources != existing:
            state["discovered_resources"] = dynamic_resources
            new_keys = {d["key"] for d in dynamic_resources} - {d["key"] for d in existing}
            if new_keys:
                labels = ", ".join(d["label"] for d in dynamic_resources
                                   if d["key"] in new_keys)
                send_service(chat_id, t("status_new_resources", lang, labels=labels))
        events       = scan_farm(farm, tracking, dynamic_resources)
        user_tz      = get_tz(state.get("timezone"))
        _dr          = farm.get("dailyRewards") or {}
        _dr_collected_ms = (_dr.get("chest") or {}).get("collectedAt", 0)
        from datetime import datetime, timezone as _utc_tz
        _today_str   = datetime.now(_utc_tz).strftime("%Y-%m-%d")
        _collected   = (bool(_dr_collected_ms) and
                        datetime.fromtimestamp(_dr_collected_ms / 1000, _utc_tz).strftime("%Y-%m-%d") == _today_str)
        daily_info   = {"streaks": _dr.get("streaks", 0), "collected_today": _collected}
        _tg_state    = state.get("twitter_gift") or {}
        twitter_gift_info = {"enabled": _tg_state.get("enabled", False),
                             "last_post_ts": _tg_state.get("last_post_ts", 0)}
        status_text  = format_status_message(events, user["farm_id"], tz=user_tz,
                                             time_format=state.get("time_format", "both"),
                                             daily_info=daily_info,
                                             twitter_gift_info=twitter_gift_info)
        is_active    = user.get("active", True)
        kb           = panel_keyboard(lang, is_active)
        old_status_id = state.get("status_msg_id")
        if loading_msg_id:
            edit_text(chat_id, loading_msg_id, status_text, reply_markup=kb)
            new_status_id = loading_msg_id
        else:
            new_status_id = None
        if new_status_id and new_status_id != old_status_id:
            if old_status_id:
                tg("unpinChatMessage", chat_id=chat_id, message_id=old_status_id)
            tg("pinChatMessage", chat_id=chat_id, message_id=new_status_id,
               disable_notification=True)
        state["status_msg_id"]    = new_status_id or old_status_id or 0
        state["last_status_text"] = status_text
        update_user(chat_id, state=state)
        return
    except Exception as e:
        status_text = t("status_error", lang, error=str(e))
    if loading_msg_id:
        edit_text(chat_id, loading_msg_id, status_text)
    else:
        send(chat_id, status_text)


def handle_stop(chat_id):
    user = get_user(chat_id)
    lang = get_lang(user)
    if not user:
        send(chat_id, t("not_registered", lang))
        return
    update_user(chat_id, active=False)
    send_service(chat_id, t("stop_ok", lang))


def handle_resume(chat_id):
    user = get_user(chat_id)
    lang = get_lang(user)
    if not user:
        send(chat_id, t("not_registered", lang))
        return
    if not user.get("farm_id"):
        send_service(chat_id, t("resume_no_farm", lang))
        return
    update_user(chat_id, active=True)
    send_service(chat_id, t("resume_ok", lang))


def handle_lang(chat_id):
    """Показать меню выбора языка."""
    user = get_user(chat_id)
    lang = get_lang(user)
    flag, name = SUPPORTED_LANGS[lang]
    send_service(
        chat_id,
        t("lang_choose", lang, current=f"{flag} {name}"),
        reply_markup=lang_keyboard(lang),
    )

# ══════════════════════════════════════════════════════════════════════════════
# ОБРАБОТЧИК CALLBACK (inline кнопки)
# ══════════════════════════════════════════════════════════════════════════════

def handle_reset(chat_id):
    user = get_user(chat_id)
    lang = get_lang(user) if user else DEFAULT_LANG
    keyboard = {"inline_keyboard": [[
        {"text": t("reset_yes_btn", lang), "callback_data": "reset:confirm"},
        {"text": t("reset_no_btn",  lang), "callback_data": "reset:cancel"},
    ]]}
    send_service(chat_id, t("reset_confirm", lang), reply_markup=keyboard)


def handle_callback(callback_query):
    cq_id    = callback_query["id"]
    chat_id  = callback_query["from"]["id"]
    msg_id   = callback_query["message"]["message_id"]
    data     = callback_query.get("data", "")

    user = get_user(chat_id)
    if not user:
        answer_callback(cq_id, t("callback_not_registered", DEFAULT_LANG))
        return

    lang              = get_lang(user)
    tracking          = dict(user.get("tracking") or DEFAULT_TRACKING)
    state             = user.get("state") or {}
    dynamic_resources = state.get("discovered_resources", [])
    dynamic_keys      = {d["key"] for d in dynamic_resources}
    current_tz        = state.get("timezone")
    user_tz           = get_tz(current_tz)

    # ── Смена языка ────────────────────────────────────────────────────────────
    if data.startswith("set_lang:"):
        new_lang = data.split(":", 1)[1]
        if new_lang in SUPPORTED_LANGS:
            state["lang"] = new_lang
            update_user(chat_id, state=state)
            flag, name = SUPPORTED_LANGS[new_lang]
            answer_callback(cq_id, f"{flag} {name}")
            from_panel = (msg_id == state.get("status_msg_id"))
            edit_text(
                chat_id, msg_id,
                t("lang_choose", new_lang, current=f"{flag} {name}"),
                reply_markup=lang_keyboard(new_lang, back_to_panel=from_panel),
            )
        return

    # ── Тоггл отслеживания ────────────────────────────────────────────────────
    if data.startswith("toggle:"):
        key = data.split(":", 1)[1]

        static_keys = {k for k, _ in TRACK_LABELS}
        if key in tracking or key in dynamic_keys or key in static_keys:
            tracking[key] = not tracking.get(key, False)
            update_user(chat_id, tracking=tracking)
            answer_callback(cq_id)
            _repeat       = state.get("repeat", {})
            _repeat_count = int(_repeat.get("count", 1))
            _repeat_intv  = int(_repeat.get("interval_min", 10))
            edit_text(
                chat_id, msg_id,
                t("settings_title", lang),
                reply_markup=settings_keyboard(tracking, dynamic_resources, current_tz, lang,
                                               _repeat_count, _repeat_intv,
                                               farm_id=user.get("farm_id", "?"),
                                               time_format=state.get("time_format", "both")),
            )
        else:
            answer_callback(cq_id, t("settings_unknown_resource", lang))

    elif data == "tz_menu":
        answer_callback(cq_id)
        edit_text(
            chat_id, msg_id,
            t("tz_title", lang, current_tz=tz_display_name(current_tz)),
            reply_markup=tz_keyboard(current_tz, lang),
        )

    elif data == "time_format_menu":
        answer_callback(cq_id)
        current_tf = state.get("time_format", "both")
        rows = []
        for fmt in ("both", "countdown", "clock"):
            check = "✅ " if fmt == current_tf else ""
            rows.append([{"text": check + t(f"time_format_{fmt}", lang),
                          "callback_data": f"set_time_format:{fmt}"}])
        rows.append([{"text": t("settings_btn_back", lang), "callback_data": "settings:open"}])
        edit_text(chat_id, msg_id, t("time_format_menu_title", lang),
                  reply_markup={"inline_keyboard": rows})

    elif data.startswith("set_time_format:"):
        new_tf = data.split(":", 1)[1]
        if new_tf in ("both", "countdown", "clock"):
            state["time_format"] = new_tf
            update_user(chat_id, state=state)
            answer_callback(cq_id)
            repeat = state.get("repeat", {})
            edit_text(
                chat_id, msg_id,
                t("settings_title", lang),
                reply_markup=settings_keyboard(tracking, dynamic_resources, current_tz, lang,
                                               int(repeat.get("count", 1)),
                                               int(repeat.get("interval_min", 10)),
                                               farm_id=user.get("farm_id", "?"),
                                               time_format=new_tf),
            )

    elif data.startswith("set_tz:"):
        new_tz = data.split(":", 1)[1]
        state["timezone"] = new_tz
        update_user(chat_id, state=state)
        answer_callback(cq_id, t("tz_saved_toast", lang, tz=tz_display_name(new_tz)))
        repeat = state.get("repeat", {})
        edit_text(
            chat_id, msg_id,
            t("settings_title", lang),
            reply_markup=settings_keyboard(tracking, dynamic_resources, new_tz, lang,
                                           int(repeat.get("count", 1)),
                                           int(repeat.get("interval_min", 10)),
                                           farm_id=user.get("farm_id", "?"),
                                           time_format=state.get("time_format", "both")),
        )

    elif data.startswith("repeat_count:"):
        # Глобальный повтор (старый формат — обратная совместимость)
        n = max(0, min(5, int(data.split(":", 1)[1])))
        state.setdefault("repeat", {})["count"] = n
        update_user(chat_id, state=state)
        toast = t("repeat_off_toast", lang) if n == 0 else t("repeat_count_toast", lang, n=n)
        answer_callback(cq_id, toast)
        repeat = state.get("repeat", {})
        glbl = {"ru": "По умолчанию", "en": "Default", "uk": "За замовч."}.get(lang, "Default")
        edit_text(
            chat_id, msg_id,
            t("repeat_res_title", lang, label=glbl),
            reply_markup=repeat_resource_keyboard(
                lang, "__global__", n, int(repeat.get("interval_min", 10)), False),
        )

    elif data.startswith("repeat_interval:"):
        # Глобальный интервал (старый формат — обратная совместимость)
        m = int(data.split(":", 1)[1])
        state.setdefault("repeat", {})["interval_min"] = m
        update_user(chat_id, state=state)
        answer_callback(cq_id, t("repeat_interval_toast", lang, m=m))
        repeat = state.get("repeat", {})
        glbl = {"ru": "По умолчанию", "en": "Default", "uk": "За замовч."}.get(lang, "Default")
        edit_text(
            chat_id, msg_id,
            t("repeat_res_title", lang, label=glbl),
            reply_markup=repeat_resource_keyboard(
                lang, "__global__", int(repeat.get("count", 1)), m, False),
        )

    elif data == "repeat_list":
        # Список ресурсов с per-resource настройками повтора
        answer_callback(cq_id)
        edit_text(
            chat_id, msg_id,
            t("repeat_list_title", lang),
            reply_markup=repeat_resource_list_keyboard(tracking, dynamic_resources, state, lang),
        )

    elif data.startswith("repeat_res:"):
        # Открыть повторы для конкретного ресурса (или глобальные)
        res_key = data.split(":", 1)[1]
        answer_callback(cq_id)
        per_res = state.get("repeat_per_resource") or {}
        if res_key == "__global__":
            rep = state.get("repeat", {})
            r_count    = int(rep.get("count", 1))
            r_interval = int(rep.get("interval_min", 10))
            has_custom = False
            label = {
                "ru": "По умолчанию", "en": "Default", "uk": "За замовч."
            }.get(lang, "Default")
        elif res_key in per_res:
            rr = per_res[res_key]
            r_count    = int(rr.get("count", 1))
            r_interval = int(rr.get("interval_min", 10))
            has_custom = True
            label = dict(TRACK_LABELS).get(res_key, res_key)
        else:
            # Нет кастомных настроек — показываем глобальные как начальные
            rep = state.get("repeat", {})
            r_count    = int(rep.get("count", 1))
            r_interval = int(rep.get("interval_min", 10))
            has_custom = False
            label = dict(TRACK_LABELS).get(res_key, res_key)
        edit_text(
            chat_id, msg_id,
            t("repeat_res_title", lang, label=label),
            reply_markup=repeat_resource_keyboard(lang, res_key, r_count, r_interval, has_custom),
        )

    elif data.startswith("repeat_res_count:"):
        # Установить count для конкретного ресурса
        _, res_key, n_str = data.split(":", 2)
        n = max(0, min(5, int(n_str)))
        per_res = state.setdefault("repeat_per_resource", {})
        if res_key == "__global__":
            state.setdefault("repeat", {})["count"] = n
        else:
            # Если кастомной записи ещё нет — инициализируем с текущим эффективным интервалом,
            # чтобы он не сбрасывался к 10м при первом нажатии
            if res_key not in per_res:
                global_repeat = state.get("repeat", {})
                per_res[res_key] = {"interval_min": int(global_repeat.get("interval_min", 10))}
            per_res[res_key]["count"] = n
        update_user(chat_id, state=state)
        toast = t("repeat_off_toast", lang) if n == 0 else t("repeat_count_toast", lang, n=n)
        answer_callback(cq_id, toast)
        # Обновляем клавиатуру
        if res_key == "__global__":
            rep = state.get("repeat", {})
            r_count    = n
            r_interval = int(rep.get("interval_min", 10))
            label = {"ru": "По умолчанию", "en": "Default", "uk": "За замовч."}.get(lang, "Default")
            has_custom = False
        else:
            rr = per_res.get(res_key, {})
            r_count    = n
            r_interval = int(rr.get("interval_min", 10))
            has_custom = True
            label = dict(TRACK_LABELS).get(res_key, res_key)
        edit_text(
            chat_id, msg_id,
            t("repeat_res_title", lang, label=label),
            reply_markup=repeat_resource_keyboard(lang, res_key, r_count, r_interval, has_custom),
        )

    elif data.startswith("repeat_res_interval:"):
        # Установить interval для конкретного ресурса
        _, res_key, m_str = data.split(":", 2)
        m = int(m_str)
        per_res = state.setdefault("repeat_per_resource", {})
        if res_key == "__global__":
            state.setdefault("repeat", {})["interval_min"] = m
        else:
            # Если кастомной записи ещё нет — инициализируем с текущим эффективным count,
            # чтобы он не сбрасывался к 1 при первом нажатии
            if res_key not in per_res:
                global_repeat = state.get("repeat", {})
                per_res[res_key] = {"count": int(global_repeat.get("count", 1))}
            per_res[res_key]["interval_min"] = m
        update_user(chat_id, state=state)
        answer_callback(cq_id, t("repeat_interval_toast", lang, m=m))
        if res_key == "__global__":
            rep = state.get("repeat", {})
            r_count    = int(rep.get("count", 1))
            r_interval = m
            label = {"ru": "По умолчанию", "en": "Default", "uk": "За замовч."}.get(lang, "Default")
            has_custom = False
        else:
            rr = per_res.get(res_key, {})
            r_count    = int(rr.get("count", 1))
            r_interval = m
            has_custom = True
            label = dict(TRACK_LABELS).get(res_key, res_key)
        edit_text(
            chat_id, msg_id,
            t("repeat_res_title", lang, label=label),
            reply_markup=repeat_resource_keyboard(lang, res_key, r_count, r_interval, has_custom),
        )

    elif data.startswith("repeat_res_reset:"):
        # Сбросить per-resource настройки — ресурс вернётся к глобальному повтору
        res_key = data.split(":", 1)[1]
        per_res = state.get("repeat_per_resource") or {}
        per_res.pop(res_key, None)
        state["repeat_per_resource"] = per_res
        update_user(chat_id, state=state)
        answer_callback(cq_id, t("repeat_res_reset_toast", lang))
        edit_text(
            chat_id, msg_id,
            t("repeat_list_title", lang),
            reply_markup=repeat_resource_list_keyboard(tracking, dynamic_resources, state, lang),
        )

    elif data == "repeat_menu":
        # Обратная совместимость — редиректим на repeat_list
        answer_callback(cq_id)
        edit_text(
            chat_id, msg_id,
            t("repeat_list_title", lang),
            reply_markup=repeat_resource_list_keyboard(tracking, dynamic_resources, state, lang),
        )

    elif data == "daily_dismiss":
        # Ручное закрытие напоминания о Daily Rewards кнопкой ❌
        if state.get("daily_reminder_msg_id") == msg_id:
            from datetime import datetime, timezone as _utc_tz
            today_str = datetime.now(_utc_tz).strftime("%Y-%m-%d")
            state["daily_reminder_msg_id"]          = 0
            state["daily_reminder_dismissed_date"]  = today_str
            update_user(chat_id, state=state)
        delete_msg(chat_id, msg_id)
        answer_callback(cq_id)

    elif data == "quest_dismiss":
        # Ручное закрытие уведомления о Questе кнопкой ❌
        if state.get("quest_msg_id") == msg_id:
            state["quest_msg_id"] = 0
            update_user(chat_id, state=state)
        delete_msg(chat_id, msg_id)
        answer_callback(cq_id)

    elif data.startswith("dismiss:"):
        # Закрытие алерта о готовности кнопкой ❌
        alert_key = data[len("dismiss:"):]
        alerts_state = state.get("ready_alerts", {})
        if alert_key in alerts_state:
            # Не удаляем запись — ставим флаг, чтобы сканер не повторял алерт
            # до следующего реального события (смены wave_anchor при следующем сборе).
            alerts_state[alert_key]["dismissed"] = True
            alerts_state[alert_key]["mid"] = 0  # сообщение уже удалено
            state["ready_alerts"] = alerts_state
            update_user(chat_id, state=state)
        delete_msg(chat_id, msg_id)
        answer_callback(cq_id)

    elif data == "noop":
        answer_callback(cq_id)

    elif data in ("settings:open", "settings:back"):
        answer_callback(cq_id)
        repeat = state.get("repeat", {})
        edit_text(
            chat_id, msg_id,
            t("settings_title", lang),
            reply_markup=settings_keyboard(tracking, dynamic_resources, current_tz, lang,
                                           int(repeat.get("count", 1)),
                                           int(repeat.get("interval_min", 10)),
                                           farm_id=user.get("farm_id", "?"),
                                           time_format=state.get("time_format", "both")),
        )

    elif data == "settings:close":
        answer_callback(cq_id, t("settings_saved", lang))
        # Если закрываем настройки из панели — возвращаем панель
        if msg_id == state.get("status_msg_id"):
            state["panel_locked"] = 0
            update_user(chat_id, state=state)
            user = get_user(chat_id)
            last_text = state.get("last_status_text", "🌻 SFL Farm Notifier")
            edit_text(chat_id, msg_id, last_text,
                      reply_markup=panel_keyboard(lang, user.get("active", True)))
        else:
            lines = [
                f"{'✅' if tracking.get(k) else '❌'} {label}"
                for k, label in TRACK_LABELS
            ]
            for dr in dynamic_resources:
                icon = "✅" if tracking.get(dr["key"]) else "❌"
                lines.append(f"{icon} {dr['emoji']} {dr['label']}")
            repeat = state.get("repeat", {})
            _rc = int(repeat.get("count", 1))
            lines.append(f"\n🕐 {tz_display_name(current_tz)}")
            lines.append(
                t("repeat_summary_off", lang)
                if _rc == 0
                else t("repeat_summary", lang, count=_rc, interval=repeat.get("interval_min", 10))
            )
            edit_text(
                chat_id, msg_id,
                t("settings_saved_title", lang) + "\n\n" + "\n".join(lines),
            )

    elif data == "setfarm_prompt":
        answer_callback(cq_id)
        state["awaiting"] = "farm_id"
        state["awaiting_msg_id"] = msg_id
        update_user(chat_id, state=state)
        edit_text(
            chat_id, msg_id,
            t("setfarm_prompt", lang, farm_id=user.get("farm_id", "?")),
            reply_markup={"inline_keyboard": [[{
                "text": t("setfarm_prompt_cancel", lang),
                "callback_data": "setfarm_cancel",
            }]]},
        )

    elif data == "setfarm_cancel":
        answer_callback(cq_id)
        state.pop("awaiting", None)
        state.pop("awaiting_msg_id", None)
        update_user(chat_id, state=state)
        # Перезагружаем пользователя чтобы получить актуальный farm_id
        user = get_user(chat_id)
        repeat = state.get("repeat", {})
        edit_text(
            chat_id, msg_id,
            t("settings_title", lang),
            reply_markup=settings_keyboard(tracking, dynamic_resources, current_tz, lang,
                                           int(repeat.get("count", 1)),
                                           int(repeat.get("interval_min", 10)),
                                           farm_id=user.get("farm_id", "?"),
                                           time_format=state.get("time_format", "both")),
        )

    # ── Кнопки панели управления (в закреплённом сообщении) ──────────────────

    elif data == "panel:settings":
        answer_callback(cq_id)
        state["panel_locked"] = int(time.time())
        update_user(chat_id, state=state)
        repeat = state.get("repeat", {})
        edit_text(
            chat_id, msg_id,
            t("settings_title", lang),
            reply_markup=settings_keyboard(tracking, dynamic_resources, current_tz, lang,
                                           int(repeat.get("count", 1)),
                                           int(repeat.get("interval_min", 10)),
                                           farm_id=user.get("farm_id", "?"),
                                           time_format=state.get("time_format", "both")),
        )

    elif data == "panel:lang":
        answer_callback(cq_id)
        state["panel_locked"] = int(time.time())
        update_user(chat_id, state=state)
        flag, name = SUPPORTED_LANGS[lang]
        edit_text(
            chat_id, msg_id,
            t("lang_choose", lang, current=f"{flag} {name}"),
            reply_markup=lang_keyboard(lang, back_to_panel=True),
        )

    elif data == "panel:stop":
        update_user(chat_id, active=False)
        state["panel_locked"] = 0
        update_user(chat_id, state=state)
        answer_callback(cq_id)
        last_text = state.get("last_status_text", "⏸")
        edit_text(chat_id, msg_id, last_text, reply_markup=panel_keyboard(lang, False))

    elif data == "panel:resume":
        update_user(chat_id, active=True)
        state["panel_locked"] = 0
        update_user(chat_id, state=state)
        answer_callback(cq_id)
        last_text = state.get("last_status_text", "▶️")
        edit_text(chat_id, msg_id, last_text, reply_markup=panel_keyboard(lang, True))

    elif data == "panel:close":
        answer_callback(cq_id)
        state["panel_locked"] = 0
        update_user(chat_id, state=state)
        user = get_user(chat_id)
        last_text = state.get("last_status_text", "🌻 SFL Farm Notifier")
        edit_text(chat_id, msg_id, last_text,
                  reply_markup=panel_keyboard(lang, user.get("active", True)))

    # ── Twitter Gift ────────────────────────────────────────────────────────

    elif data == "twitter_gift:open":
        answer_callback(cq_id)
        tg_state = state.get("twitter_gift") or {}
        status   = _twitter_gift_status_text(tg_state, lang, user_tz)
        edit_text(
            chat_id, msg_id,
            t("twitter_gift_title", lang, status=status),
            reply_markup=twitter_gift_keyboard(tg_state, lang),
        )

    elif data == "twitter_gift:toggle":
        tg_state = state.get("twitter_gift") or {}
        enabled  = tg_state.get("enabled", False)
        tg_state["enabled"] = not enabled
        state["twitter_gift"] = tg_state
        update_user(chat_id, state=state)
        toast = (
            t("twitter_gift_enabled_toast", lang)
            if not enabled else
            t("twitter_gift_disabled_toast", lang)
        )
        answer_callback(cq_id, toast)
        status = _twitter_gift_status_text(tg_state, lang, user_tz)
        edit_text(
            chat_id, msg_id,
            t("twitter_gift_title", lang, status=status),
            reply_markup=twitter_gift_keyboard(tg_state, lang),
        )

    elif data == "twitter_gift:done":
        import time as _time
        tg_state = state.get("twitter_gift") or {}
        tg_state["last_post_ts"] = int(_time.time())
        tg_state["notified"]     = False
        tg_state["notify_msg_id"] = 0
        state["twitter_gift"] = tg_state
        update_user(chat_id, state=state)
        answer_callback(cq_id, t("twitter_gift_done_toast", lang))
        status = _twitter_gift_status_text(tg_state, lang, user_tz)
        edit_text(
            chat_id, msg_id,
            t("twitter_gift_title", lang, status=status),
            reply_markup=twitter_gift_keyboard(tg_state, lang),
        )

    elif data == "twitter_gift:set_time":
        answer_callback(cq_id)
        state["awaiting"]     = "twitter_post_time"
        state["awaiting_msg_id"] = msg_id
        update_user(chat_id, state=state)
        tz_label = tz_display_name(current_tz)
        edit_text(
            chat_id, msg_id,
            t("twitter_gift_set_time_prompt", lang, tz=tz_label),
            reply_markup={"inline_keyboard": [[{
                "text": t("twitter_gift_btn_cancel", lang),
                "callback_data": "twitter_gift:cancel_set",
            }]]},
        )

    elif data == "twitter_gift:cancel_set":
        answer_callback(cq_id)
        state.pop("awaiting", None)
        state.pop("awaiting_msg_id", None)
        update_user(chat_id, state=state)
        tg_state = state.get("twitter_gift") or {}
        status   = _twitter_gift_status_text(tg_state, lang, user_tz)
        edit_text(
            chat_id, msg_id,
            t("twitter_gift_title", lang, status=status),
            reply_markup=twitter_gift_keyboard(tg_state, lang),
        )

    elif data == "reset:confirm":
        answer_callback(cq_id)
        update_user(chat_id,
            farm_id="",
            api_key="",
            tracking=DEFAULT_TRACKING,
            state={},
            active=False,
            scanner_dispatched=False,
        )
        delete_msg(chat_id, msg_id)
        send_service(chat_id, t("reset_done", lang), silent=True)
        handle_start(chat_id, callback_query["from"])

    elif data == "reset:cancel":
        answer_callback(cq_id)
        delete_msg(chat_id, msg_id)
        send_service(chat_id, t("reset_cancel", lang), silent=True)




# ══════════════════════════════════════════════════════════════════════════════
# ДИСПЕТЧЕР ОБНОВЛЕНИЙ
# ══════════════════════════════════════════════════════════════════════════════

def dispatch(update):
    if "callback_query" in update:
        handle_callback(update["callback_query"])
        return

    msg = update.get("message")
    if not msg:
        return

    chat_id    = msg["chat"]["id"]
    message_id = msg["message_id"]
    user_from  = msg.get("from", {})
    text       = msg.get("text", "").strip()

    if not text:
        return

    if msg["chat"]["type"] != "private":
        return

    # ── Ожидание ввода farm_id ────────────────────────────────────────────────
    if not text.startswith("/"):
        user = get_user(chat_id)
        if user:
            state = user.get("state") or {}
            if state.get("awaiting") == "farm_id":
                lang = get_lang(user)
                prompt_msg_id = state.get("awaiting_msg_id")
                delete_msg(chat_id, message_id)
                if not text.isdigit():
                    # Невалидный ввод — обновляем подсказку
                    if prompt_msg_id:
                        edit_text(
                            chat_id, prompt_msg_id,
                            t("setfarm_invalid", lang),
                            reply_markup={"inline_keyboard": [[{
                                "text": t("setfarm_prompt_cancel", lang),
                                "callback_data": "setfarm_cancel",
                            }]]},
                        )
                    return
                # Сохраняем новый farm_id
                update_user(chat_id, farm_id=text)
                was_activated = activate_user_if_ready(chat_id)
                if was_activated:
                    dispatch_new_user_runner(chat_id)
                state.pop("awaiting", None)
                state.pop("awaiting_msg_id", None)
                update_user(chat_id, state=state)
                user = get_user(chat_id)
                tracking          = user.get("tracking") or DEFAULT_TRACKING
                dynamic_resources = state.get("discovered_resources", [])
                current_tz        = state.get("timezone")
                repeat            = state.get("repeat", {})
                if prompt_msg_id:
                    edit_text(
                        chat_id, prompt_msg_id,
                        t("settings_title", lang) + "\n\n" + t("setfarm_changed", lang, farm_id=text),
                        reply_markup=settings_keyboard(
                            tracking, dynamic_resources, current_tz, lang,
                            int(repeat.get("count", 1)),
                            int(repeat.get("interval_min", 10)),
                            farm_id=text,
                            time_format=state.get("time_format", "both"),
                        ),
                    )
                return

            elif state.get("awaiting") == "twitter_post_time":
                lang          = get_lang(user)
                prompt_msg_id = state.get("awaiting_msg_id")
                delete_msg(chat_id, message_id)
                _user_tz = get_tz(state.get("timezone"))
                ts = _parse_tweet_datetime(text, _user_tz)
                if ts is None:
                    if prompt_msg_id:
                        edit_text(
                            chat_id, prompt_msg_id,
                            t("twitter_gift_set_time_invalid", lang),
                            reply_markup={"inline_keyboard": [[{
                                "text": t("twitter_gift_btn_cancel", lang),
                                "callback_data": "twitter_gift:cancel_set",
                            }]]},
                        )
                    return
                # Сохраняем timestamp и включаем Twitter Gift если ещё не включён
                tg_state = state.get("twitter_gift") or {}
                tg_state["last_post_ts"]  = ts
                tg_state["enabled"]       = True
                tg_state["notified"]      = False
                tg_state["notify_msg_id"] = 0
                state["twitter_gift"] = tg_state
                state.pop("awaiting", None)
                state.pop("awaiting_msg_id", None)
                update_user(chat_id, state=state)
                status = _twitter_gift_status_text(tg_state, lang, _user_tz)
                if prompt_msg_id:
                    edit_text(
                        chat_id, prompt_msg_id,
                        t("twitter_gift_title", lang, status=status),
                        reply_markup=twitter_gift_keyboard(tg_state, lang),
                    )
                return

    cmd = text.split()[0].lower().split("@")[0]

    if cmd == "/start":
        handle_start(chat_id, user_from)
    elif cmd == "/setfarm":
        handle_setfarm(chat_id, text)
    elif cmd == "/setkey":
        handle_setkey(chat_id, message_id, text)
    elif cmd == "/settings":
        handle_settings(chat_id)
    elif cmd == "/status":
        handle_status(chat_id)
    elif cmd == "/stop":
        handle_stop(chat_id)
    elif cmd == "/resume":
        handle_resume(chat_id)
    elif cmd in ("/lang", "/language", "/setlang"):
        handle_lang(chat_id)
    elif cmd == "/reset":
        handle_reset(chat_id)
    elif cmd in ("/help", "/h"):
        user = get_user(chat_id)
        lang = get_lang(user)
        send_service(chat_id, t("help", lang))
    else:
        if text.startswith("/"):
            user = get_user(chat_id)
            lang = get_lang(user)
            send_service(chat_id, t("unknown_command", lang) + t("help", lang))

# ══════════════════════════════════════════════════════════════════════════════
# LONG POLLING ЦИКЛ
# ══════════════════════════════════════════════════════════════════════════════

def run_polling(duration_seconds=21000):
    if not TG_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN не задан!")
        sys.exit(1)

    log.info(f"Бот запущен (long polling, duration={duration_seconds}s)")
    tg("deleteWebhook", drop_pending_updates=False)

    offset   = 0
    end_time = time.time() + duration_seconds

    while time.time() < end_time:
        try:
            result = tg(
                "getUpdates",
                offset=offset,
                timeout=30,
                allowed_updates=["message", "callback_query"],
            )
            if not result:
                continue
            for update in result:
                offset = update["update_id"] + 1
                try:
                    dispatch(update)
                except Exception as e:
                    log.warning(f"dispatch error: {e}")
        except Exception as e:
            log.warning(f"polling error: {e}")
            time.sleep(5)

    log.info("Бот завершил работу (duration истёк, ждём перезапуска от GitHub Actions).")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SFL Telegram Bot")
    parser.add_argument("--duration", type=int, default=21000,
                        help="Длительность работы бота (секунды)")
    args = parser.parse_args()
    run_polling(duration_seconds=args.duration)
