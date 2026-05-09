#!/usr/bin/env python3
"""
sfl_core.py — Общая логика сканирования SFL (без GUI, без GitHub Variables).
Используется и сканером, и ботом.
"""

import json, os, time, logging
from datetime import datetime, timezone as _dtz, timedelta as _td
try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    def _make_tz(name: str):
        try:
            return _ZoneInfo(name)
        except Exception:
            return _dtz(_td(hours=0))
except ImportError:
    def _make_tz(name: str):  # type: ignore
        OFFSETS = {
            "UTC": 0, "Europe/London": 0,
            "Europe/Lisbon": 0, "Atlantic/Azores": -1,
            "Europe/Paris": 1, "Europe/Berlin": 1, "Europe/Warsaw": 1,
            "Europe/Kiev": 2, "Europe/Bucharest": 2,
            "Europe/Moscow": 3, "Europe/Istanbul": 3,
            "Asia/Dubai": 4, "Asia/Baku": 4,
            "Asia/Tashkent": 5, "Asia/Yekaterinburg": 5,
            "Asia/Kolkata": 5,  # +5:30 approx
            "Asia/Dhaka": 6, "Asia/Almaty": 6,
            "Asia/Bangkok": 7, "Asia/Novosibirsk": 7,
            "Asia/Shanghai": 8, "Asia/Singapore": 8,
            "Asia/Tokyo": 9, "Asia/Seoul": 9,
            "Australia/Sydney": 10,
            "Pacific/Auckland": 12,
            "America/New_York": -5, "America/Chicago": -6,
            "America/Denver": -7, "America/Los_Angeles": -8,
        }
        return _dtz(_td(hours=OFFSETS.get(name, 0)))

# Глобальный дефолт (используется только если tz не передан явно)
UA_TZ = _make_tz("Europe/Kiev")

def get_tz(tz_name: str | None):
    """Возвращает объект timezone по имени из TIMEZONES."""
    if not tz_name:
        return UA_TZ
    return _make_tz(tz_name)

# ──────────────────────────────────────────────────────────────────────────────
# Список часовых поясов для выбора в боте
# Формат: (tz_name, emoji_flag, label, utc_offset_label)
# ──────────────────────────────────────────────────────────────────────────────
TIMEZONES: list[tuple[str, str, str]] = [
    ("Europe/London",      "🇬🇧", "Лондон",          "UTC+0/+1"),
    ("Europe/Paris",       "🇫🇷", "Париж / Берлин",  "UTC+1/+2"),
    ("Europe/Warsaw",      "🇵🇱", "Варшава",          "UTC+1/+2"),
    ("Europe/Kiev",        "🇺🇦", "Киев",             "UTC+2/+3"),
    ("Europe/Bucharest",   "🇷🇴", "Бухарест",         "UTC+2/+3"),
    ("Europe/Moscow",      "🇷🇺", "Москва",           "UTC+3"),
    ("Europe/Istanbul",    "🇹🇷", "Стамбул",          "UTC+3"),
    ("Asia/Dubai",         "🇦🇪", "Дубай",            "UTC+4"),
    ("Asia/Baku",          "🇦🇿", "Баку",             "UTC+4"),
    ("Asia/Tashkent",      "🇺🇿", "Ташкент",          "UTC+5"),
    ("Asia/Kolkata",       "🇮🇳", "Индия",            "UTC+5:30"),
    ("Asia/Dhaka",         "🇧🇩", "Дакка",            "UTC+6"),
    ("Asia/Almaty",        "🇰🇿", "Алматы",           "UTC+6"),
    ("Asia/Bangkok",       "🇹🇭", "Бангкок",          "UTC+7"),
    ("Asia/Novosibirsk",   "🇷🇺", "Новосибирск",      "UTC+7"),
    ("Asia/Shanghai",      "🇨🇳", "Пекин / Шанхай",  "UTC+8"),
    ("Asia/Singapore",     "🇸🇬", "Сингапур",         "UTC+8"),
    ("Asia/Tokyo",         "🇯🇵", "Токио",            "UTC+9"),
    ("Asia/Seoul",         "🇰🇷", "Сеул",             "UTC+9"),
    ("Australia/Sydney",   "🇦🇺", "Сидней",           "UTC+10/+11"),
    ("Pacific/Auckland",   "🇳🇿", "Окленд",           "UTC+12/+13"),
    ("America/New_York",   "🇺🇸", "Нью-Йорк",        "UTC-5/-4"),
    ("America/Chicago",    "🇺🇸", "Чикаго",           "UTC-6/-5"),
    ("America/Denver",     "🇺🇸", "Денвер",           "UTC-7/-6"),
    ("America/Los_Angeles","🇺🇸", "Лос-Анджелес",    "UTC-8/-7"),
    ("UTC",                "🌐", "UTC",               "UTC+0"),
]

# Быстрый поиск по tz_name
_TZ_MAP = {tz: (flag, label, utc) for tz, flag, label, utc in TIMEZONES}

def tz_display_name(tz_name: str | None) -> str:
    """Возвращает читаемое название + UTC-смещение для отображения."""
    if not tz_name:
        tz_name = "Europe/Kiev"
    if tz_name in _TZ_MAP:
        flag, label, utc = _TZ_MAP[tz_name]
        return f"{flag} {label} ({utc})"
    return tz_name

try:
    import requests
except ImportError:
    os.system(f'python -m pip install requests -q')
    import requests

log = logging.getLogger("SFL")

# ══════════════════════════════════════════════════════════════════════════════
# КОНСТАНТЫ ВРЕМЕНИ РОСТА
# ══════════════════════════════════════════════════════════════════════════════

