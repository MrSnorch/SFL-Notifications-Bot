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
)
from sfl_supabase import (
    get_or_create_user, get_user, update_user,
    activate_user_if_ready, upsert_user,
)

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE = f"https://api.telegram.org/bot{TG_TOKEN}"

# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM API HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def tg(method: str, **kwargs) -> dict | None:
    try:
        r = requests.post(f"{API_BASE}/{method}", json=kwargs, timeout=20)
        if r.ok:
            return r.json().get("result")
        log.warning(f"TG {method} failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        log.warning(f"TG {method} error: {e}")
    return None


def send(chat_id: int, text: str, reply_markup: dict = None,
         silent: bool = False) -> dict | None:
    kwargs = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_notification": silent,
    }
    if reply_markup:
        kwargs["reply_markup"] = reply_markup
    return tg("sendMessage", **kwargs)


def edit_text(chat_id: int, message_id: int, text: str,
              reply_markup: dict = None) -> dict | None:
    kwargs = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        kwargs["reply_markup"] = reply_markup
    return tg("editMessageText", **kwargs)


def answer_callback(callback_query_id: str, text: str = ""):
    tg("answerCallbackQuery",
       callback_query_id=callback_query_id, text=text, show_alert=False)


def delete_msg(chat_id: int, message_id: int):
    tg("deleteMessage", chat_id=chat_id, message_id=message_id)

# ══════════════════════════════════════════════════════════════════════════════
# КЛАВИАТУРЫ
# ══════════════════════════════════════════════════════════════════════════════

def settings_keyboard(tracking: dict,
                       dynamic_resources: list[dict] | None = None) -> dict:
    """Inline-клавиатура для /settings — статические + динамические ресурсы."""
    buttons = []
    # Статические (известные) ресурсы
    for key, label in TRACK_LABELS:
        enabled = tracking.get(key, DEFAULT_TRACKING.get(key, False))
        icon = "✅" if enabled else "❌"
        buttons.append([{
            "text": f"{icon} {label}",
            "callback_data": f"toggle:{key}",
        }])
    # Динамические ресурсы (найденные в ответе API конкретного пользователя)
    for dr in (dynamic_resources or []):
        key   = dr["key"]
        label = f"{dr['emoji']} {dr['label']}"
        enabled = tracking.get(key, False)
        icon = "✅" if enabled else "❌"
        buttons.append([{
            "text": f"{icon} {label}",
            "callback_data": f"toggle:{key}",
        }])
    buttons.append([{
        "text": "💾 Сохранить и закрыть",
        "callback_data": "settings:close",
    }])
    return {"inline_keyboard": buttons}

# ══════════════════════════════════════════════════════════════════════════════
# ТЕКСТЫ СООБЩЕНИЙ
# ══════════════════════════════════════════════════════════════════════════════

WELCOME_TEXT = """🌻 <b>SFL Farm Notifier</b>

Привет! Я буду следить за твоей фермой в Sunflower Land и присылать уведомления когда ресурсы готовы.

Для начала настрой:
1️⃣ /setfarm <code>12345</code> — укажи ID фермы
2️⃣ /setkey <code>твой_api_ключ</code> — укажи API ключ

Как получить API ключ:
• Зайди на <a href="https://sunflower-land.com">sunflower-land.com</a>
• Настройки → Community API → Create Key

После настройки уведомления включатся автоматически! 🚀"""

HELP_TEXT = """🌻 <b>SFL Farm Notifier — Команды</b>

/start — перезапустить бота
/setfarm <code>ID</code> — установить ID фермы
/setkey <code>KEY</code> — установить API ключ
/settings — настроить что отслеживать
/status — проверить ферму прямо сейчас
/stop — приостановить уведомления
/resume — возобновить уведомления
/help — это сообщение"""

# ══════════════════════════════════════════════════════════════════════════════
# ОБРАБОТЧИКИ КОМАНД
# ══════════════════════════════════════════════════════════════════════════════

def handle_start(chat_id: int, user_from: dict):
    get_or_create_user(
        chat_id,
        username=user_from.get("username", ""),
        first_name=user_from.get("first_name", ""),
    )
    send(chat_id, WELCOME_TEXT, silent=True)


