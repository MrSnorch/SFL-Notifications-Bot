#!/usr/bin/env python3
"""
sfl_scanner.py — Мульти-пользовательский сканер SFL.
Запускается GitHub Actions каждые 5 минут.
Читает всех активных пользователей из Supabase,
сканирует их фермы и шлёт уведомления в личные сообщения.
"""

import json, os, sys, time, logging
from datetime import datetime

# ── зависимости ──────────────────────────────────────────────────────────────
def _pip(pkg):
    os.system(f'"{sys.executable}" -m pip install {pkg} -q')

try:
    import requests
except ImportError:
    _pip("requests"); import requests

# ── инициализация логгера ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("SFL")

from sfl_core import (
    scan_farm, load_from_api, format_status_message, format_ready_alert,
    tg_send, tg_edit, tg_delete, tg_upsert_status, tg_pin_message,
    tg_unpin_message, Event,
    discover_dynamic_resources, merge_discovered,
    get_tz,
)
from sfl_supabase import (
    get_all_active_users, get_user, load_state, save_state, update_user,
)

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

# ══════════════════════════════════════════════════════════════════════════════
# ОБРАБОТКА АЛЕРТОВ ГОТОВНОСТИ
# ══════════════════════════════════════════════════════════════════════════════

def process_ready_alerts(chat_id: int, events: list[Event],
                         alerts_state: dict) -> dict:
    """
    Для каждого готового события:
    - Если нет алерта → отправляем новый.
    - Если счётчик изменился → редактируем.
    - Если событие больше не готово → удаляем алерт.
    """
    current_ready = {}

    for e in events:
        if e.ready_count <= 0:
            continue
        key  = e.name
        text = format_ready_alert(e)
        current_ready[key] = e
        stored = alerts_state.get(key)

        if stored is None:
            # Новый алерт
            mid = tg_send(TG_TOKEN, chat_id, text)
            if mid:
                alerts_state[key] = {
                    "mid": mid,
                    "ready_count": e.ready_count,
                    "count": e.count,
                }
        else:
            mid    = stored["mid"]
            old_rc = stored.get("ready_count", -1)
            old_c  = stored.get("count", e.count)
            if old_rc != e.ready_count or old_c != e.count:
                tg_edit(TG_TOKEN, chat_id, mid, text)
                alerts_state[key] = {
                    "mid": mid,
                    "ready_count": e.ready_count,
                    "count": e.count,
                }

    # Удаляем алерты которые больше не актуальны
    for key in list(alerts_state.keys()):
        if key not in current_ready:
            mid = alerts_state[key]["mid"]
            tg_delete(TG_TOKEN, chat_id, mid)
            del alerts_state[key]

    return alerts_state

# ══════════════════════════════════════════════════════════════════════════════
# СКАНИРОВАНИЕ ОДНОГО ПОЛЬЗОВАТЕЛЯ
# ══════════════════════════════════════════════════════════════════════════════