CROP_GROW_MS: dict[str, int] = {
    "Sunflower":   60_000,
    "Potato":      5*60_000,
    "Rhubarb":     10*60_000,
    "Pumpkin":     30*60_000,
    "Zucchini":    30*60_000,
    "Carrot":      3_600_000,
    "Yam":         3_600_000,
    "Cabbage":     2*3_600_000,
    "Broccoli":    2*3_600_000,
    "Soybean":     3*3_600_000,
    "Beetroot":    4*3_600_000,
    "Hot Pepper":  4*3_600_000,
    "Cauliflower": 8*3_600_000,
    "Parsnip":     12*3_600_000,
    "Coffee":      12*3_600_000,
    "Eggplant":    16*3_600_000,
    "Onion":       20*3_600_000,
    "Corn":        20*3_600_000,
    "Radish":      24*3_600_000,
    "Wheat":       24*3_600_000,
    "Turnip":      24*3_600_000,
    "Kale":        36*3_600_000,
    "Artichoke":   36*3_600_000,
    "Barley":      48*3_600_000,
    "Rice":        32*3_600_000,
    "Olive":       24*3_600_000,
    "Tomato":      2*3_600_000,
    "Lemon":       4*3_600_000,
}

FRUIT_REGROW_MS: dict[str, int] = {
    # Значения из PATCH_FRUIT_SEEDS[seed].plantSeconds в игре (fruitPlanted.ts)
    "Tomato":    2*3_600_000,   # Tomato Seed
    "Lemon":     4*3_600_000,   # Lemon Seed
    "Blueberry": 6*3_600_000,   # Blueberry Seed
    "Orange":    8*3_600_000,   # Orange Seed
    "Apple":     12*3_600_000,  # Apple Seed
    "Banana":    12*3_600_000,  # Banana Plant
    "Celestine": 6*3_600_000,   # Celestine Seed
    "Lunara":    12*3_600_000,  # Lunara Seed
    "Duskberry": 24*3_600_000,  # Duskberry Seed
    "Grape":     12*3_600_000,  # Grape Seed (greenhouse)
}

# Время роста цветов: readyAt = plantedAt + BASE_MS (без множителей!)
# Бусты уже зашиты в plantedAt игрой через сдвиг назад по формуле:
#   plantedAt = createdAt - (baseSecs - boostedSecs) * 1000
# Поэтому readyAt = plantedAt + baseSecs * 1000 — никаких коэффициентов не нужно.
#
# Источник: FLOWER_SEEDS[seed].plantSeconds из flowers.ts (игровой код):
#   Sunpetal Seed = 24h: Pansy, Cosmos, Prism Petal (все цвета)
#   Bloom Seed    = 48h: Balloon Flower, Daffodil, Celestial Frostbloom (все цвета)
#   Lily Seed     = 120h: Carnation, Lotus, Primula Enigma (все цвета)
#   Edelweiss Seed = 72h: Edelweiss (все цвета)
#   Gladiolus Seed = 72h: Gladiolus (все цвета)
#   Lavender Seed  = 72h: Lavender (все цвета)
#   Clover Seed    = 72h: Clover (все цвета)
def _build_flower_grow_ms() -> dict[str, int]:
    _COLORS = ("Red", "Yellow", "Purple", "White", "Blue")
    _H = 3_600_000
    result: dict[str, int] = {}
    # 24h — Sunpetal Seed
    for c in _COLORS:
        result[f"{c} Pansy"] = 24*_H
        result[f"{c} Cosmos"] = 24*_H
    result["Prism Petal"] = 24*_H
    # 48h — Bloom Seed
    for c in _COLORS:
        result[f"{c} Balloon Flower"] = 48*_H
        result[f"{c} Daffodil"] = 48*_H
    result["Celestial Frostbloom"] = 48*_H
    # 72h — Edelweiss / Gladiolus / Lavender / Clover Seeds
    for c in _COLORS:
        for family in ("Edelweiss", "Gladiolus", "Lavender", "Clover"):
            result[f"{c} {family}"] = 72*_H
    # 120h — Lily Seed
    for c in _COLORS:
        result[f"{c} Carnation"] = 120*_H
        result[f"{c} Lotus"] = 120*_H
    result["Primula Enigma"] = 120*_H
    return result

FLOWER_GROW_MS: dict[str, int] = _build_flower_grow_ms()
_FLOWER_GROW_MS_DEFAULT = 48*3_600_000  # fallback: Bloom Seed

TREE_RESPAWN_MS     = 2  * 3_600_000
STONE_RESPAWN_MS    = 4  * 3_600_000
IRON_RESPAWN_MS     = 8  * 3_600_000
GOLD_RESPAWN_MS     = 24 * 3_600_000
CRIM_RESPAWN_MS     = 36 * 3_600_000
OIL_RESPAWN_MS      = 24 * 3_600_000
SALT_RESPAWN_MS     = 8  * 3_600_000
SUNSTONE_RESPAWN_MS = 72 * 3_600_000
MUSH_SPAWN_MS       = 16 * 3_600_000

# ══════════════════════════════════════════════════════════════════════════════
# АВТОДЕТЕКТ ДИНАМИЧЕСКИХ РЕСУРСОВ
# ══════════════════════════════════════════════════════════════════════════════

# Ключи, которые уже обрабатываются выделенным кодом — не трогать при автодетекте
KNOWN_RESOURCE_KEYS = {
    "crops", "trees", "stones", "iron", "gold", "crimstones",
    "oilReserves", "sunstones", "fruitPatches", "flowers",
    "beehives", "mushrooms", "henHouse", "barn", "saltFarm",
    # нересурсные поля верхнего уровня
    "coins", "balance", "previousBalance", "inventory", "previousInventory",
    "shipments", "gems", "flower", "choreBoard", "bank", "bumpkin",
    "wardrobe", "previousWardrobe", "home", "interior", "island",
    "farmHands", "greenhouse", "calendar", "vip", "createdAt", "stock",
    "trades", "expandedAt", "buildings", "collectibles", "pumpkinPlaza",
    "megastore", "dailyRewards", "buffs", "floatingIsland", "farmActivity",
    "milestones", "fishing", "crabTraps", "chores", "kingdomChores",
    "conversations", "mailbox", "socialTasks",
}