def handle_setfarm(chat_id: int, text: str):
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        send(chat_id,
             "❌ Укажи ID фермы:\n<code>/setfarm 12345</code>")
        return

    farm_id = parts[1].strip()
    # Проверяем что это число
    if not farm_id.isdigit():
        send(chat_id,
             "❌ ID фермы должен быть числом.\nПример: <code>/setfarm 12345</code>")
        return

    # Убедимся что пользователь существует
    get_or_create_user(chat_id)
    update_user(chat_id, farm_id=farm_id)

    was_activated = activate_user_if_ready(chat_id)

    if was_activated:
        send(chat_id,
             f"✅ Ферма <b>{farm_id}</b> установлена!\n\n"
             "🔔 Уведомления <b>включены</b> — первый статус придёт через несколько минут.")
    else:
        send(chat_id,
             f"✅ Ферма <b>{farm_id}</b> установлена!\n\n"
             "⏳ Осталось указать API ключ:\n<code>/setkey твой_ключ</code>")


def handle_setkey(chat_id: int, message_id: int, text: str):
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        send(chat_id,
             "❌ Укажи API ключ:\n<code>/setkey твой_ключ</code>")
        return

    api_key = parts[1].strip()

    # Сразу удаляем сообщение с ключом для безопасности
    delete_msg(chat_id, message_id)

    get_or_create_user(chat_id)
    update_user(chat_id, api_key=api_key)

    was_activated = activate_user_if_ready(chat_id)

    if was_activated:
        send(chat_id,
             "✅ API ключ сохранён! (твоё сообщение удалено для безопасности)\n\n"
             "🔔 Уведомления <b>включены</b> — первый статус придёт через несколько минут.")
    else:
        user = get_user(chat_id)
        if not user or not user.get("farm_id"):
            send(chat_id,
                 "✅ API ключ сохранён! (твоё сообщение удалено для безопасности)\n\n"
                 "⏳ Осталось указать ID фермы:\n<code>/setfarm 12345</code>")
        else:
            send(chat_id,
                 "✅ API ключ сохранён! (твоё сообщение удалено для безопасности)")


def handle_settings(chat_id: int):
    user = get_user(chat_id)
    if not user:
        send(chat_id, "❌ Сначала зарегистрируйся: /start")
        return

    tracking          = user.get("tracking") or DEFAULT_TRACKING
    state             = user.get("state") or {}
    dynamic_resources = state.get("discovered_resources", [])

    text = "⚙️ <b>Настройки отслеживания</b>\n\nВыбери что отслеживать:"
    if dynamic_resources:
        text += f"\n\n🔍 <i>Найдено новых ресурсов: {len(dynamic_resources)}</i>"
    send(chat_id, text, reply_markup=settings_keyboard(tracking, dynamic_resources))


def handle_status(chat_id: int):
    user = get_user(chat_id)
    if not user or not user.get("farm_id") or not user.get("api_key"):
        send(chat_id,
             "❌ Ферма не настроена.\n"
             "Используй /setfarm и /setkey")
        return

    msg = send(chat_id, "⏳ Загружаю данные фермы...")
    loading_msg_id = msg["message_id"] if msg else None

    try:
        farm     = load_from_api(user["farm_id"], user["api_key"])
        tracking = user.get("tracking") or DEFAULT_TRACKING
        state    = user.get("state") or {}

        # ── Автодетект новых ресурсов ─────────────────────────────────────────
        newly_found       = discover_dynamic_resources(farm)
        existing          = state.get("discovered_resources", [])
        dynamic_resources = merge_discovered(existing, newly_found)

        if dynamic_resources != existing:
            state["discovered_resources"] = dynamic_resources
            new_keys = {d["key"] for d in dynamic_resources} - {d["key"] for d in existing}
            if new_keys:
                labels = ", ".join(d["label"] for d in dynamic_resources
                                   if d["key"] in new_keys)
                send(chat_id,
                     f"🔍 <b>Найдены новые ресурсы для отслеживания:</b> {labels}\n"
                     f"Включи их в /settings если нужно.")

        events       = scan_farm(farm, tracking, dynamic_resources)
        status_text  = format_status_message(events, user["farm_id"])

        # ── Статус-сообщение: редактируем "загрузку" → готовый текст ─────────
        old_status_id = state.get("status_msg_id")

        if loading_msg_id:
            # Превращаем сообщение "⏳ Загружаю..." в статус
            edit_text(chat_id, loading_msg_id, status_text)
            new_status_id = loading_msg_id
        else:
            new_status_id = None

        # Закрепляем если это новое сообщение (не то, что уже закреплено)
        if new_status_id and new_status_id != old_status_id:
            if old_status_id:
                tg("unpinChatMessage",
                   chat_id=chat_id, message_id=old_status_id)
            tg("pinChatMessage",
               chat_id=chat_id, message_id=new_status_id,
               disable_notification=True)

        state["status_msg_id"] = new_status_id or old_status_id or 0
        update_user(chat_id, state=state)
        return

    except Exception as e:
        status_text = f"❌ Ошибка при загрузке фермы:\n<code>{e}</code>"

    # Fallback: редактируем или отправляем новое
    if loading_msg_id:
        edit_text(chat_id, loading_msg_id, status_text)
    else:
        send(chat_id, status_text)