def scan_user(user: dict) -> "int | None":
    """Возвращает next_ready_at_ms (мс) — время ближайшего ещё-не-готового события,
    или None если всё уже готово / нет событий."""
    telegram_id = user["telegram_id"]
    farm_id     = user.get("farm_id", "")
    api_key     = user.get("api_key", "")
    tracking    = user.get("tracking") or {}
    username    = user.get("username") or user.get("first_name") or str(telegram_id)

    log.info(f"[{username}] Сканирование фермы {farm_id}...")

    try:
        farm = load_from_api(farm_id, api_key)
    except Exception as e:
        if hasattr(e, "response") and getattr(e.response, "status_code", None) == 429:
            raise  # пробрасываем 429 — кулдаун выставляет run_loop
        log.warning(f"[{username}] Ошибка API: {e}")
        return

    # ── Автодетект новых ресурсов ─────────────────────────────────────────────
    state             = load_state(telegram_id)
    existing          = state.get("discovered_resources", [])
    newly_found       = discover_dynamic_resources(farm)
    dynamic_resources = merge_discovered(existing, newly_found)

    if dynamic_resources != existing:
        state["discovered_resources"] = dynamic_resources
        new_keys = {d["key"] for d in dynamic_resources} - {d["key"] for d in existing}
        if new_keys:
            labels = ", ".join(
                d["label"] for d in dynamic_resources if d["key"] in new_keys
            )
            log.info(f"[{username}] Новые ресурсы: {labels}")
            tg_send(TG_TOKEN, telegram_id,
                    f"🔍 <b>Найдены новые ресурсы:</b> {labels}\n"
                    f"Включи их в /settings если нужно.")

    try:
        events = scan_farm(farm, tracking, dynamic_resources)
    except Exception as e:
        log.warning(f"[{username}] Ошибка сканирования: {e}")
        return

    status_msg_id = state.get("status_msg_id")
    alerts_state  = state.get("ready_alerts", {})

    # ── Статус-сообщение (редактируется, не пингует) ─────────────────────────
    user_tz     = get_tz(state.get("timezone"))
    status_text = format_status_message(events, farm_id, tz=user_tz)
    new_msg_id, is_new    = tg_upsert_status(TG_TOKEN, telegram_id, status_text, status_msg_id)
    state["status_msg_id"] = new_msg_id

    # Закрепляем если появилось новое сообщение (старое не удалось отредактировать)
    if is_new and new_msg_id:
        if status_msg_id and status_msg_id != new_msg_id:
            tg_unpin_message(TG_TOKEN, telegram_id, status_msg_id)
        ok = tg_pin_message(TG_TOKEN, telegram_id, new_msg_id)
        log.info(f"[{username}] {'📌 Закреплено' if ok else '⚠️ Не удалось закрепить'} статус-сообщение {new_msg_id}")

    # ── Алерты о готовности (пингуют) ────────────────────────────────────────
    state["ready_alerts"] = process_ready_alerts(
        telegram_id, events, alerts_state)

    save_state(telegram_id, state)
    ready_cnt = sum(1 for e in events if e.ready_count > 0)
    log.info(f"[{username}] Готово: {ready_cnt}/{len(events)} событий")

    # ── Сохраняем краткий снимок для админ-панели ─────────────────────────────
    try:
        last_scan = {
            "scanned_at_ms": int(time.time() * 1000),
            "farm_id": farm_id,
            "events": [
                {
                    "name":           e.name,
                    "emoji":          e.emoji,
                    "count":          e.count,
                    "ready_count":    e.ready_count,
                    "ready_at_ms":    e.ready_at_ms,
                    "pending_at_ms":  e.pending_at_ms,
                }
                for e in events
            ],
        }
        update_user(telegram_id, last_scan=last_scan)
    except Exception as e:
        log.warning(f"[{username}] Не удалось сохранить last_scan: {e}")

    # Возвращаем время ближайшего ещё не готового события (для предсказания)
    not_ready = [e for e in events if e.ready_count < e.count]
    return min((e.ready_at_ms for e in not_ready), default=None)


# Кулдауны при 429: telegram_id → время до которого пропускаем пользователя
_cooldowns: dict = {}
COOLDOWN_429 = 60  # 1 минута при повторном rate limit (сверх штатного интервала)

# Предсказание: telegram_id → unix-время (секунды) ближайшего события
_next_scan_at: dict = {}


# ══════════════════════════════════════════════════════════════════════════════
# ГЛАВНЫЙ ЦИКЛ
# ══════════════════════════════════════════════════════════════════════════════