# Поля-таймеры (в порядке приоритета)
_TIMER_FIELDS = ["readyAt", "harvestedAt", "minedAt", "collectedAt",
                 "attachedUntil", "finishedAt", "completedAt"]

# Эмодзи по ключевым словам в названии ресурса
_EMOJI_HINTS = {
    "lava": "🌋", "pit": "🕳️", "forge": "🔥", "volcano": "🌋",
    "well": "💧", "lake": "🏞️", "pond": "🐟", "fish": "🐟",
    "mine": "⛏️", "rock": "🪨", "gem": "💎", "crystal": "🔮",
    "plant": "🌿", "tree": "🌳", "flower": "🌸", "crop": "🌾",
    "chest": "📦", "box": "📦", "crate": "🗃️",
    "portal": "🔮", "ruin": "🏚️", "quest": "📜", "task": "📋",
    "bee": "🐝", "hive": "🍯", "honey": "🍯",
    "animal": "🐾", "cow": "🐄", "chicken": "🐔",
    "trap": "🪤", "crab": "🦀",
}


def _guess_emoji(key: str) -> str:
    kl = key.lower()
    for word, em in _EMOJI_HINTS.items():
        if word in kl:
            return em
    return "⏰"


def _key_to_label(key: str) -> str:
    """lavaPits → Lava Pits"""
    import re
    s = re.sub(r"([A-Z])", r" \1", key).strip()
    return s.title()


def discover_dynamic_resources(farm: dict) -> list[dict]:
    """
    Сканирует ответ API и находит UUID-коллекции с таймерами,
    которые НЕ обрабатываются выделенным кодом.

    Возвращает список словарей:
        {"key": "lavaPits", "label": "Lava Pits", "emoji": "🌋",
         "timer_field": "readyAt"}
    """
    found = []
    for key, val in farm.items():
        if key in KNOWN_RESOURCE_KEYS:
            continue
        if not isinstance(val, dict) or not val:
            continue
        # Значения должны быть словарями (UUID-keyed коллекция)
        sample = next(iter(val.values()), None)
        if not isinstance(sample, dict):
            continue
        # Ищем таймерное поле
        for tf in _TIMER_FIELDS:
            if tf in sample:
                found.append({
                    "key":         key,
                    "label":       _key_to_label(key),
                    "emoji":       _guess_emoji(key),
                    "timer_field": tf,
                })
                break
    return found


def merge_discovered(existing: list[dict], new_found: list[dict]) -> list[dict]:
    """
    Объединяет ранее найденные ресурсы с новыми.
    Добавляет только те, которых ещё нет, сохраняя порядок.
    """
    existing_keys = {d["key"] for d in existing}
    merged = list(existing)
    for item in new_found:
        if item["key"] not in existing_keys:
            merged.append(item)
    return merged


def scan_dynamic_resource(farm: dict, key: str, timer_field: str,
                           label: str, emoji: str) -> "Event | None":
    """
    Универсальный сканер для UUID-коллекций с readyAt-подобным таймером.
    Работает для любого нового типа ресурса без отдельного кода.
    """
    times = []
    now_ms = int(time.time() * 1000)
    for _, item in farm.get(key, {}).items():
        if not isinstance(item, dict):
            continue
        t = _fix_ts(item.get(timer_field, 0))
        if t:
            times.append(t)
    if not times:
        return None
    times.sort()
    rc = sum(1 for t in times if t <= now_ms)
    pnd = times[rc] if rc < len(times) else times[-1]
    return Event(label, emoji, times[0], len(times), rc,
                 f"{rc}/{len(times)} готово" if rc else f"{len(times)} шт.",
                 pending_at_ms=pnd, last_ready_at_ms=times[-1],
                 resource_key=key)


DEFAULT_TRACKING = {
    "crops": True, "trees": True, "stones": True, "iron": True,
    "gold": True, "crimstones": False, "oil": False, "salt": True,
    "sunstones": False, "fruits": True, "flowers": True,
    "honey": True, "mushrooms": False, "animals": False,
}

TRACK_LABELS = [
    ("crops",      "🌾 Урожай"),
    ("trees",      "🪵 Деревья"),
    ("stones",     "🪨 Камни"),
    ("iron",       "⛏️ Железо"),
    ("gold",       "🥇 Золото"),
    ("crimstones", "💎 Криминстоун"),
    ("oil",        "🛢️ Нефть"),
    ("salt",       "🧂 Соль"),
    ("sunstones",  "🌟 Санстоун"),
    ("fruits",     "🍎 Фрукты"),
    ("flowers",    "🌸 Цветы"),
    ("honey",      "🍯 Мёд"),
    ("mushrooms",  "🍄 Грибы"),
    ("animals",    "🐄 Животные"),
]

# ══════════════════════════════════════════════════════════════════════════════
# EVENT CLASS
# ══════════════════════════════════════════════════════════════════════════════

