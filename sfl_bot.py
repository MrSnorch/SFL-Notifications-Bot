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
)
from sfl_supabase import (
    get_or_create_user, get_user, update_user,
    activate_user_if_ready, upsert_user,
)

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE = f"https://api.telegram.org/bot{TG_TOKEN}"

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
            "Для начала настрой:\n"
            "1️⃣ /setfarm <code>12345</code> — укажи ID фермы\n"
            "2️⃣ /setkey <code>твой_api_ключ</code> — укажи API ключ\n\n"
            "Как получить API ключ:\n"
            "• Зайди на <a href=\"https://sunflower-land.com\">sunflower-land.com</a>\n"
            "• Настройки → Community API → Create Key\n\n"
            "После настройки уведомления включатся автоматически! 🚀"
        ),
        "en": (
            "🌻 <b>SFL Farm Notifier</b>\n\n"
            "Hello! I'll monitor your Sunflower Land farm and send notifications when resources are ready.\n\n"
            "To get started:\n"
            "1️⃣ /setfarm <code>12345</code> — set your farm ID\n"
            "2️⃣ /setkey <code>your_api_key</code> — set your API key\n\n"
            "How to get an API key:\n"
            "• Go to <a href=\"https://sunflower-land.com\">sunflower-land.com</a>\n"
            "• Settings → Community API → Create Key\n\n"
            "Notifications will turn on automatically once you're set up! 🚀"
        ),
        "uk": (
            "🌻 <b>SFL Farm Notifier</b>\n\n"
            "Привіт! Я стежитиму за твоєю фермою у Sunflower Land і надсилатиму сповіщення, коли ресурси готові.\n\n"
            "Для початку налаштуй:\n"
            "1️⃣ /setfarm <code>12345</code> — вкажи ID ферми\n"
            "2️⃣ /setkey <code>твій_api_ключ</code> — вкажи API ключ\n\n"
            "Як отримати API ключ:\n"
            "• Зайди на <a href=\"https://sunflower-land.com\">sunflower-land.com</a>\n"
            "• Налаштування → Community API → Create Key\n\n"
            "Після налаштування сповіщення увімкнуться автоматично! 🚀"
        ),
    },
    "help": {
        "ru": (
            "🌻 <b>SFL Farm Notifier — Команды</b>\n\n"
            "/start — перезапустить бота\n"
            "/setfarm <code>ID</code> — установить ID фермы\n"
            "/setkey <code>KEY</code> — установить API ключ\n"
            "/settings — настроить что отслеживать\n"
            "/status — проверить ферму прямо сейчас\n"
            "/stop — приостановить уведомления\n"
            "/resume — возобновить уведомления\n"
            "/lang — сменить язык\n"
            "/help — это сообщение"
        ),
        "en": (
            "🌻 <b>SFL Farm Notifier — Commands</b>\n\n"
            "/start — restart the bot\n"
            "/setfarm <code>ID</code> — set farm ID\n"
            "/setkey <code>KEY</code> — set API key\n"
            "/settings — configure what to track\n"
            "/status — check farm right now\n"
            "/stop — pause notifications\n"
            "/resume — resume notifications\n"
            "/lang — change language\n"
            "/help — this message"
        ),
        "uk": (
            "🌻 <b>SFL Farm Notifier — Команди</b>\n\n"
            "/start — перезапустити бота\n"
            "/setfarm <code>ID</code> — встановити ID ферми\n"
            "/setkey <code>KEY</code> — встановити API ключ\n"
            "/settings — налаштувати що відстежувати\n"
            "/status — перевірити ферму прямо зараз\n"
            "/stop — призупинити сповіщення\n"
            "/resume — поновити сповіщення\n"
            "/lang — змінити мову\n"
            "/help — це повідомлення"
        ),
    },
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
    "settings_unknown_resource": {
        "ru": "Неизвестный ресурс",
        "en": "Unknown resource",
        "uk": "Невідомий ресурс",
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
        r = requests.post(f"{API_BASE}/{method}", json=kwargs, timeout=20)
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

# ══════════════════════════════════════════════════════════════════════════════
# КЛАВИАТУРЫ
# ══════════════════════════════════════════════════════════════════════════════

def lang_keyboard(current_lang):
    """Inline-клавиатура выбора языка."""
    buttons = []
    for code, (flag, name) in SUPPORTED_LANGS.items():
        marker = "🔘 " if code == current_lang else ""
        buttons.append([{
            "text": f"{marker}{flag} {name}",
            "callback_data": f"set_lang:{code}",
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


def settings_keyboard(tracking, dynamic_resources=None, current_tz=None, lang=DEFAULT_LANG):
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
    buttons.append([{
        "text": t("settings_btn_save", lang),
        "callback_data": "settings:close",
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
    send(chat_id, t("welcome", lang), silent=True)


def handle_setfarm(chat_id, text):
    user = get_user(chat_id)
    lang = get_lang(user)
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        send(chat_id, t("setfarm_usage", lang))
        return
    farm_id = parts[1].strip()
    if not farm_id.isdigit():
        send(chat_id, t("setfarm_not_number", lang))
        return
    get_or_create_user(chat_id)
    update_user(chat_id, farm_id=farm_id)
    was_activated = activate_user_if_ready(chat_id)
    if was_activated:
        send(chat_id, t("setfarm_ok_active", lang, farm_id=farm_id))
    else:
        send(chat_id, t("setfarm_ok_pending", lang, farm_id=farm_id))


def handle_setkey(chat_id, message_id, text):
    user = get_user(chat_id)
    lang = get_lang(user)
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        send(chat_id, t("setkey_usage", lang))
        return
    api_key = parts[1].strip()
    delete_msg(chat_id, message_id)
    get_or_create_user(chat_id)
    update_user(chat_id, api_key=api_key)
    was_activated = activate_user_if_ready(chat_id)
    if was_activated:
        send(chat_id, t("setkey_ok_active", lang))
    else:
        user = get_user(chat_id)
        if not user or not user.get("farm_id"):
            send(chat_id, t("setkey_ok_need_farm", lang))
        else:
            send(chat_id, t("setkey_ok", lang))


def handle_settings(chat_id):
    user = get_user(chat_id)
    if not user:
        send(chat_id, t("not_registered", DEFAULT_LANG))
        return
    lang              = get_lang(user)
    tracking          = user.get("tracking") or DEFAULT_TRACKING
    state             = user.get("state") or {}
    dynamic_resources = state.get("discovered_resources", [])
    current_tz        = state.get("timezone")
    text = t("settings_title", lang)
    if dynamic_resources:
        text += t("settings_dynamic_note", lang, count=len(dynamic_resources))
    send(chat_id, text,
         reply_markup=settings_keyboard(tracking, dynamic_resources, current_tz, lang))


def handle_status(chat_id):
    user = get_user(chat_id)
    lang = get_lang(user)
    if not user or not user.get("farm_id") or not user.get("api_key"):
        send(chat_id, t("status_no_farm", lang))
        return
    msg = send(chat_id, t("status_loading", lang))
    loading_msg_id = msg["message_id"] if msg else None
    try:
        farm     = load_from_api(user["farm_id"], user["api_key"])
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
                send(chat_id, t("status_new_resources", lang, labels=labels))
        events       = scan_farm(farm, tracking, dynamic_resources)
        user_tz      = get_tz(state.get("timezone"))
        status_text  = format_status_message(events, user["farm_id"], tz=user_tz)
        old_status_id = state.get("status_msg_id")
        if loading_msg_id:
            edit_text(chat_id, loading_msg_id, status_text)
            new_status_id = loading_msg_id
        else:
            new_status_id = None
        if new_status_id and new_status_id != old_status_id:
            if old_status_id:
                tg("unpinChatMessage", chat_id=chat_id, message_id=old_status_id)
            tg("pinChatMessage", chat_id=chat_id, message_id=new_status_id,
               disable_notification=True)
        state["status_msg_id"] = new_status_id or old_status_id or 0
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
    send(chat_id, t("stop_ok", lang))


def handle_resume(chat_id):
    user = get_user(chat_id)
    lang = get_lang(user)
    if not user:
        send(chat_id, t("not_registered", lang))
        return
    if not user.get("farm_id") or not user.get("api_key"):
        send(chat_id, t("resume_no_farm", lang))
        return
    update_user(chat_id, active=True)
    send(chat_id, t("resume_ok", lang))


def handle_lang(chat_id):
    """Показать меню выбора языка."""
    user = get_user(chat_id)
    lang = get_lang(user)
    flag, name = SUPPORTED_LANGS[lang]
    send(
        chat_id,
        t("lang_choose", lang, current=f"{flag} {name}"),
        reply_markup=lang_keyboard(lang),
    )

# ══════════════════════════════════════════════════════════════════════════════
# ОБРАБОТЧИК CALLBACK (inline кнопки)
# ══════════════════════════════════════════════════════════════════════════════

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

    # ── Смена языка ────────────────────────────────────────────────────────────
    if data.startswith("set_lang:"):
        new_lang = data.split(":", 1)[1]
        if new_lang in SUPPORTED_LANGS:
            state["lang"] = new_lang
            update_user(chat_id, state=state)
            flag, name = SUPPORTED_LANGS[new_lang]
            answer_callback(cq_id, f"{flag} {name}")
            edit_text(
                chat_id, msg_id,
                t("lang_choose", new_lang, current=f"{flag} {name}"),
                reply_markup=lang_keyboard(new_lang),
            )
        return

    # ── Тоггл отслеживания ────────────────────────────────────────────────────
    if data.startswith("toggle:"):
        key = data.split(":", 1)[1]
        if key in tracking or key in dynamic_keys:
            tracking[key] = not tracking.get(key, False)
            update_user(chat_id, tracking=tracking)
            answer_callback(cq_id)
            edit_text(
                chat_id, msg_id,
                t("settings_title", lang),
                reply_markup=settings_keyboard(tracking, dynamic_resources, current_tz, lang),
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

    elif data.startswith("set_tz:"):
        new_tz = data.split(":", 1)[1]
        state["timezone"] = new_tz
        update_user(chat_id, state=state)
        answer_callback(cq_id, t("tz_saved_toast", lang, tz=tz_display_name(new_tz)))
        edit_text(
            chat_id, msg_id,
            t("settings_title", lang),
            reply_markup=settings_keyboard(tracking, dynamic_resources, new_tz, lang),
        )

    elif data in ("settings:open", "settings:back"):
        answer_callback(cq_id)
        edit_text(
            chat_id, msg_id,
            t("settings_title", lang),
            reply_markup=settings_keyboard(tracking, dynamic_resources, current_tz, lang),
        )

    elif data == "settings:close":
        answer_callback(cq_id, t("settings_saved", lang))
        lines = [
            f"{'✅' if tracking.get(k) else '❌'} {label}"
            for k, label in TRACK_LABELS
        ]
        for dr in dynamic_resources:
            icon = "✅" if tracking.get(dr["key"]) else "❌"
            lines.append(f"{icon} {dr['emoji']} {dr['label']}")
        lines.append(f"\n🕐 {tz_display_name(current_tz)}")
        edit_text(
            chat_id, msg_id,
            t("settings_saved_title", lang) + "\n\n" + "\n".join(lines),
        )

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
    elif cmd in ("/help", "/h"):
        user = get_user(chat_id)
        lang = get_lang(user)
        send(chat_id, t("help", lang))
    else:
        if text.startswith("/"):
            user = get_user(chat_id)
            lang = get_lang(user)
            send(chat_id, t("unknown_command", lang) + t("help", lang))

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