def run_loop(duration_seconds: int = 21300, request_interval: int = 15):
    """
    Основной цикл сканера.
    duration=21300с (5ч 55м) — чуть меньше лимита GitHub Actions job 6ч.
    request_interval=15с — минимальный интервал между запросами согласно документации API.

    Предсказание: после каждого скана запоминаем ready_at_ms ближайшего события
    и не делаем API-запрос пока оно не наступило — уведомление приходит точно в момент готовности.
    """
    if not TG_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN не задан!")
        sys.exit(1)

    end_time  = time.time() + duration_seconds
    iteration = 0

    log.info(f"Сканер запущен. Duration={duration_seconds}s, request_interval={request_interval}s")

    while time.time() < end_time:
        iteration += 1
        remaining = int(end_time - time.time())
        log.info(f"=== Итерация {iteration}, осталось {remaining}с ===")

        users = get_all_active_users()
        log.info(f"Активных пользователей: {len(users)}")

        any_scanned = False
        for user in users:
            if time.time() >= end_time:
                break
            telegram_id = user["telegram_id"]
            username    = user.get("username") or user.get("first_name") or str(telegram_id)

            cooldown_until = _cooldowns.get(telegram_id, 0)
            if time.time() < cooldown_until:
                remaining_cd = int(cooldown_until - time.time())
                log.info(f"[{username}] Пропуск: rate limit, ещё {remaining_cd}с кулдауна")
                continue

            next_scheduled = _next_scan_at.get(telegram_id, 0)
            if time.time() < next_scheduled:
                next_t = datetime.fromtimestamp(next_scheduled).strftime("%H:%M:%S")
                log.info(f"[{username}] Пропуск: следующее событие в {next_t}")
                continue

            try:
                next_ready_ms = scan_user(user)
                any_scanned = True
                if next_ready_ms:
                    _next_scan_at[telegram_id] = next_ready_ms / 1000
                    next_t = datetime.fromtimestamp(next_ready_ms / 1000).strftime("%H:%M:%S")
                    log.info(f"[{username}] Следующий скан запланирован на {next_t}")
                else:
                    _next_scan_at.pop(telegram_id, None)
            except Exception as e:
                if hasattr(e, "response") and getattr(e.response, "status_code", None) == 429:
                    _cooldowns[telegram_id] = time.time() + COOLDOWN_429
                    log.warning(f"[{username}] 429 Rate limit — кулдаун {COOLDOWN_429}с")
                else:
                    raise

            # Пауза между запросами к API (только когда реально отправили запрос)
            sleep_sec = min(request_interval, max(0.0, end_time - time.time()))
            if sleep_sec > 0:
                log.info(f"Пауза {int(sleep_sec)}с...")
                time.sleep(sleep_sec)

        # Если никого не сканировали — спим до ближайшего события, не крутим вхолостую
        if not any_scanned:
            now = time.time()
            all_scheduled = [t for t in _next_scan_at.values() if t > now]
            cooldown_end  = max(_cooldowns.values(), default=0)
            candidates    = [*all_scheduled, cooldown_end]
            wait = max(2.0, min(candidates) - now) if candidates else request_interval
            wait = min(wait, max(0.0, end_time - now))
            if wait > 0:
                log.info(f"Все пользователи пропущены. Сон {int(wait)}с до следующего события...")
                time.sleep(wait)

    log.info("Сканер завершил работу.")


def run_once_user(telegram_id: int):
    """Сканирует одного пользователя по telegram_id — для matrix режима GitHub Actions."""
    if not TG_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN не задан!")
        sys.exit(1)
    user = get_user(telegram_id)
    if not user:
        log.error(f"Пользователь {telegram_id} не найден")
        sys.exit(1)
    if not user.get("active"):
        log.info(f"Пользователь {telegram_id} не активен, пропуск.")
        return
    scan_user(user)
    log.info(f"Готово: пользователь {telegram_id}")


def run_once():
    """Одиночный прогон — для тестирования."""
    if not TG_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN не задан!")
        sys.exit(1)

    users = get_all_active_users()
    log.info(f"Активных пользователей: {len(users)}")

    for user in users:
        scan_user(user)

    log.info("Готово.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SFL Multi-User Scanner")
    parser.add_argument("--user", type=int, default=None,
                        help="Сканировать только одного пользователя (для matrix режима)")
    parser.add_argument("--once", action="store_true",
                        help="Один прогон и выход")
    parser.add_argument("--duration", type=int, default=21300,
                        help="Длительность основного цикла (секунды)")
    parser.add_argument("--request-interval", "--interval", type=int, default=15,
                        help="Пауза между запросами к API (секунды, default: 15 — минимум по документации)")
    args = parser.parse_args()

    if args.user:
        run_once_user(args.user)
    elif args.once:
        run_once()
    else:
        run_loop(duration_seconds=args.duration, request_interval=args.request_interval)