class Event:
    def __init__(self, name, emoji, ready_at_ms, count=1, ready_count=0,
                 extra="", pending_at_ms=None, last_ready_at_ms=None, ready_times=None,
                 resource_key=""):
        self.name         = name
        self.emoji        = emoji
        self.ready_at_ms  = ready_at_ms
        self.count        = count
        self.ready_count  = ready_count
        self.extra        = extra
        self.pending_at_ms = pending_at_ms if pending_at_ms is not None else ready_at_ms
        self.last_ready_at_ms = last_ready_at_ms if last_ready_at_ms is not None else ready_at_ms
        # Полный отсортированный список таймов готовности — нужен для точного подсчёта
        # в _fire_pending_alert, когда уведомление шлётся без нового API-запроса.
        self.ready_times  = ready_times
        # Ключ категории ресурса (crops / trees / stones / …) для per-resource настроек повтора
        self.resource_key = resource_key

    def is_ready(self):
        return self.ready_at_ms <= int(time.time() * 1000)

    def time_left_ms(self):
        return max(0, self.ready_at_ms - int(time.time() * 1000))

    def fmt_pending_time_left(self):
        ms = max(0, self.pending_at_ms - int(time.time() * 1000))
        if ms == 0: return "ГОТОВО!"
        s = ms // 1000; h, rem = divmod(s, 3600); m, sc = divmod(rem, 60)
        if h >= 24:
            d = h // 24; h = h % 24
            return f"{d}д {h:02d}:{m:02d}:{sc:02d}"
        return f"{h:02d}:{m:02d}:{sc:02d}"

    def fmt_pending_ready_time(self, tz=None):
        return datetime.fromtimestamp(
            self.pending_at_ms / 1000, tz=tz or UA_TZ).strftime("%H:%M")

# ══════════════════════════════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════════════════════════════

def load_from_api(farm_id: str, api_key: str, retries: int = 3, timeout: int = 30) -> dict:
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(
                f"https://api.sunflower-land.com/community/farms/{farm_id}",
                headers={"x-api-key": api_key},
                timeout=timeout,
            )
            if r.status_code == 429:
                r.raise_for_status()  # пробрасываем 429 сразу — не ретраим
            break
        except requests.exceptions.Timeout as e:
            last_exc = e
            if attempt < retries:
                import time as _time
                _time.sleep(2 ** attempt)  # 2s, 4s
            else:
                raise
    else:
        raise last_exc
    r.raise_for_status()
    data = r.json()
    if isinstance(data, str):
        import json as _json
        data = _json.loads(data)
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected API response type: {type(data).__name__}")
    farm = data.get("farm", data)
    # Handle double-encoded JSON: API sometimes returns farm as a JSON string
    if isinstance(farm, str):
        import json as _json
        farm = _json.loads(farm)
    if not isinstance(farm, dict):
        raise ValueError(f"Unexpected 'farm' type: {type(farm).__name__}, value: {str(farm)[:120]}")
    return farm

# ══════════════════════════════════════════════════════════════════════════════
# СКАНИРОВАНИЕ
# ══════════════════════════════════════════════════════════════════════════════

def _d(val) -> dict:
    """Return val if it's a dict, else {}.  Guards against API returning strings."""
    return val if isinstance(val, dict) else {}

def _l(val) -> list:
    """Return val if it's a list, else [].  Guards against API returning strings."""
    return val if isinstance(val, list) else []
def _fix_ts(ts):
    """Конвертирует секунды → миллисекунды если нужно."""
    if ts and 0 < ts < 10_000_000_000:
        return ts * 1000
    return ts

