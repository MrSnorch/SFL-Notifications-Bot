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

from datetime import datetime, timedelta, timezone as _tz_mod
_utc_tz = _tz_mod.utc
from sfl_core import (
    scan_farm, load_from_api, format_status_message, format_ready_alert,
    tg_send, tg_edit, tg_delete, tg_upsert_status, tg_pin_message,
    tg_unpin_message, Event, split_ready_into_waves,
    discover_dynamic_resources, merge_discovered,
    get_tz, panel_keyboard, format_quest_notification,
    format_daily_reward_ready, format_daily_reminder,
)
from sfl_supabase import (
    get_all_active_users, get_user, load_state, save_state, update_user,
)

TG_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
SHARED_API_KEY = os.environ.get("SFL_API_KEY", "").strip()

# ══════════════════════════════════════════════════════════════════════════════
# ОБРАБОТКА АЛЕРТОВ ГОТОВНОСТИ
# ══════════════════════════════════════════════════════════════════════════════

def _dismiss_keyboard(alert_key: str) -> dict:
    """Инлайн-клавиатура с кнопкой ❌ для закрытия алерта."""
    return {"inline_keyboard": [[
        {"text": "❌", "callback_data": f"dismiss:{alert_key}"}
    ]]}

def process_ready_alerts(chat_id: int, events: list[Event],
                         alerts_state: dict,
                         repeat_count: int = 3,
                         repeat_interval_sec: int = 600,
                         repeat_by_key: dict | None = None) -> dict:
    """
    Для каждого готового события разбивает на волны и отправляет/редактирует алерт на волну.
    Ключ алерта: "{name}:{wave_anchor_ms}" — стабилен между сканами.
    repeat_by_key: {resource_key: {"count": n, "interval_min": m}} — per-resource настройки.
    Если ресурс отсутствует в repeat_by_key — используются глобальные repeat_count/repeat_interval_sec.
    """
    current_ready = {}
    now = time.time()
    now_ms = int(now * 1000)

    for e in events:
        if e.ready_count <= 0:
            continue

        # Определяем эффективные настройки повтора для этого ресурса
        r_key = getattr(e, "resource_key", "")
        if repeat_by_key and r_key and r_key in repeat_by_key:
            rr = repeat_by_key[r_key]
            eff_count    = max(0, min(5, int(rr.get("count", repeat_count))))
            eff_interval = int(rr.get("interval_min", repeat_interval_sec // 60)) * 60
        else:
            eff_count    = repeat_count
            eff_interval = repeat_interval_sec

        # Разбиваем готовые ресурсы на волны (группы по 5 минут)
        if e.ready_times and e.count > 1:
            ready_now = [t for t in e.ready_times if t <= now_ms + 30_000]
            waves = split_ready_into_waves(ready_now)
            if not waves:
                waves = [(e.ready_count, int(e.ready_at_ms))]
        else:
            waves = [(e.ready_count, int(e.ready_at_ms))]

        for wave_count, wave_anchor in waves:
            key  = f"{e.name}:{wave_anchor}"
            text = format_ready_alert(e, wave_count=wave_count)
            current_ready[key] = e
            stored = alerts_state.get(key)

            if stored is None:
                # Новый алерт
                mid = tg_send(TG_TOKEN, chat_id, text,
                              reply_markup=_dismiss_keyboard(key))
                if mid:
                    alerts_state[key] = {
                        "mid":          mid,
                        "ready_count":  wave_count,
                        "count":        e.count,
                        "sent_count":   0,
                        "last_sent_at": now,
                    }
            else:
                if stored.get("dismissed"):
                    # Пользователь закрыл алерт кнопкой ❌ — не повторяем.
                    # current_ready уже содержит этот ключ, поэтому cleanup не сработает
                    # пока wave_anchor не изменится (ресурс собран → новый скан).
                    continue
                mid       = stored["mid"]
                old_rc    = stored.get("ready_count", -1)
                old_c     = stored.get("count", e.count)
                sent      = stored.get("sent_count", 1)
                last_sent = stored.get("last_sent_at", now)

                if old_rc != wave_count or old_c != e.count:
                    # Счётчик изменился — редактируем
                    tg_edit(TG_TOKEN, chat_id, mid, text)
                    alerts_state[key] = {**stored, "ready_count": wave_count, "count": e.count}
                elif sent < eff_count and (now - last_sent) >= eff_interval:
                    # Повтор: новое сообщение (пингует), старое удаляем
                    new_mid = tg_send(TG_TOKEN, chat_id, text,
                                      reply_markup=_dismiss_keyboard(key))
                    if new_mid:
                        tg_delete(TG_TOKEN, chat_id, mid)
                        alerts_state[key] = {
                            "mid":          new_mid,
                            "ready_count":  wave_count,
                            "count":        e.count,
                            "sent_count":   sent + 1,
                            "last_sent_at": now,
                        }
                        log.info(f"[{chat_id}] Повтор алерта «{key}» ({sent + 1}/{eff_count})")
                elif sent >= eff_count:
                    log.debug(f"[{chat_id}] Алерт «{key}»: повторы исчерпаны ({sent}/{eff_count})")
                else:
                    remaining = int(eff_interval - (now - last_sent))
                    log.debug(f"[{chat_id}] Алерт «{key}»: следующий повтор через {remaining}с "
                              f"(отправлено {sent}/{eff_count})")

    # Удаляем алерты которые больше не актуальны
    for key in list(alerts_state.keys()):
        if key not in current_ready:
            mid = alerts_state[key].get("mid", 0)
            if mid:  # mid=0 означает dismissed — сообщение уже удалено пользователем
                tg_delete(TG_TOKEN, chat_id, mid)
            del alerts_state[key]

    return alerts_state

# ══════════════════════════════════════════════════════════════════════════════
# ШАРИК — ВСЕГДА ПОСЛЕДНЕЕ СООБЩЕНИЕ
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_balloon_last(chat_id: int, alerts_state: dict) -> dict:
    """
    Если уведомление шарика существует и после него появились другие уведомления
    (mid у других > mid шарика) — пересоздаём сообщение шарика чтобы оно было последним.
    """
    # Ищем ключ шарика (resource_key="balloon" → имя "Шарик:...")
    balloon_key = next(
        (k for k in alerts_state if k.startswith("Шарик:")), None
    )
    if not balloon_key:
        return alerts_state

    stored = alerts_state[balloon_key]
    if stored.get("dismissed"):
        return alerts_state

    balloon_mid = stored.get("mid", 0)
    if not balloon_mid:
        return alerts_state

    # Максимальный mid среди всех остальных активных алертов
    other_mids = [
        v["mid"] for k, v in alerts_state.items()
        if k != balloon_key and v.get("mid") and not v.get("dismissed")
    ]
    if not other_mids or max(other_mids) <= balloon_mid:
        return alerts_state  # шарик уже последний

    # Пересоздаём: удаляем старое, отправляем новое
    log.info(f"[{chat_id}] Пересоздаём уведомление шарика (не последнее)")
    from sfl_core import format_ready_alert, Event
    # Восстанавливаем Event из сохранённого состояния для форматирования
    dummy = Event("Шарик", "❤️", 0, stored.get("count", 1),
                  stored.get("ready_count", 1), resource_key="balloon")
    text = format_ready_alert(dummy)

    tg_delete(TG_TOKEN, chat_id, balloon_mid)
    new_mid = tg_send(TG_TOKEN, chat_id, text,
                      reply_markup=_dismiss_keyboard(balloon_key))
    if new_mid:
        alerts_state[balloon_key] = {**stored, "mid": new_mid}

    return alerts_state

def scan_user(user: dict) -> "int | None":
    """Возвращает next_ready_at_ms (мс) — время ближайшего ещё-не-готового события,
    или None если всё уже готово / нет событий."""
    telegram_id = user["telegram_id"]
    farm_id     = user.get("farm_id", "")
    api_key     = SHARED_API_KEY
    tracking    = user.get("tracking") or {}
    username    = user.get("username") or user.get("first_name") or str(telegram_id)

    log.info(f"[{username}] Сканирование фермы {farm_id}...")

    try:
        farm = load_from_api(farm_id, api_key)
    except Exception as e:
        if hasattr(e, "response") and getattr(e.response, "status_code", None) == 429:
            raise  # пробрасываем 429 — кулдаун выставляет run_loop
        log.warning(f"[{username}] Ошибка API: {e}")
        return None, None

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

    # ── Daily Rewards — данные для статус-сообщения ───────────────────────────
    _dr            = farm.get("dailyRewards") or {}
    _dr_streaks    = _dr.get("streaks", 0)
    _dr_collected_ms = (_dr.get("chest") or {}).get("collectedAt", 0)
    _now_utc       = datetime.now(_utc_tz)
    _today_utc_str = _now_utc.strftime("%Y-%m-%d")
    _dr_collected_today = (
        bool(_dr_collected_ms) and
        datetime.fromtimestamp(_dr_collected_ms / 1000, _utc_tz).strftime("%Y-%m-%d") == _today_utc_str
    )
    _tomorrow_utc  = (_now_utc + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    _next_reset_ms = int(_tomorrow_utc.timestamp() * 1000)
    daily_info = {"streaks": _dr_streaks, "collected_today": _dr_collected_today, "next_reset_ms": _next_reset_ms}

    # ── Статус-сообщение (редактируется, не пингует) ─────────────────────────
    user_tz     = get_tz(state.get("timezone"))
    status_text = format_status_message(events, farm_id, tz=user_tz,
                                        time_format=state.get("time_format", "both"),
                                        daily_info=daily_info)
    _lang       = state.get("lang", "ru")
    _is_active  = user.get("active", True)
    new_msg_id, is_new    = tg_upsert_status(TG_TOKEN, telegram_id, status_text, status_msg_id,
                                              reply_markup=panel_keyboard(_lang, _is_active))
    state["status_msg_id"] = new_msg_id

    # Закрепляем если появилось новое сообщение (старое не удалось отредактировать)
    if is_new and new_msg_id:
        if status_msg_id and status_msg_id != new_msg_id:
            tg_unpin_message(TG_TOKEN, telegram_id, status_msg_id)
        ok = tg_pin_message(TG_TOKEN, telegram_id, new_msg_id)
        log.info(f"[{username}] {'📌 Закреплено' if ok else '⚠️ Не удалось закрепить'} статус-сообщение {new_msg_id}")

    # ── Алерты о готовности (пингуют) ────────────────────────────────────────
    repeat          = state.get("repeat", {})
    repeat_count    = max(0, min(5, int(repeat.get("count", 2))))
    repeat_interval = int(repeat.get("interval_min", 10)) * 60
    # Per-resource repeat overrides: {resource_key: {"count": n, "interval_min": m}}
    repeat_by_key   = state.get("repeat_per_resource", {}) or {}
    state["ready_alerts"] = process_ready_alerts(
        telegram_id, events, alerts_state,
        repeat_count=repeat_count,
        repeat_interval_sec=repeat_interval,
        repeat_by_key=repeat_by_key,
    )

    # ── Quest (Pumpkin Pete) ──────────────────────────────────────────────────
    # Алерт о готовности шлёт process_ready_alerts через Event с resource_key="quest".
    # Здесь отправляем расширенное уведомление с описанием Questа (один раз).
    tg_data   = farm.get("telegram") or {}
    quest     = tg_data.get("quest") or {}
    q_name    = quest.get("name", "")
    q_choices = quest.get("choices", [])
    q_start   = quest.get("startAt", 0)
    last_quest_notified  = state.get("last_quest_notified", "")
    last_quest_start_at  = state.get("last_quest_start_at", 0)
    quest_msg_id         = state.get("quest_msg_id", 0)

    # Если startAt изменился — игрок взял квест (или пришёл новый).
    # Удаляем старое уведомление, если оно ещё не удалено вручную.
    if quest_msg_id and q_start != last_quest_start_at:
        tg_delete(TG_TOKEN, telegram_id, quest_msg_id)
        state["quest_msg_id"] = 0
        log.info(f"[{username}] Quest-уведомление удалено (startAt изменился)")

    if q_name and not q_choices and q_start and q_start <= int(time.time() * 1000):
        if q_name != last_quest_notified:
            # Новый Quest стал доступен — шлём детальное сообщение с кнопкой ❌
            text = format_quest_notification(q_name, lang=_lang)
            dismiss_kb = {"inline_keyboard": [[{"text": "❌", "callback_data": "quest_dismiss"}]]}
            mid = tg_send(TG_TOKEN, telegram_id, text, reply_markup=dismiss_kb)
            state["last_quest_notified"] = q_name
            state["last_quest_start_at"] = q_start
            state["quest_msg_id"]        = mid or 0
            log.info(f"[{username}] Новый Quest: {q_name}")

    state["ready_alerts"] = _ensure_balloon_last(telegram_id, state["ready_alerts"])

    # ── Daily Rewards ─────────────────────────────────────────────────────────
    _utc_hour            = _now_utc.hour
    _daily_notified_date = state.get("daily_notified_date", "")

    # Первый скан нового UTC-дня → удаляем старое напоминание и шлём midnight-уведомление
    if _today_utc_str != _daily_notified_date:
        _old_mid = state.get("daily_reminder_msg_id", 0)
        if _old_mid:
            tg_delete(TG_TOKEN, telegram_id, _old_mid)
            state["daily_reminder_msg_id"] = 0
        # Шлём только если награда ещё не собрана — иначе просто фиксируем дату
        if not _dr_collected_today:
            text = format_daily_reward_ready(_dr_streaks, lang=_lang)
            tg_send(TG_TOKEN, telegram_id, text, silent=True)
            log.info(f"[{username}] Daily Rewards: midnight-уведомление (стрик {_dr_streaks})")
        else:
            log.info(f"[{username}] Daily Rewards: новый день, но награда уже собрана — без уведомления")
        state["daily_notified_date"]           = _today_utc_str
        state["daily_reminder_hours_sent"]     = []
        state["daily_reminder_dismissed_date"] = ""

    # Награда собрана → удаляем напоминание если висит
    if _dr_collected_today:
        _old_mid = state.get("daily_reminder_msg_id", 0)
        if _old_mid:
            tg_delete(TG_TOKEN, telegram_id, _old_mid)
            state["daily_reminder_msg_id"] = 0
            log.info(f"[{username}] Daily Rewards: собрана, напоминание удалено")

    # Ежечасные напоминания в 19-23 UTC если награда не собрана и не dismissed
    elif 19 <= _utc_hour <= 23:
        _dismissed_date = state.get("daily_reminder_dismissed_date", "")
        _hours_sent     = state.get("daily_reminder_hours_sent", [])
        if _today_utc_str != _dismissed_date and _utc_hour not in _hours_sent:
            _hours_left = 24 - _utc_hour
            text = format_daily_reminder(_dr_streaks, _hours_left, lang=_lang)
            _old_mid = state.get("daily_reminder_msg_id", 0)
            if _old_mid:
                tg_delete(TG_TOKEN, telegram_id, _old_mid)
            _dismiss_kb = {"inline_keyboard": [[{"text": "❌", "callback_data": "daily_dismiss"}]]}
            _mid = tg_send(TG_TOKEN, telegram_id, text, reply_markup=_dismiss_kb)
            _hours_sent.append(_utc_hour)
            state["daily_reminder_hours_sent"] = _hours_sent
            state["daily_reminder_msg_id"]     = _mid or 0
            log.info(f"[{username}] Daily Rewards: напоминание {_utc_hour}:00 UTC (осталось {_hours_left}ч)")

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

    # Возвращаем время и само событие ближайшего ещё не готового события (для предсказания).
    # Берём только будущие timestamps — прошедшие означают что событие уже готово
    # но не собрано, уведомление уже отправлено, незачем сканировать снова.
    now_ms    = int(time.time() * 1000)
    not_ready = [e for e in events if e.ready_count < e.count and e.ready_at_ms > now_ms]
    if not_ready:
        next_event = min(not_ready, key=lambda e: e.ready_at_ms)
        return next_event.ready_at_ms, next_event
    return None, None


# Кулдауны при 429: telegram_id → время до которого пропускаем пользователя
_cooldowns: dict = {}
COOLDOWN_429 = 60  # 1 минута при повторном rate limit (сверх штатного интервала)

# Предсказание: telegram_id → unix-время (секунды) ближайшего события
_next_scan_at: dict = {}


# ══════════════════════════════════════════════════════════════════════════════
# ОТПРАВКА АЛЕРТА БЕЗ СКАНА (для matrix-режима: ранний подъём)
# ══════════════════════════════════════════════════════════════════════════════

def _fire_pending_alert(telegram_id: int, event: "Event") -> None:
    """
    Отправляет алерт о готовности события не делая запрос к игровому API.
    Вызывается когда мы проснулись раньше планового скана именно ради этого события.
    Использует волновой ключ "{name}:{wave_anchor_ms}" совместимый с process_ready_alerts.
    """
    state        = load_state(telegram_id)
    alerts_state = state.get("ready_alerts", {})

    # Вычисляем количество готовых на момент пробуждения.
    # max(1, ...) — мы проснулись именно ради этого события, минимум 1 гарантированно готов
    # (ранний подъём на 3с может дать sum=0 до наступления таймера).
    now_ms = int(time.time() * 1000)
    if event.ready_times:
        event.ready_count = max(1, sum(1 for t in event.ready_times if t <= now_ms))
    else:
        event.ready_count = event.count  # fallback для ресурсов без ready_times

    # Определяем волну: первый готовый/почти готовый ресурс задаёт anchor
    if event.ready_times and event.count > 1:
        ready_now = [t for t in event.ready_times if t <= now_ms + 30_000]
        waves = split_ready_into_waves(ready_now)
        wave_count, wave_anchor = waves[0] if waves else (event.ready_count, int(event.ready_at_ms))
        wave_count = max(1, wave_count)
    else:
        wave_count  = event.ready_count
        wave_anchor = int(event.ready_at_ms)

    key  = f"{event.name}:{wave_anchor}"
    text = format_ready_alert(event, wave_count=wave_count)
    mid  = tg_send(TG_TOKEN, telegram_id, text,
                   reply_markup=_dismiss_keyboard(key))
    if mid:
        alerts_state[key] = {
            "mid":          mid,
            "ready_count":  wave_count,
            "count":        event.count,
            "sent_count":   0,
            "last_sent_at": time.time(),
        }
        state["ready_alerts"] = alerts_state
        save_state(telegram_id, state)


# ══════════════════════════════════════════════════════════════════════════════
# ГЛАВНЫЙ ЦИКЛ
# ══════════════════════════════════════════════════════════════════════════════

def run_loop(duration_seconds: int = 21300, request_interval: int = 30):
    """
    Основной цикл сканера.
    duration=21300с (5ч 55м) — чуть меньше лимита GitHub Actions job 6ч.
    request_interval=30с — интервал между запросами к API.

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
                next_ready_ms, _ = scan_user(user)
                any_scanned = True
                if next_ready_ms:
                    _next_scan_at[telegram_id] = next_ready_ms / 1000
                    next_t = datetime.fromtimestamp(next_ready_ms / 1000).strftime("%H:%M:%S")
                    log.info(f"[{username}] Следующий скан запланирован на {next_t}")
                else:
                    # Всё готово — проверяем раз в 5 минут
                    _next_scan_at[telegram_id] = time.time() + 300
                    log.info(f"[{username}] Всё готово, следующий скан через 5 мин")
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


def run_loop_user(telegram_id: int, duration_seconds: int = 20700,
                  request_interval: int = 30):
    """
    Длинный цикл для одного пользователя — для matrix режима GitHub Actions.
    Каждый matrix job крутит свой цикл ~5ч45м на отдельном runner (= отдельный IP).
    """
    if not TG_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN не задан!")
        sys.exit(1)

    end_time = time.time() + duration_seconds

    log.info(f"[{telegram_id}] Цикл запущен. Duration={duration_seconds}s, interval={request_interval}s")

    pending_event    = None  # событие которое готово после раннего подъёма
    last_scan_time   = 0.0   # время последнего scan_user — для соблюдения интервала

    while time.time() < end_time:
        # Перечитываем юзера — tracking/настройки могут меняться через бота
        user = get_user(telegram_id)
        if not user or not user.get("active"):
            log.info(f"[{telegram_id}] Пользователь деактивирован, выход.")
            break

        # ── Ранний подъём: шлём алерт без скана ────────────────────────────
        if pending_event is not None:
            log.info(f"[{telegram_id}] Ранний подъём — шлём алерт «{pending_event.name}» без скана")
            _fire_pending_alert(telegram_id, pending_event)
            pending_event = None
            # Доспать оставшееся время до request_interval чтобы не получить 429
            remaining = request_interval - (time.time() - last_scan_time)
            if remaining > 0:
                log.info(f"[{telegram_id}] Ждём {int(remaining)}с до следующего скана...")
                time.sleep(remaining)
            continue

        # ── Обычный скан ────────────────────────────────────────────────────
        try:
            next_ready_ms, next_event = scan_user(user)
        except Exception as e:
            if hasattr(e, "response") and getattr(e.response, "status_code", None) == 429:
                log.warning(f"[{telegram_id}] 429 Rate limit на этом IP — выходим для смены runner'а")
                sys.exit(2)  # Код 2 = rate limited, нужен новый IP
            else:
                log.warning(f"[{telegram_id}] Ошибка: {e}")
            next_ready_ms, next_event = None, None

        last_scan_time = time.time()

        # Спим request_interval секунд, но просыпаемся раньше если событие
        # наступает до следующего планового скана — уведомление придёт точно в срок
        now = time.time()
        sleep_sec = request_interval
        if next_ready_ms:
            secs_until_event = (next_ready_ms / 1000) - now
            if 0 < secs_until_event < request_interval:
                sleep_sec     = max(0, secs_until_event - 3)
                pending_event = next_event  # запоминаем — после сна пошлём без скана
                next_t = datetime.fromtimestamp(next_ready_ms / 1000).strftime("%H:%M:%S")
                log.info(f"[{telegram_id}] Событие «{next_event.name}» в {next_t} — "
                         f"просыпаемся раньше через {int(sleep_sec)}с, скан пропустим")

        sleep_sec = min(sleep_sec, max(0.0, end_time - now))
        if sleep_sec > 0:
            time.sleep(sleep_sec)

    log.info(f"[{telegram_id}] Цикл завершён.")


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
    parser.add_argument("--request-interval", "--interval", type=int, default=30,
                        help="Пауза между запросами к API (секунды, default: 30)")
    args = parser.parse_args()

    if args.user:
        run_loop_user(args.user, duration_seconds=args.duration,
                      request_interval=args.request_interval)
    elif args.once:
        run_once()
    else:
        run_loop(duration_seconds=args.duration, request_interval=args.request_interval)
