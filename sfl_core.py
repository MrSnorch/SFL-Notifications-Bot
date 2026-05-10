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

# Кулдауны скиллов-способностей (power: true) из bumpkinSkills.ts
# Ключ — точное название скилла как в API (previousPowerUseAt)
POWER_SKILL_COOLDOWNS: dict[str, int] = {
    "Instant Growth":       1000 * 60 * 60 * 72,   # 3 дня
    "Tree Blitz":           1000 * 60 * 60 * 24,   # 1 день
    "Barnyard Rouse":       1000 * 60 * 60 * 24 * 5,  # 5 дней
    "Greenhouse Guru":      1000 * 60 * 60 * 96,   # 4 дня
    "Instant Gratification":1000 * 60 * 60 * 96,   # 4 дня
    "Petal Blessed":        1000 * 60 * 60 * 96,   # 4 дня
    "Grease Lightning":     1000 * 60 * 60 * 96,   # 4 дня
    "Salt Surge":           1000 * 60 * 60 * 72,   # 3 дня
}

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
    "balloon": True,
    "quest": True,
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
    ("balloon",    "❤️ Шарик"),
    ("quest",      "📜 Quest"),
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

    # ── СКИЛЛЫ-СПОСОБНОСТИ (power skills, кулдаун) ───────────────────────────
    if track.get("skills", True):
        bumpkin      = _d(farm.get("bumpkin"))
        active_skills = _d(bumpkin.get("skills"))
        prev_use     = _d(bumpkin.get("previousPowerUseAt"))
        for skill_name, last_used_ms in prev_use.items():
            cooldown_ms = POWER_SKILL_COOLDOWNS.get(skill_name)
            if not cooldown_ms:
                continue
            if skill_name not in active_skills:
                continue  # скилл сброшен — игнорируем
            last_used_ms = _fix_ts(last_used_ms)
            ready_at_ms = last_used_ms + cooldown_ms
            rc = 1 if ready_at_ms <= now_ms else 0
            events.append(Event(skill_name, "⚡", ready_at_ms, 1, rc,
                resource_key="skills"))

    # ── BALLOON (Floating Island / Шарик) ────────────────────────────────────
    # Шарик прилетает по расписанию (floatingIsland.schedule).
    # Пропускаем если пользователь уже решил головоломку сегодня (petalPuzzleSolvedAt).
    if track.get("balloon", True):
        fi = farm.get("floatingIsland") or {}
        if isinstance(fi, dict):
            petal_ts = fi.get("petalPuzzleSolvedAt", 0) or 0
            petal_ts = _fix_ts(petal_ts)
            solved_today = False
            if petal_ts:
                from datetime import timezone as _utc
                solved_dt = datetime.fromtimestamp(petal_ts / 1000, tz=_utc.utc).date()
                today_dt  = datetime.now(tz=_utc.utc).date()
                solved_today = (solved_dt == today_dt)

            if not solved_today:
                schedule = [s for s in fi.get("schedule", [])
                            if isinstance(s, dict)
                            and isinstance(s.get("startAt"), (int, float))
                            and isinstance(s.get("endAt"),   (int, float))]
                # Берём только окна которые ещё не закончились
                future = [(int(s["startAt"]), int(s["endAt"]))
                          for s in schedule if s["endAt"] > now_ms]
                if future:
                    next_start, next_end = min(future, key=lambda x: x[0])
                    is_here = next_start <= now_ms
                    rc = 1 if is_here else 0
                    events.append(Event("Шарик", "❤️", next_start, 1, rc,
                        extra="",
                        last_ready_at_ms=next_end,
                        resource_key="balloon"))

    # ── QUEST (Pumpkin Pete Telegram quest) ──────────────────────────────────
    # startAt — время когда Quest станет доступен (может быть в будущем).
    # choices: [] — Quest ещё не отвечен.
    if track.get("quest", True):
        tg_data = farm.get("telegram") or {}
        quest   = tg_data.get("quest") or {}
        q_start = _fix_ts(quest.get("startAt", 0))
        q_name  = quest.get("name", "")
        q_choices = quest.get("choices", [])
        if q_start and q_name and not q_choices:
            rc = 1 if q_start <= now_ms else 0
            events.append(Event("Quest", "📜", q_start, 1, rc,
                extra=q_name,
                resource_key="quest"))

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
    "ready_skills_section": {
        "ru": "\n✅ <b>Готово к использованию:</b>",
        "en": "\n✅ <b>Ready to use:</b>",
        "uk": "\n✅ <b>Готово до використання:</b>",
    },
    "skill_ready_alert": {
        "ru": "{emoji} <b>{name} — готово к использованию ✅</b>",
        "en": "{emoji} <b>{name} — ready to use ✅</b>",
        "uk": "{emoji} <b>{name} — готово до використання ✅</b>",
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
    "balloon_arrived": {
        "ru": "❤️ <b>Шарик прилетел!</b>{until}",
        "en": "❤️ <b>Balloon arrived!</b>{until}",
        "uk": "❤️ <b>Шарик прилетів!</b>{until}",
    },
    "balloon_until": {
        "ru": " Улетает в {clock} (через {mins} мин)",
        "en": " Leaves at {clock} (in {mins} min)",
        "uk": " Відлітає о {clock} (через {mins} хв)",
    },
    "quest_arrived": {
        "ru": "📜 <b>Новый Quest доступен!</b>",
        "en": "📜 <b>New quest available!</b>",
        "uk": "📜 <b>Новий Quest доступний!</b>",
    },
    "daily_reward_ready": {
        "ru": "🎁 <b>Daily Reward [{streaks}] — готово к получению ✅</b>",
        "en": "🎁 <b>Daily Reward [{streaks}] — ready to collect ✅</b>",
        "uk": "🎁 <b>Daily Reward [{streaks}] — готово до отримання ✅</b>",
    },
    "daily_reward_reminder": {
        "ru": "🎁 <b>Daily Reward [{streaks}] — не забудь забрать! осталось {hours}ч ⚠️</b>",
        "en": "🎁 <b>Daily Reward [{streaks}] — don't forget to collect! {hours}h left ⚠️</b>",
        "uk": "🎁 <b>Daily Reward [{streaks}] — не забудь забрати! залишилось {hours}год ⚠️</b>",
    },
    "daily_status_collected": {
        "ru": "🎁 Daily Reward [{streaks}] — ✅",
        "en": "🎁 Daily Reward [{streaks}] — ✅",
        "uk": "🎁 Daily Reward [{streaks}] — ✅",
    },
    "daily_status_pending": {
        "ru": "🎁 <b>Daily Reward [{streaks}] — забери!</b>",
        "en": "🎁 <b>Daily Reward [{streaks}] — collect it!</b>",
        "uk": "🎁 <b>Daily Reward [{streaks}] — забери!</b>",
    },
    "daily_status_available": {
        "ru": "🎁 <b>Daily Reward [{streaks}] доступен к получению!</b>",
        "en": "🎁 <b>Daily Reward [{streaks}] available to collect!</b>",
        "uk": "🎁 <b>Daily Reward [{streaks}] доступний до отримання!</b>",
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
                           tz=None, lang: str = "ru",
                           time_format: str = "both",
                           daily_info: dict | None = None) -> str:
    # time_format: "both" = countdown + clock, "countdown" = countdown only, "clock" = clock only
    """Статус-сообщение — закреп (редактируется, не уведомляет)."""
    _tz = tz or UA_TZ
    if not events:
        return _i18n("no_resources", lang, farm_id=farm_id)

    pending = [e for e in events if e.ready_count < e.count]
    lines = [_i18n("farm_header", lang, farm_id=farm_id)]

    now_ms = int(time.time() * 1000)
    # Собираем отображаемые строки: каждая волна — отдельный элемент (ms, line)
    display_items: list[tuple[int, str]] = []

    if daily_info is not None:
        _streaks = daily_info.get("streaks", 0)
        if daily_info.get("collected_today"):
            # Награда уже собрана — показываем обратный отсчёт до следующего сброса
            _next_reset_ms = daily_info.get("next_reset_ms", 0)
            if _next_reset_ms:
                ms_left = max(0, _next_reset_ms - now_ms)
                if time_format == "clock":
                    time_str = datetime.fromtimestamp(_next_reset_ms / 1000, tz=_tz).strftime("%H:%M")
                elif time_format == "countdown":
                    time_str = _fmt_ms_human(ms_left, lang)
                else:  # both
                    clock = datetime.fromtimestamp(_next_reset_ms / 1000, tz=_tz).strftime("%H:%M")
                    time_str = f"{_fmt_ms_human(ms_left, lang)} — {clock}"
                display_items.append((_next_reset_ms,
                    f"🎁 <b>Daily Reward [{_streaks}]</b> — {time_str}"))
        else:
            # Награда доступна к получению
            lines.append(_i18n("daily_status_available", lang, streaks=_streaks))

    if not pending and not display_items:
        lines.append(_i18n("all_ready", lang))
    else:
        lines.append("")

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
                        if time_format == "clock":
                            time_str = clock
                        elif time_format == "countdown":
                            time_str = _fmt_ms_human(ms_left, lang)
                        else:  # both
                            time_str = f"{_fmt_ms_human(ms_left, lang)} — {clock}"
                        display_items.append((ready_ms,
                            f"{e.emoji} <b>{e.name}{cnt_label}{swarm_extra}</b>"
                            f" — {time_str}"))
                    continue

            # Одна волна или нет ready_times — стандартная строка
            cnt_label = f" [{e.count - e.ready_count}]" if e.count > 1 else ""
            ms_left   = max(0, e.pending_at_ms - now_ms)
            clock     = e.fmt_pending_ready_time(_tz)
            if time_format == "clock":
                time_str = clock
            elif time_format == "countdown":
                time_str = _fmt_ms_human(ms_left, lang)
            else:  # both
                time_str = f"{_fmt_ms_human(ms_left, lang)} — {clock}"
            display_items.append((e.pending_at_ms,
                f"{e.emoji} <b>{e.name}{cnt_label}{swarm_extra}</b>"
                f" — {time_str}"))

        for _, line in sorted(display_items, key=lambda x: x[0])[:20]:
            lines.append(line)

    ready_resources = [e for e in events if e.ready_count > 0 and e.resource_key != "skills"]
    ready_skills    = [e for e in events if e.ready_count > 0 and e.resource_key == "skills"]
    if ready_resources:
        lines.append(_i18n("ready_section", lang))
        for e in ready_resources:
            cnt = f" [{e.ready_count}/{e.count}]" if e.count > 1 else ""
            if e.resource_key == "balloon" and e.last_ready_at_ms:
                end_clock = datetime.fromtimestamp(
                    e.last_ready_at_ms / 1000, tz=_tz).strftime("%H:%M")
                lines.append(f"  {e.emoji} {e.name}{cnt} (до {end_clock})")
            else:
                lines.append(f"  {e.emoji} {e.name}{cnt}")
    if ready_skills:
        lines.append(_i18n("ready_skills_section", lang))
        for e in ready_skills:
            lines.append(f"  {e.emoji} {e.name}")

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
    if getattr(e, "resource_key", "") == "skills":
        return _i18n("skill_ready_alert", lang, emoji=e.emoji, name=e.name)
    if getattr(e, "resource_key", "") == "balloon":
        until = ""
        if e.last_ready_at_ms and e.last_ready_at_ms > now_ms:
            mins_left = max(1, int((e.last_ready_at_ms - now_ms) / 60_000))
            clock = datetime.fromtimestamp(e.last_ready_at_ms / 1000, tz=UA_TZ).strftime("%H:%M")
            until = _i18n("balloon_until", lang, clock=clock, mins=mins_left)
        return _i18n("balloon_arrived", lang, until=until)
    if getattr(e, "resource_key", "") == "quest":
        return _i18n("quest_arrived", lang)
    is_honey = e.name == "Honey"
    extra_label = f" ({e.extra})" if (e.extra and is_honey) else ""
    return _i18n("ready_alert", lang, emoji=e.emoji, name=e.name,
                 cnt=cnt, extra=extra_label)

# ══════════════════════════════════════════════════════════════════════════════
# ДАННЫЕ QuestОВ (Pumpkin Pete Telegram quests)
# Ключ — quest["name"] из API. Добавляй новые Questы сюда по мере появления.
# ══════════════════════════════════════════════════════════════════════════════

QUEST_DATA: dict[str, dict] = {
    "ancient-totem": {
        "title": "Ancient Totem",
        "description": "While digging, you unearth a strange humming totem covered in runes. What will you do?",
        "choices": [
            ("✋ Touch it",      "100 Coins 🪙"),
            ("🙈 Bury it again", "5 Stone 🪨"),
        ],
    },
    "bards-visit": {
        "title": "Bard's Visit",
        "description": "A traveling bard plays a lively tune and asks for a small gift to bless your harvest. How will you respond?",
        "choices": [
            ("🎵 Give him mushrooms", "5 Wild Mushrooms 🍄 + 50 Coins 🪙"),
            ("🤐 Ignore him",         "50 Coins 🪙"),
        ],
    },
    "beach-banter": {
        "title": "Beach Banter",
        "description": "Petro and Corale are arguing over a washed-up relic. Help settle the dispute?",
        "choices": [
            ("🗺️ Decode the vase's map", "5 Kale Seed 🥬"),
            ("🌊 Let the waves claim it", "50 Coins 🪙"),
            ("🚶 Ignore it",              "3 White Pansy 🤍"),
        ],
    },
    "berts-portal": {
        "title": "Bert's Portal",
        "description": "Bert says a mushroom ring is a portal to another land. Try jumping in?",
        "choices": [
            ("🧙‍♂️ Step into the ring", "1 Gold 🥇"),
            ("🧿 Back away slowly",    "50 Coins 🪙"),
            ("🚶 Ignore it",           "3 Red Pansy 🌺"),
        ],
    },
    "chase-the-rainbow": {
        "title": "Chase the Rainbow",
        "description": "A dazzling rainbow arcs across Sunflower Land. It's said treasures lie at its base. Will you chase it?",
        "choices": [
            ("🏃 Chase it!",      "10 Gems 💎"),
            ("🧑‍🌾 Ignore it", "50 Coins 🪙"),
        ],
    },
    "chicken-race": {
        "title": "Chicken Race",
        "description": "A cheeky chicken challenges you to a race around the farm. Villagers are watching!",
        "choices": [
            ("🏃‍♂️ Race the chicken", "5 Axes 🪓 + 50 Coins 🪙"),
            ("🐥 Let it strut",        "5 Kale 🥬"),
        ],
    },
    "cornwells-curiosity": {
        "title": "Cornwell's Curiosity",
        "description": "What is Cornwell's profession in Sunflower Land?",
        "choices": [
            ("📖 Librarian ✅",  "100 Coins 🪙 + 5 Gems 💎"),
            ("⚒️ Blacksmith ❌", "No prize"),
            ("🧙 Wizard ❌",     "No prize"),
        ],
    },
    "cornwells-riddle": {
        "title": "Cornwell's Riddle",
        "description": "Cornwell challenges you with a cryptic riddle tied to a hidden stash. Try to solve it?",
        "choices": [
            ("👨‍🌾 Investigate the answer", "10 Kale 🥬"),
            ("📘 Close the riddle book",    "50 Coins 🪙"),
            ("🚶 Ignore it",                "150 Coins 🪙"),
        ],
    },
    "desert-rune": {
        "title": "Desert Rune",
        "description": "A glowing rune was found in the desert. Touch it or report it?",
        "choices": [
            ("🔥 Touch the glowing rune",  "10 Corn 🌽"),
            ("🧘 Leave it undisturbed",    "50 Coins 🪙"),
            ("🚶 Ignore it",               "50 Coins 🪙"),
        ],
    },
    "finleys-fish": {
        "title": "Finley's Fish",
        "description": "Finley saw a huge shadow in the ocean. Try to catch it?",
        "choices": [
            ("🎣 Cast Finley's rod",     "5 Stone 🪨"),
            ("🐚 Sit by the shore",      "50 Coins 🪙"),
            ("🚶 Ignore it",             "3 Purple Pansy 🟣"),
        ],
    },
    "fox-theft": {
        "title": "Fox Theft",
        "description": "A fox is spotted stealing berries from your farm. Quick thinking might save your harvest!",
        "choices": [
            ("🦊 Shoo it away", "5 Mushrooms 🍄"),
            ("🥬 Let it go",    "5 Kale 🥬"),
        ],
    },
    "gambits-bet": {
        "title": "Gambit's Bet",
        "description": "Gambit offers a risky game with high rewards. Do you play?",
        "choices": [
            ("🕵️ Start the scavenger hunt", "5 Wheat Seed 🌾"),
            ("🎭 Decline the risky bet",     "50 Coins 🪙"),
            ("🚶 Ignore it",                 "50 Coins 🪙"),
        ],
    },
    "ghostly-harvest": {
        "title": "Ghostly Harvest",
        "description": "Strange crops have sprouted overnight, glowing under the moonlight. Investigate?",
        "choices": [
            ("🧩 Decode the crop symbol",   "10 Pumpkin 🎃"),
            ("🌑 Step away from the glow",  "50 Coins 🪙"),
            ("🚶 Ignore it",                "5 Iron ⛓️"),
        ],
    },
    "goblin-dance-party": {
        "title": "Goblin Dance Party",
        "description": "The Goblins have set up a wild dance party in the fields. Strange music fills the air. Join them?",
        "choices": [
            ("💃 Join them",   "15 Love Charms 💝"),
            ("🕺 Stay away",   "5 Stone 🪨"),
        ],
    },
    "goblin-scheme": {
        "title": "Goblin Scheme",
        "description": "A shady goblin whispers about a shortcut to wealth. Trust him?",
        "choices": [
            ("💰 Enter the mountain lair",  "5 Corn Seed 🌽"),
            ("🚫 Ignore the goblin's tip",  "50 Coins 🪙"),
            ("🚶 Ignore it",                "5 Wood 🪵"),
        ],
    },
    "goblin-trade": {
        "title": "Goblin Trade",
        "description": "A sneaky Goblin jingles a bag of shiny stones, offering a suspicious trade for your crops. Will you trust him?",
        "choices": [
            ("🤝 Accept trade", "5 Pickaxe ⛏️"),
            ("🚶 Refuse",       "50 Coins 🪙"),
        ],
    },
    "goblin-upgrade": {
        "title": "Goblin Upgrade",
        "description": "A shady Goblin offers to \"upgrade\" your tools. His grin is unsettling. Trust him?",
        "choices": [
            ("🛠️ Agree",  "5 Rods 🎣 + 5 Pickaxes ⛏️"),
            ("❌ Decline", "50 Coins 🪙"),
        ],
    },
    "golden-fish": {
        "title": "Golden Fish",
        "description": "A Golden Fish is flopping by the river. Legends say catching it brings great fortune. Will you take the risk?",
        "choices": [
            ("🐠 Catch it!", "15 Gems 💎"),
            ("🦈 Let it go", "50 Coins 🪙"),
        ],
    },
    "grimblys-feast": {
        "title": "Grimbly's Feast",
        "description": "Grimbly is preparing a Goblin feast but needs one last ingredient. Help him?",
        "choices": [
            ("🍄 Search behind the falls", "7 Gems 💎"),
            ("🥣 Refuse the recipe",       "50 Coins 🪙"),
            ("🚶 Ignore it",               "100 Coins 🪙"),
        ],
    },
    "help-old-cornwell": {
        "title": "Help Old Cornwell",
        "description": "Wise Old Cornwell waves you over, arms full of freshly picked Kale. He looks exhausted and could use a hand. Will you help?",
        "choices": [
            ("🧑‍🌾 Help him", "5 Kale 🥬 + 10 Love Charms 💘"),
            ("🙈 Ignore him",  "50 Coins 🪙"),
        ],
    },
    "jesters-prank": {
        "title": "Jester's Prank",
        "description": "The Jester plans to swap Victoria's crown with a fake during the royal procession. He offers you a reward if you help. Will you participate?",
        "choices": [
            ("👑 Swap the crown!", "10 Pumpkin 🎃"),
            ("⚖️ Warn the queen",  "50 Coins 🪙"),
            ("🚶 Ignore it",       "1 Gold 🥇"),
        ],
    },
    "lost-pirate-map": {
        "title": "Lost Pirate Map",
        "description": "You stumble upon a torn pirate map buried in the sand. Will you follow it?",
        "choices": [
            ("🗺️ Follow it", "10 Gems 💎"),
            ("🚶 Ignore it", "50 Coins 🪙"),
        ],
    },
    "lost-scroll": {
        "title": "Lost Scroll",
        "description": "Cornwell misplaced a scroll that could reveal ancient truths. Help find it?",
        "choices": [
            ("🛠️ Enter the hidden room", "1 Celestine Seed 🌱"),
            ("📚 Leave the library",      "50 Coins 🪙"),
            ("🚶 Ignore it",              "3 Red Pansy 🌺"),
        ],
    },
    "magic-storm": {
        "title": "Magic Storm",
        "description": "A vibrant magic storm rolls across Sunflower Land. Will you brave it?",
        "choices": [
            ("🌫️ Dance in the storm", "10 Axes 🪓"),
            ("🏠 Hide inside",         "5 Wood 🪵"),
        ],
    },
    "merchants-mystery-box": {
        "title": "Merchant's Mystery Box",
        "description": "A wandering merchant offers you a sealed mystery box. He promises great rewards inside. Will you buy it?",
        "choices": [
            ("🎁 Buy the box", "5 Axes 🪓"),
            ("🚫 Decline",     "50 Coins 🪙"),
            ("🚶 Ignore it",   "5 Wood 🪵"),
        ],
    },
    "mirandas-song": {
        "title": "Miranda's Song",
        "description": "Miranda found a seashell that sings. Listen to it?",
        "choices": [
            ("🎵 Follow the music trail", "5 Carrot Seed 🥕"),
            ("🙉 Ignore the melody",      "50 Coins 🪙"),
            ("🚶 Ignore it",              "50 Coins 🪙"),
        ],
    },
    "moonlight-crops": {
        "title": "Moonlight Crops",
        "description": "Your crops glisten under the full moon. Old tales say moon-harvests bring unusual yields. What will you do?",
        "choices": [
            ("🌾 Harvest them",      "5 Kale 🥬 + 10 Wood 🪵"),
            ("🐑 Wait till morning", "50 Coins 🪙"),
        ],
    },
    "mushroom-circle": {
        "title": "Mushroom Circle",
        "description": "Overnight, a glowing circle of mushrooms has formed near your farm. Strange energies hum in the air. Dare to step inside?",
        "choices": [
            ("🌀 Step inside",      "3 Wild Mushrooms 🍄"),
            ("🛡️ Walk around it", "5 Wood 🪵"),
        ],
    },
    "mysterious-merchant": {
        "title": "Mysterious Merchant",
        "description": "A cloaked figure appears at the edge of your farm, offering rare goods for an unusual price...",
        "choices": [
            ("📦 Select the glowing package", "3 Kale Seeds 🥬"),
            ("🎁 Choose the wooden box",      "100 Coins 🪙 + 2 Wood 🪵"),
            ("🚶 Ignore it",                  "5 Wood 🪵"),
        ],
    },
    "mystic-well": {
        "title": "Mystic Well",
        "description": "A bubbling well behind the plaza is glowing. Drop something in?",
        "choices": [
            ("💎 Drop your treasured item", "5 Stone 🪨"),
            ("🌑 Keep your belongings",     "50 Coins 🪙"),
            ("🚶 Ignore it",                "50 Coins 🪙"),
        ],
    },
    "petes-fishing-challenge": {
        "title": "Pete's Fishing Challenge",
        "description": "Pete boasts about his fishing skills by the lake. He challenges you to a contest. Accept?",
        "choices": [
            ("🎣 Compete!",      "5 Rods 🎣"),
            ("🧑‍🌾 Decline", "50 Coins 🪙"),
        ],
    },
    "petes-parade": {
        "title": "Pete's Parade",
        "description": "The plaza is setting up a parade, but Pete's float is broken! Help him fix it?",
        "choices": [
            ("🔍 Scour the dusty barn",     "5 Rods 🎣"),
            ("🚫 Leave the float unfinished", "50 Coins 🪙"),
            ("🚶 Ignore it",                 "3 Yellow Pansy 🌼"),
        ],
    },
    "plaza-whispers": {
        "title": "Plaza Whispers",
        "description": "Betty says the plaza is whispering secrets at night. Investigate the sound?",
        "choices": [
            ("🛠️ Uncover the fountain's secret", "10 Beetroot 🥬"),
            ("🌃 Walk into the night",            "50 Coins 🪙"),
            ("🚶 Ignore it",                      "5 Egg 🥚"),
        ],
    },
    "ravens-secret": {
        "title": "Raven's Secret",
        "description": "Who is Raven secretly related to?",
        "choices": [
            ("⚒️ The Blacksmith ✅", "100 Coins 🪙 + 5 Gems 💎"),
            ("🧝 A Moonseeker ❌",   "5 Love Charms 💘"),
            ("👸 Queen Victoria ❌", "5 Love Charms 💘"),
        ],
    },
    "ravens-vision": {
        "title": "Raven's Vision",
        "description": "Raven speaks of a vision involving a rare flower and a lunar event. Search for it?",
        "choices": [
            ("🌕 Wait beneath the moonlight", "8 Gems 💎"),
            ("🏳️ Skip the lunar ritual",    "50 Coins 🪙"),
            ("🚶 Ignore it",                  "3 Red Pansy 🌺"),
        ],
    },
    "sunken-bottle": {
        "title": "Sunken Bottle",
        "description": "A mysterious bottle washed ashore. It holds an old, crumpled note. Open it?",
        "choices": [
            ("🧭 Search the marked shoreline", "5 Iron Pickaxe ⛏️"),
            ("📄 Crumple the soggy note",      "50 Coins 🪙"),
            ("🚶 Ignore it",                   "100 Coins 🪙"),
        ],
    },
    "timmys-trouble": {
        "title": "Timmy's Trouble",
        "description": "Timmy swears he saw a Goblin stealing honey. Investigate the scene?",
        "choices": [
            ("🐾 Follow the sticky trail", "5 Honey 🍯"),
            ("🐝 Leave the hive be",       "50 Coins 🪙"),
            ("🚶 Ignore it",               "100 Coins 🪙"),
        ],
    },
    "treasure-dust": {
        "title": "Treasure Dust",
        "description": "Old Salty is sneezing—says it's the scent of nearby treasure. Follow his nose?",
        "choices": [
            ("🪣 Dig where he points",    "5 Pumpkin Seed 🎃"),
            ("🚫 Respect the boundaries", "50 Coins 🪙"),
            ("🚶 Ignore it",              "3 Yellow Pansy 🌼"),
        ],
    },
    "treasure-scroll": {
        "title": "Treasure Scroll",
        "description": "A crumpled scroll blows into your path, possibly leading to treasure. Will you read it?",
        "choices": [
            ("📜 Read it", "5 Pickaxes ⛏️"),
            ("🔥 Burn it", "5 Wood 🪵"),
        ],
    },
    "tywins-tax": {
        "title": "Tywin's Tax",
        "description": '"All Bumpkins must pay a special crop tax!" shouts Tywin. He demands payment... but something feels off.',
        "choices": [
            ("🧨 Sabotage his supply crate", "10 Kale 🥬"),
            ("😇 Do nothing",                "100 Coins 🪙"),
            ("📦 Pay the tax",               "3 Gems 💎"),
        ],
    },
    "victorias-command": {
        "title": "Victoria's Command",
        "description": "Queen Victoria demands a tribute of rare flowers. Comply or resist?",
        "choices": [
            ("🪻 Sneak into the garden", "5 Iron ⛓️"),
            ("🫡 Bow out gracefully",    "50 Coins 🪙"),
            ("🚶 Ignore it",             "10 Carrot 🥕"),
        ],
    },
    "whispering-flowers": {
        "title": "Whispering Flowers",
        "description": "Your sunflowers whisper secrets in the breeze. Lean in closer?",
        "choices": [
            ("👂 Listen closely", "100 Coins 🪙"),
            ("🏃 Ignore them",    "50 Coins 🪙"),
        ],
    },
    "whispers-in-the-wind": {
        "title": "Whispers in the Wind",
        "description": "A strange wind blows through the Plaza, carrying soft whispers that only you seem to hear. Something is calling...",
        "choices": [
            ("🌳 Dig beneath the tree", "1 Celestine Seed ✨"),
            ("🙉 Ignore the voices",   "50 Coins 🪙"),
            ("🔴 Block your ears",     "5 Wood 🪵"),
        ],
    },
    "wild-creature": {
        "title": "Wild Creature",
        "description": "Cornwell spots a wild creature near the woods. Dangerous—or valuable?",
        "choices": [
            ("🧭 Investigate", "5 Gems 💎"),
            ("🛡️ Stay safe", "5 Stone 🪨"),
        ],
    },
    "wishing-well": {
        "title": "Wishing Well",
        "description": "An old wishing well glows faintly under the stars. Toss a coin and make a wish?",
        "choices": [
            ("🪙 Toss a coin", "200 Coins 🪙"),
            ("🚶 Walk past",   "50 Coins 🪙"),
        ],
    },
    # Добавляй новые Questы ниже по тому же шаблону:
    # "quest-name": {
    #     "title": "...",
    #     "description": "...",
    #     "choices": [("Emoji Вариант", "Награда"), ...],
    # },
}

def format_daily_reward_ready(streaks: int, lang: str = "ru") -> str:
    """Уведомление в 00:00 UTC — награда доступна."""
    return _i18n("daily_reward_ready", lang, streaks=streaks)


def format_daily_reminder(streaks: int, hours_left: int, lang: str = "ru") -> str:
    """Ежечасное напоминание в 19-23 UTC если награда не собрана."""
    return _i18n("daily_reward_reminder", lang, streaks=streaks, hours=hours_left)


# Алиасы для квестов с апострофом — API может вернуть любой из вариантов:
# без апострофа (основной), с апострофом, или апостроф → дефис.
QUEST_DATA["bard's-visit"] = QUEST_DATA['bards-visit']
QUEST_DATA['bard-s-visit'] = QUEST_DATA['bards-visit']
QUEST_DATA["bert's-portal"] = QUEST_DATA['berts-portal']
QUEST_DATA['bert-s-portal'] = QUEST_DATA['berts-portal']
QUEST_DATA["cornwell's-curiosity"] = QUEST_DATA['cornwells-curiosity']
QUEST_DATA['cornwell-s-curiosity'] = QUEST_DATA['cornwells-curiosity']
QUEST_DATA["cornwell's-riddle"] = QUEST_DATA['cornwells-riddle']
QUEST_DATA['cornwell-s-riddle'] = QUEST_DATA['cornwells-riddle']
QUEST_DATA["finley's-fish"] = QUEST_DATA['finleys-fish']
QUEST_DATA['finley-s-fish'] = QUEST_DATA['finleys-fish']
QUEST_DATA["gambit's-bet"] = QUEST_DATA['gambits-bet']
QUEST_DATA['gambit-s-bet'] = QUEST_DATA['gambits-bet']
QUEST_DATA["grimbly's-feast"] = QUEST_DATA['grimblys-feast']
QUEST_DATA['grimbly-s-feast'] = QUEST_DATA['grimblys-feast']
QUEST_DATA["jester's-prank"] = QUEST_DATA['jesters-prank']
QUEST_DATA['jester-s-prank'] = QUEST_DATA['jesters-prank']
QUEST_DATA["merchant's-mystery-box"] = QUEST_DATA['merchants-mystery-box']
QUEST_DATA['merchant-s-mystery-box'] = QUEST_DATA['merchants-mystery-box']
QUEST_DATA["miranda's-song"] = QUEST_DATA['mirandas-song']
QUEST_DATA['miranda-s-song'] = QUEST_DATA['mirandas-song']
QUEST_DATA["pete's-fishing-challenge"] = QUEST_DATA['petes-fishing-challenge']
QUEST_DATA['pete-s-fishing-challenge'] = QUEST_DATA['petes-fishing-challenge']
QUEST_DATA["pete's-parade"] = QUEST_DATA['petes-parade']
QUEST_DATA['pete-s-parade'] = QUEST_DATA['petes-parade']
QUEST_DATA["raven's-secret"] = QUEST_DATA['ravens-secret']
QUEST_DATA['raven-s-secret'] = QUEST_DATA['ravens-secret']
QUEST_DATA["raven's-vision"] = QUEST_DATA['ravens-vision']
QUEST_DATA['raven-s-vision'] = QUEST_DATA['ravens-vision']
QUEST_DATA["timmy's-trouble"] = QUEST_DATA['timmys-trouble']
QUEST_DATA['timmy-s-trouble'] = QUEST_DATA['timmys-trouble']
QUEST_DATA["tywin's-tax"] = QUEST_DATA['tywins-tax']
QUEST_DATA['tywin-s-tax'] = QUEST_DATA['tywins-tax']
QUEST_DATA["victoria's-command"] = QUEST_DATA['victorias-command']
QUEST_DATA['victoria-s-command'] = QUEST_DATA['victorias-command']


def format_quest_notification(quest_name: str, lang: str = "ru") -> str:
    """Форматирует уведомление о новом Questе."""
    data = QUEST_DATA.get(quest_name)

    # Фallback: API иногда шлёт имя без притяжательного 's'
    # (напр. "bert-portal" вместо "berts-portal")
    if not data:
        parts = quest_name.split("-", 1)
        if len(parts) == 2:
            data = QUEST_DATA.get(parts[0] + "s-" + parts[1])

    header = "📜 <b>Новый Quest</b>  <a href=\"https://t.me/pumpkin_pete_bot?start=MrSnorch\">Pumpkin Pete</a>"

    if not data:
        # Quest неизвестен — показываем имя как есть
        display_name = quest_name.replace("-", " ").title()
        return f"{header}\n\n<b>{display_name}</b>"

    lines = [header, "", f"<b>{data['title']}</b>", data["description"]]

    if data.get("choices"):
        rewards_label = {"ru": "Награды", "en": "Rewards", "uk": "Нагороди"}.get(lang, "Rewards")
        lines.append(f"\n<b>{rewards_label}</b>")
        for choice, reward in data["choices"]:
            lines.append(f"{choice}: {reward}")

    return "\n".join(lines)


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
    if r.ok:
        return True
    # "message is not modified" — сообщение существует, текст не изменился → считаем успехом.
    # Это НЕ значит что сообщение удалено, поэтому возвращаем True чтобы не создавать дубль закрепа.
    if r.status_code == 400 and "is not modified" in r.text:
        return True
    return False

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