def scan_farm(farm: dict, track: dict,
              dynamic_resources: list[dict] | None = None) -> list[Event]:
    events = []
    now_ms = int(time.time() * 1000)

    # ── CROPS ─────────────────────────────────────────────────────────────────
    if track.get("crops", True):
        crop_map: dict[str, list] = {}
        for pid, plot in farm.get("crops", {}).items():
            if not isinstance(plot, dict):
                continue
            c = plot.get("crop")
            if not c or not c.get("name"):
                continue
            name = c["name"]
            rdy = _fix_ts(c.get("readyAt", 0))
            if rdy:
                crop_map.setdefault(name, []).append(rdy)
                continue
            planted = _fix_ts(c.get("plantedAt", 0))
            if not planted:
                continue
            grow = CROP_GROW_MS.get(name, 3_600_000)
            crop_map.setdefault(name, []).append(planted + grow)
        for name, times in crop_map.items():
            times.sort()
            rc = sum(1 for t in times if t <= now_ms)
            pnd = times[rc] if rc < len(times) else times[-1]
            events.append(Event(name, "🌾", times[0], len(times), rc,
                f"{rc}/{len(times)} готово" if rc else f"{len(times)} участков",
                pending_at_ms=pnd, last_ready_at_ms=times[-1], ready_times=times,
                resource_key="crops"))

    # ── TREES ─────────────────────────────────────────────────────────────────
    if track.get("trees", True):
        tt = []
        for tid, tree in farm.get("trees", {}).items():
            if not isinstance(tree, dict):
                continue
            ch = _fix_ts(_d(tree.get("wood")).get("choppedAt", 0))
            if ch:
                tt.append(ch + TREE_RESPAWN_MS)
        if tt:
            tt.sort(); rc = sum(1 for t in tt if t <= now_ms)
            pnd = tt[rc] if rc < len(tt) else tt[-1]
            events.append(Event("Trees", "🪵", tt[0], len(tt), rc,
                f"{rc}/{len(tt)} готово" if rc else f"{len(tt)} деревьев",
                pending_at_ms=pnd, last_ready_at_ms=tt[-1], ready_times=tt,
                resource_key="trees"))

    # ── STONES / IRON / GOLD / CRIMSTONES ─────────────────────────────────────
    for key, label, emoji, respawn in [
        ("stones",     "Stones",     "🪨", STONE_RESPAWN_MS),
        ("iron",       "Iron",       "⛏️", IRON_RESPAWN_MS),
        ("gold",       "Gold",       "🥇", GOLD_RESPAWN_MS),
        ("crimstones", "Crimstones", "💎", CRIM_RESPAWN_MS),
    ]:
        if track.get(key, False):
            st = []
            for sid, s in farm.get(key, {}).items():
                if not isinstance(s, dict):
                    continue
                m = _fix_ts(_d(s.get("stone")).get("minedAt", 0))
                if m:
                    st.append(m + respawn)
            if st:
                st.sort(); rc = sum(1 for t in st if t <= now_ms)
                pnd = st[rc] if rc < len(st) else st[-1]
                events.append(Event(label, emoji, st[0], len(st), rc,
                    f"{rc}/{len(st)} готово" if rc else f"{len(st)} шт.",
                    pending_at_ms=pnd, last_ready_at_ms=st[-1], ready_times=st,
                    resource_key=key))

    # ── OIL ───────────────────────────────────────────────────────────────────
    if track.get("oil", False):
        ot = []
        for oid, s in farm.get("oilReserves", {}).items():
            if not isinstance(s, dict):
                continue
            d = _fix_ts(_d(s.get("oil")).get("drilledAt", 0))
            if d:
                ot.append(d + OIL_RESPAWN_MS)
        if ot:
            ot.sort(); rc = sum(1 for t in ot if t <= now_ms)
            pnd = ot[rc] if rc < len(ot) else ot[-1]
            events.append(Event("Oil", "🛢️", ot[0], len(ot), rc,
                f"{rc}/{len(ot)} готово" if rc else f"{len(ot)} скважин",
                pending_at_ms=pnd, last_ready_at_ms=ot[-1],
                resource_key="oil"))

    # ── SALT ──────────────────────────────────────────────────────────────────
    if track.get("salt", True):
        salt_raw = farm.get("saltFarm", {})
        nodes = salt_raw.get("nodes", {}) if isinstance(salt_raw, dict) else {}
        sa_ready = []; sa_stored = 0
        for nid, node in nodes.items():
            sd = node.get("salt", {}) if isinstance(node, dict) else {}
            stored  = sd.get("storedCharges", 0)
            next_at = _fix_ts(sd.get("nextChargeAt", 0))
            if stored > 0:
                sa_stored += stored
            elif next_at:
                sa_ready.append(next_at)
        total = len(nodes)
        if total:
            rc = sa_stored + sum(1 for t in sa_ready if t <= now_ms)
            earliest = min(sa_ready) if sa_ready else now_ms
            events.append(Event("Salt", "🧂", earliest, total, rc,
                f"{rc}/{total} готово" if rc else f"{total} узл.",
                resource_key="salt"))

    # ── SUNSTONES ─────────────────────────────────────────────────────────────
    if track.get("sunstones", False):
        ss = []
        for ssid, s in farm.get("sunstones", {}).items():
            if not isinstance(s, dict):
                continue
            m = _fix_ts(_d(s.get("stone")).get("minedAt", 0))
            if m:
                ss.append(m + SUNSTONE_RESPAWN_MS)
        if ss:
            ss.sort(); rc = sum(1 for t in ss if t <= now_ms)
            pnd = ss[rc] if rc < len(ss) else ss[-1]
            events.append(Event("Sunstones", "🌟", ss[0], len(ss), rc,
                f"{rc}/{len(ss)} готово" if rc else f"{len(ss)} жил",
                pending_at_ms=pnd, last_ready_at_ms=ss[-1],
                resource_key="sunstones"))

    # ── FRUITS ────────────────────────────────────────────────────────────────
    if track.get("fruits", True):
        fruit_map: dict[str, list] = {}
        for pid, patch in farm.get("fruitPatches", {}).items():
            if not isinstance(patch, dict):
                continue
            fr = patch.get("fruit")
            if not fr or fr.get("harvestsLeft", 0) == 0:
                continue
            name = fr.get("name", "Фрукт")
            # harvestedAt — это сдвинутый plantedAt после сбора (как в цветах).
            # До первого сбора используем plantedAt.
            # readyAt = (harvestedAt или plantedAt) + BASE_REGROW_MS
            hv = _fix_ts(fr.get("harvestedAt") or fr.get("plantedAt", 0))
            if not hv:
                continue
            regrow = FRUIT_REGROW_MS.get(name, 12*3_600_000)
            fruit_map.setdefault(name, []).append(hv + regrow)
        for name, times in fruit_map.items():
            times.sort(); rc = sum(1 for t in times if t <= now_ms)
            pnd = times[rc] if rc < len(times) else times[-1]
            events.append(Event(name, "🍎", times[0], len(times), rc,
                f"{rc}/{len(times)} готово" if rc else f"{len(times)} деревьев",
                pending_at_ms=pnd, last_ready_at_ms=times[-1],
                resource_key="fruits"))

    # ── FLOWERS ───────────────────────────────────────────────────────────────
    if track.get("flowers", True):
        flower_map: dict[str, list] = {}
        for bid, bed in _d(farm.get("flowers")).get("flowerBeds", {}).items():
            if not isinstance(bed, dict):
                continue
            fl = bed.get("flower")
            if not fl:
                continue
            name = fl.get("name", "Цветок")
            rdy = _fix_ts(fl.get("readyAt", 0))
            if rdy:
                flower_map.setdefault(name, []).append(rdy)
                continue
            planted = _fix_ts(fl.get("plantedAt", 0))
            if not planted:
                continue
            # Бусты уже закодированы в plantedAt игрой (сдвиг назад).
            # readyAt = plantedAt + BASE_SEED_TIME_MS — никаких множителей не нужно.
            grow = FLOWER_GROW_MS.get(name, _FLOWER_GROW_MS_DEFAULT)
            flower_map.setdefault(name, []).append(planted + grow)
        for name, times in flower_map.items():
            times.sort(); rc = sum(1 for t in times if t <= now_ms)
            pnd = times[rc] if rc < len(times) else times[-1]
            events.append(Event(name, "🌸", times[0], len(times), rc,
                f"{rc}/{len(times)} готово" if rc else f"{len(times)} грядок",
                pending_at_ms=pnd, last_ready_at_ms=times[-1],
                resource_key="flowers"))

    # ── HONEY ─────────────────────────────────────────────────────────────────
    # Скорость производства мёда:
    #   Поле flowers[active]["rate"] уже содержит итоговую скорость с учётом
    #   всех бонусов (Hyper Bees, бафы и т.д.) — игра вычисляет её при
    #   прикреплении цветка. Добавлять бонусы вручную не нужно.
    # Поле honey["produced"] — накопленное время производства в мс (при rate=1.0).
    # Доля заполнения = produced / HONEY_FULL_MS.
    HONEY_FULL_MS  = 24 * 3_600_000

    if track.get("honey", True):
        ht = []; hive_swarm = 0
        for hid, hive in farm.get("beehives", {}).items():
            if not isinstance(hive, dict):
                continue
            if hive.get("swarm"):
                hive_swarm += 1

            # Производство мёда идёт только пока цветок ещё растёт
            active_flower = next(
                (fl for fl in _l(hive.get("flowers"))
                 if isinstance(fl, dict) and _fix_ts(fl.get("attachedUntil", 0)) > now_ms),
                None
            )
            if not active_flower:
                continue

            honey_data = _d(hive.get("honey"))
            produced_ms = honey_data.get("produced", honey_data.get("amount", 0))
            h_amount    = produced_ms / HONEY_FULL_MS
            h_updated   = _fix_ts(honey_data.get("updatedAt", 0))
            if not h_updated:
                continue

            # Приоритет 1: honey["speed"] — если игра сохраняет итоговую скорость
            # Приоритет 2: flowers[active]["rate"] — уже включает все бонусы
            stored_speed = honey_data.get("speed")
            if stored_speed and stored_speed > 0:
                honey_rate = float(stored_speed)
            else:
                honey_rate = float(active_flower.get("rate", 1.0))

            honey_ms_per_unit = HONEY_FULL_MS / honey_rate

            # Текущее кол-во мёда = снэпшот + выработка с момента снэпшота
            current_amount = h_amount + (now_ms - h_updated) / honey_ms_per_unit
            if current_amount < 1.0:
                ready_at = int(now_ms + (1.0 - current_amount) * honey_ms_per_unit)
                ht.append(ready_at)

        bee_swarm = len(_d(farm.get("collectibles")).get("Bee Swarm", []))
        swarm_total = hive_swarm + bee_swarm
        if ht:
            ht.sort(); rc = sum(1 for t in ht if t <= now_ms)
            pnd = ht[rc] if rc < len(ht) else ht[-1]
            extra = f"🐝 Bee Swarm x{swarm_total}" if swarm_total else ""
            events.append(Event("Honey", "🍯", ht[0], len(ht), rc,
                extra, pending_at_ms=pnd, last_ready_at_ms=ht[-1],
                resource_key="honey"))

    # ── MUSHROOMS ─────────────────────────────────────────────────────────────
    if track.get("mushrooms", False):
        mush = _d(farm.get("mushrooms"))
        sa = _fix_ts(mush.get("spawnedAt", 0))
        if sa:
            events.append(Event("Mushrooms", "🍄", sa + MUSH_SPAWN_MS, 1,
                extra="новая партия", resource_key="mushrooms"))

    # ── ANIMALS ───────────────────────────────────────────────────────────────
    if track.get("animals", False):
        ag: dict[str, list] = {}
        for src in ("henHouse", "barn"):
            for aid, animal in _d(farm.get(src)).get("animals", {}).items():
                if not isinstance(animal, dict):
                    continue
                atype    = animal.get("type", "Animal")
                state_a  = animal.get("state", "")
                awake_at = _fix_ts(animal.get("awakeAt", 0))
                if state_a == "sleeping" and awake_at:
                    ag.setdefault(atype, []).append(awake_at)
                elif state_a in ("idle", "ready", ""):
                    ag.setdefault(atype, []).append(0)
        for atype, times in ag.items():
            times.sort()
            rc = sum(1 for t in times if t == 0 or t <= now_ms)
            first = min(t for t in times if t > 0) if any(t > 0 for t in times) else now_ms
            emoji = "🐄" if "Cow" in atype else "🐔"
            last_at = max((t for t in times if t > 0), default=now_ms)
            events.append(Event(atype, emoji, first, len(times), rc,
                f"{rc}/{len(times)} проснулось" if rc else f"{len(times)} животных",
                last_ready_at_ms=last_at, resource_key="animals"))

    # ── ДИНАМИЧЕСКИЕ РЕСУРСЫ (автодетект) ────────────────────────────────────
    for dr in (dynamic_resources or []):
        key = dr["key"]
        if not track.get(key, False):
            continue
        ev = scan_dynamic_resource(farm, key, dr["timer_field"],
                                    dr["label"], dr["emoji"])
        if ev:
            events.append(ev)

    events.sort(key=lambda e: e.ready_at_ms)
    return events