def handle_stop(chat_id: int):
    user = get_user(chat_id)
    if not user:
        send(chat_id, "❌ Сначала зарегистрируйся: /start")
        return
    update_user(chat_id, active=False)
    send(chat_id,
         "⏸️ Уведомления <b>приостановлены</b>.\n"
         "Чтобы возобновить — /resume")


def handle_resume(chat_id: int):
    user = get_user(chat_id)
    if not user:
        send(chat_id, "❌ Сначала зарегистрируйся: /start")
        return
    if not user.get("farm_id") or not user.get("api_key"):
        send(chat_id,
             "❌ Сначала настрой ферму:\n"
             "/setfarm и /setkey")
        return
    update_user(chat_id, active=True)
    send(chat_id,
         "▶️ Уведомления <b>возобновлены</b>!\n"
         "Первый статус придёт через несколько минут.")


# ══════════════════════════════════════════════════════════════════════════════
# ОБРАБОТЧИК CALLBACK (inline кнопки настроек)
# ══════════════════════════════════════════════════════════════════════════════

def handle_callback(callback_query: dict):
    cq_id    = callback_query["id"]
    chat_id  = callback_query["from"]["id"]
    msg_id   = callback_query["message"]["message_id"]
    data     = callback_query.get("data", "")

    user = get_user(chat_id)
    if not user:
        answer_callback(cq_id, "Сначала /start")
        return

    tracking          = dict(user.get("tracking") or DEFAULT_TRACKING)
    state             = user.get("state") or {}
    dynamic_resources = state.get("discovered_resources", [])
    dynamic_keys      = {d["key"] for d in dynamic_resources}

    if data.startswith("toggle:"):
        key = data.split(":", 1)[1]
        # Разрешаем тогл и для статических, и для динамических ресурсов
        if key in tracking or key in dynamic_keys:
            tracking[key] = not tracking.get(key, False)
            update_user(chat_id, tracking=tracking)
            answer_callback(cq_id)
            edit_text(
                chat_id, msg_id,
                "⚙️ <b>Настройки отслеживания</b>\n\nВыбери что отслеживать:",
                reply_markup=settings_keyboard(tracking, dynamic_resources),
            )
        else:
            answer_callback(cq_id, "Неизвестный ресурс")

    elif data == "settings:close":
        answer_callback(cq_id, "✅ Сохранено!")
        # Итоговый список: статические + динамические
        lines = [
            f"{'✅' if tracking.get(k) else '❌'} {label}"
            for k, label in TRACK_LABELS
        ]
        for dr in dynamic_resources:
            icon = "✅" if tracking.get(dr["key"]) else "❌"
            lines.append(f"{icon} {dr['emoji']} {dr['label']}")
        edit_text(
            chat_id, msg_id,
            "✅ <b>Настройки сохранены!</b>\n\n" + "\n".join(lines)
        )

# ══════════════════════════════════════════════════════════════════════════════
# ДИСПЕТЧЕР ОБНОВЛЕНИЙ
# ══════════════════════════════════════════════════════════════════════════════

def dispatch(update: dict):
    # Inline-кнопки
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

    # Только личные сообщения (не группы)
    if msg["chat"]["type"] != "private":
        return

    cmd = text.split()[0].lower().split("@")[0]  # убираем @botname

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
    elif cmd in ("/help", "/h"):
        send(chat_id, HELP_TEXT)
    else:
        # Неизвестная команда — подсказываем
        if text.startswith("/"):
            send(chat_id, f"❓ Неизвестная команда.\n{HELP_TEXT}")

# ══════════════════════════════════════════════════════════════════════════════
# LONG POLLING ЦИКЛ
# ══════════════════════════════════════════════════════════════════════════════

def run_polling(duration_seconds: int = 21000):
    """
    Long polling цикл.
    duration=21000с (5ч 50м) — GitHub Actions перезапускает по cron каждые 6ч.
    """
    if not TG_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN не задан!")
        sys.exit(1)

    log.info(f"Бот запущен (long polling, duration={duration_seconds}s)")

    # Сбрасываем webhook если был
    tg("deleteWebhook", drop_pending_updates=False)

    offset  = 0
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
