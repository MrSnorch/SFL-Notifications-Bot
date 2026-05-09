#!/usr/bin/env python3
"""
sfl_supabase.py — Тонкая обёртка над Supabase REST API.
Не требует supabase-py — только requests.
"""

import json, os, logging
import requests

log = logging.getLogger("SFL")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY", "")

DEFAULT_TRACKING = {
    "crops": True, "trees": True, "stones": True, "iron": True,
    "gold": True, "crimstones": False, "oil": False, "salt": True,
    "sunstones": False, "fruits": True, "flowers": True,
    "honey": True, "mushrooms": False, "animals": False,
}


def _headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _url(table: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{table}"


# ── USERS ────────────────────────────────────────────────────────────────────

def get_user(telegram_id: int) -> dict | None:
    r = requests.get(
        _url("users"),
        headers=_headers(),
        params={"telegram_id": f"eq.{telegram_id}"},
        timeout=15,
    )
    if r.ok:
        data = r.json()
        return data[0] if data else None
    log.warning(f"get_user {telegram_id}: {r.status_code} {r.text[:200]}")
    return None


def upsert_user(telegram_id: int, **fields) -> dict | None:
    """Создаёт или обновляет пользователя. Возвращает обновлённую запись."""
    payload = {"telegram_id": telegram_id, **fields}
    r = requests.post(
        _url("users"),
        headers={**_headers(), "Prefer": "return=representation,resolution=merge-duplicates"},
        json=payload,
        timeout=15,
    )
    if r.ok:
        data = r.json()
        return data[0] if data else None
    log.warning(f"upsert_user {telegram_id}: {r.status_code} {r.text[:200]}")
    return None


def update_user(telegram_id: int, **fields) -> bool:
    r = requests.patch(
        _url("users"),
        headers=_headers(),
        params={"telegram_id": f"eq.{telegram_id}"},
        json=fields,
        timeout=15,
    )
    if not r.ok:
        log.warning(f"update_user {telegram_id}: {r.status_code} {r.text[:200]}")
    return r.ok


def get_all_active_users() -> list[dict]:
    r = requests.get(
        _url("users"),
        headers=_headers(),
        params={"active": "eq.true", "select": "*"},
        timeout=15,
    )
    if r.ok:
        return r.json()
    log.warning(f"get_all_active_users: {r.status_code} {r.text[:200]}")
    return []


# ── STATE (хранится в поле state jsonb) ──────────────────────────────────────

def load_state(telegram_id: int) -> dict:
    user = get_user(telegram_id)
    if user and isinstance(user.get("state"), dict):
        return user["state"]
    return {"status_msg_id": None, "ready_alerts": {}}


def save_state(telegram_id: int, state: dict) -> bool:
    return update_user(telegram_id, state=state)


# ── HELPERS ──────────────────────────────────────────────────────────────────

def get_or_create_user(telegram_id: int, username: str = "",
                        first_name: str = "") -> dict:
    user = get_user(telegram_id)
    if not user:
        user = upsert_user(
            telegram_id,
            username=username,
            first_name=first_name,
            farm_id="",
            api_key="",
            tracking=DEFAULT_TRACKING,
            state={},
            active=False,
        )
    return user or {}


def activate_user_if_ready(telegram_id: int) -> bool:
    """Активирует пользователя если заданы farm_id и api_key."""
    user = get_user(telegram_id)
    if user and user.get("farm_id") and user.get("api_key"):
        update_user(telegram_id, active=True)
        return True
    return False