# ══════════════════════════════════════════════════════════════════════════════
# ФОРМАТИРОВАНИЕ СООБЩЕНИЙ
# ══════════════════════════════════════════════════════════════════════════════

_I18N = {
    "now": {
        "ru": "сейчас", "en": "now", "uk": "зараз",
    },
    "in_dhms": {
        "ru": "через {d}д {h:02d}:{m:02d}:{s:02d}",
        "en": "in {d}d {h:02d}:{m:02d}:{s:02d}",
        "uk": "через {d}д {h:02d}:{m:02d}:{s:02d}",
    },
    "in_hms": {
        "ru": "через {h}ч {m:02d}м {s:02d}с",
        "en": "in {h}h {m:02d}m {s:02d}s",
        "uk": "через {h}г {m:02d}хв {s:02d}с",
    },
    "in_ms": {
        "ru": "через {m}м {s:02d}с",
        "en": "in {m}m {s:02d}s",
        "uk": "через {m}хв {s:02d}с",
    },
    "in_s": {
        "ru": "через {s}с",
        "en": "in {s}s",
        "uk": "через {s}с",
    },
    "no_resources": {
        "ru": "🌻 Ферма <b>{farm_id}</b>\n\nНет отслеживаемых ресурсов.",
        "en": "🌻 Farm <b>{farm_id}</b>\n\nNo tracked resources.",
        "uk": "🌻 Ферма <b>{farm_id}</b>\n\nНемає відстежуваних ресурсів.",
    },
    "farm_header": {
        "ru": "🌻 <b>Ферма {farm_id}</b>",
        "en": "🌻 <b>Farm {farm_id}</b>",
        "uk": "🌻 <b>Ферма {farm_id}</b>",
    },
    "all_ready": {
        "ru": "\n✅ <b>Всё готово к сбору!</b>",
        "en": "\n✅ <b>Everything is ready to harvest!</b>",
        "uk": "\n✅ <b>Все готово до збору!</b>",
    },
    "ready_section": {
        "ru": "\n✅ <b>Готово к сбору:</b>",
        "en": "\n✅ <b>Ready to harvest:</b>",
        "uk": "\n✅ <b>Готово до збору:</b>",
    },
    "updated_at": {
        "ru": "\n<i>Обновлено: {ts}</i>",
        "en": "\n<i>Updated: {ts}</i>",
        "uk": "\n<i>Оновлено: {ts}</i>",
    },
    "ready_alert": {
        "ru": "{emoji} <b>{name}{cnt}{extra} — готово к сбору ✅</b>",
        "en": "{emoji} <b>{name}{cnt}{extra} — ready to harvest ✅</b>",
        "uk": "{emoji} <b>{name}{cnt}{extra} — готово до збору ✅</b>",
    },
}


def _i18n(key: str, lang: str, **kwargs) -> str:
    lang = lang if lang in ("ru", "en", "uk") else "ru"
    tmpl = _I18N.get(key, {}).get(lang) or _I18N.get(key, {}).get("ru", f"[{key}]")
    return tmpl.format(**kwargs) if kwargs else tmpl


def _fmt_ms_human(ms: int, lang: str = "ru") -> str:
    if ms <= 0:
        return _i18n("now", lang)
    s = int(ms) // 1000; h, rem = divmod(s, 3600); m, sc = divmod(rem, 60)
    if h >= 24:
        d = h // 24; h = h % 24
        return _i18n("in_dhms", lang, d=d, h=h, m=m, s=sc)
    if h > 0:
        return _i18n("in_hms", lang, h=h, m=m, s=sc)
    if m > 0:
        return _i18n("in_ms", lang, m=m, s=sc)
    return _i18n("in_s", lang, s=sc)


def _split_into_groups(ready_times: list, now_ms: int,
                       window_ms: int = 300_000) -> list[tuple[int, int]]:
    """
    Разбивает pending ready_times на "волны" по близости времени.
    Возвращает список (count, ready_at_ms) отсортированный по времени.
    Таймы в пределах window_ms от первого в группе → одна волна.
    """
    pending = sorted(t for t in ready_times if t > now_ms)
    if not pending:
        return []
    groups: list[tuple[int, int]] = []
    group_anchor = pending[0]
    group_count  = 1
    for t in pending[1:]:
        if t - group_anchor <= window_ms:
            group_count += 1
        else:
            groups.append((group_count, group_anchor))
            group_anchor = t
            group_count  = 1
    groups.append((group_count, group_anchor))
    return groups


def split_ready_into_waves(ready_times: list, window_ms: int = 60_000) -> list[tuple[int, int]]:
    """
    Разбивает уже готовые ready_times на волны по близости времени.
    Возвращает список (count, anchor_ms) где anchor — первый таймстамп волны.
    """
    times = sorted(ready_times)
    if not times:
        return []
    groups: list[tuple[int, int]] = []
    anchor = times[0]
    count = 1
    for t in times[1:]:
        if t - anchor <= window_ms:
            count += 1
        else:
            groups.append((count, anchor))
            anchor = t
            count = 1
    groups.append((count, anchor))
    return groups


def format_status_message(events: list[Event], farm_id: str,
                           tz=None, lang: str = "ru") -> str:
    """Статус-сообщение — закреп (редактируется, не уведомляет)."""
    _tz = tz or UA_TZ
    if not events:
        return _i18n("no_resources", lang, farm_id=farm_id)

    pending = [e for e in events if e.ready_count < e.count]
    lines = [_i18n("farm_header", lang, farm_id=farm_id)]

    if not pending:
        lines.append(_i18n("all_ready", lang))
    else:
        lines.append("")
        now_ms = int(time.time() * 1000)

        # Собираем отображаемые строки: каждая волна — отдельный элемент (ms, line)
        display_items: list[tuple[int, str]] = []

        for e in pending:
            swarm_extra = ""
            if e.name == "Honey" and e.extra:
                import re as _re
                m = _re.search(r"Swarm x(\d+)", e.extra)
                swarm_extra = f" (Swarm x{m.group(1)})" if m else ""

            # Если есть ready_times — делим на волны по времени готовности
            if e.ready_times and e.count > 1:
                groups = _split_into_groups(e.ready_times, now_ms)
                if len(groups) > 1:
                    for cnt, ready_ms in groups:
                        ms_left = max(0, ready_ms - now_ms)
                        clock   = datetime.fromtimestamp(ready_ms / 1000, tz=_tz).strftime("%H:%M")
                        cnt_label = f" [{cnt}]"
                        display_items.append((ready_ms,
                            f"{e.emoji} <b>{e.name}{cnt_label}{swarm_extra}</b>"
                            f" — {_fmt_ms_human(ms_left, lang)} — {clock}"))
                    continue

            # Одна волна или нет ready_times — стандартная строка
            cnt_label = f" [{e.count - e.ready_count}]" if e.count > 1 else ""
            ms_left   = max(0, e.pending_at_ms - now_ms)
            clock     = e.fmt_pending_ready_time(_tz)
            display_items.append((e.pending_at_ms,
                f"{e.emoji} <b>{e.name}{cnt_label}{swarm_extra}</b>"
                f" — {_fmt_ms_human(ms_left, lang)} — {clock}"))

        for _, line in sorted(display_items, key=lambda x: x[0])[:20]:
            lines.append(line)

    ready_now = [e for e in events if e.ready_count > 0]
    if ready_now:
        lines.append(_i18n("ready_section", lang))
        for e in ready_now:
            cnt = f" [{e.ready_count}/{e.count}]" if e.count > 1 else ""
            lines.append(f"  {e.emoji} {e.name}{cnt}")

    ts = datetime.now(tz=_tz).strftime("%d.%m %H:%M")
    lines.append(_i18n("updated_at", lang, ts=ts))
    return "\n".join(lines)


def format_ready_alert(e: Event, lang: str = "ru", wave_count: int | None = None) -> str:
    # wave_count передаётся явно при волновом режиме.
    # Иначе: если все оставшиеся созреют в течение 30 секунд — показываем полный счётчик.
    now_ms = int(time.time() * 1000)
    if wave_count is not None:
        effective_ready = wave_count
    else:
        all_ready_soon = (e.last_ready_at_ms - now_ms) <= 30_000
        effective_ready = e.count if all_ready_soon else e.ready_count
    cnt = f" [{effective_ready}/{e.count}]" if e.count > 1 else ""
    is_honey = e.name == "Honey"
    extra_label = f" ({e.extra})" if (e.extra and is_honey) else ""
    return _i18n("ready_alert", lang, emoji=e.emoji, name=e.name,
                 cnt=cnt, extra=extra_label)

# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM API HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def tg_send(token: str, chat_id: int, text: str,
            silent: bool = False, reply_markup: dict = None) -> int | None:
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_notification": silent,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload, timeout=20)
        if r.ok:
            return r.json()["result"]["message_id"]
        log.warning(f"tg_send failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        log.warning(f"tg_send error: {e}")
    return None

def panel_keyboard(lang: str, is_active: bool) -> dict:
    """Inline-клавиатура «живого пульта» для закреплённого статус-сообщения."""
    labels = {
        "settings": {"ru": "⚙️ Настройки",  "en": "⚙️ Settings",  "uk": "⚙️ Налаштування"},
        "stop":     {"ru": "⏸ Пауза",        "en": "⏸ Pause",      "uk": "⏸ Пауза"},
        "resume":   {"ru": "▶️ Возобновить", "en": "▶️ Resume",     "uk": "▶️ Поновити"},
        "lang":     {"ru": "🌐 Язык",         "en": "🌐 Language",   "uk": "🌐 Мова"},
    }
    L = lambda k: labels[k].get(lang) or labels[k]["en"]
    toggle = (
        {"text": L("stop"),   "callback_data": "panel:stop"}
        if is_active else
        {"text": L("resume"), "callback_data": "panel:resume"}
    )
    return {"inline_keyboard": [
        [{"text": L("settings"), "callback_data": "panel:settings"}],
        [toggle],
        [{"text": L("lang"),     "callback_data": "panel:lang"}],
    ]}


def tg_edit(token: str, chat_id: int, message_id: int, text: str,
            reply_markup: dict = None) -> bool:
    """Редактирует сообщение. Возвращает True при успехе.
    При сетевой ошибке (таймаут и т.п.) бросает исключение наверх —
    чтобы вызывающий код не путал «сообщение удалено» с «сеть недоступна»
    и не слал новое сообщение зря."""
    payload = {"chat_id": chat_id, "message_id": message_id,
               "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    r = requests.post(
        f"https://api.telegram.org/bot{token}/editMessageText",
        json=payload, timeout=20)
    return r.ok

def tg_delete(token: str, chat_id: int, message_id: int):
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/deleteMessage",
            json={"chat_id": chat_id, "message_id": message_id},
            timeout=10)
    except Exception:
        pass

def tg_pin_message(token: str, chat_id: int, message_id: int,
                   disable_notification: bool = True) -> bool:
    """Закрепляет сообщение в чате. disable_notification=True — без звука."""
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/pinChatMessage",
            json={"chat_id": chat_id, "message_id": message_id,
                  "disable_notification": disable_notification},
            timeout=15)
        return r.ok
    except Exception:
        return False


def tg_unpin_message(token: str, chat_id: int, message_id: int) -> bool:
    """Открепляет конкретное сообщение."""
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/unpinChatMessage",
            json={"chat_id": chat_id, "message_id": message_id},
            timeout=15)
        return r.ok
    except Exception:
        return False


def tg_upsert_status(token: str, chat_id: int, text: str,
                     message_id: int | None,
                     reply_markup: dict = None) -> tuple[int, bool]:
    """Создаёт или редактирует статус-сообщение.
    Возвращает (message_id, is_new) — is_new=True если создано новое сообщение.

    tg_edit бросает исключение при сетевых ошибках (таймаут и т.п.) —
    в этом случае мы НЕ шлём новое сообщение, чтобы не плодить дубли закрепа.
    Новое сообщение создаётся только при HTTP-ошибке (message deleted/not found).
    """
    if message_id:
        try:
            if tg_edit(token, chat_id, message_id, text, reply_markup=reply_markup):
                return message_id, False
        except Exception as e:
            log.warning(f"tg_edit network error (skip send): {e}")
            return message_id, False  # сеть упала — старый mid оставляем, не трогаем закреп
    mid = tg_send(token, chat_id, text, silent=True, reply_markup=reply_markup)
    return (mid or message_id or 0), True
