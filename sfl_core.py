#!/usr/bin/env python3
"""
sfl_core.py — Общая логика сканирования SFL (без GUI, без GitHub Variables).
Используется и сканером, и ботом.
"""

import json, os, time, logging
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
    UA_TZ = ZoneInfo("Europe/Kiev")
except Exception:
    from datetime import timezone as _tz, timedelta as _td
    UA_TZ = _tz(_td(hours=3))

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
    "Tomato":    2*3_600_000,
    "Lemon":     4*3_600_000,
    "Chestnut":  4*3_600_000,
    "Blueberry": 6*3_600_000,
    "Starfruit": 6*3_600_000,
    "Orange":    8*3_600_000,
    "Apple":     12*3_600_000,
    "Banana":    12*3_600_000,
    "Coconut":   12*3_600_000,
    "Grape":     8*3_600_000,
    "Big Apple": 12*3_600_000, "Big Orange": 8*3_600_000,
    "Big Banana": 12*3_600_000, "Giant Apple": 12*3_600_000, "Giant Orange": 8*3_600_000,
}

FLOWER_GROW_MS: dict[str, int] = {
    "default": 24*3_600_000,
    "Celestine": 24*3_600_000, "Duskberry": 24*3_600_000, "Lunara": 24*3_600_000,
    "Primrose Petal": 24*3_600_000, "Clover": 24*3_600_000, "Gladiolus": 24*3_600_000,
    "Prism Petal": 72*3_600_000, "Primula Enigma": 72*3_600_000,
    "Celestial Frostbloom": 72*3_600_000,
    **{f"{c} {k}": (48 if c in ("Red","Purple","Blue") else 24)*3_600_000
       for k in ("Balloon Flower","Carnation","Daffodil","Lotus","Pansy","Cosmos","Tulip")
       for c in ("Red","Yellow","Purple","White","Blue")}
}

TREE_RESPAWN_MS     = 2  * 3_600_000
STONE_RESPAWN_MS    = 4  * 3_600_000
IRON_RESPAWN_MS     = 8  * 3_600_000
GOLD_RESPAWN_MS     = 24 * 3_600_000
CRIM_RESPAWN_MS     = 36 * 3_600_000
OIL_RESPAWN_MS      = 24 * 3_600_000
SALT_RESPAWN_MS     = 8  * 3_600_000
SUNSTONE_RESPAWN_MS = 72 * 3_600_000
MUSH_SPAWN_MS       = 16 * 3_600_000

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
                 extra="", pending_at_ms=None):
        self.name         = name
        self.emoji        = emoji
        self.ready_at_ms  = ready_at_ms
        self.count        = count
        self.ready_count  = ready_count
        self.extra        = extra
        self.pending_at_ms = pending_at_ms if pending_at_ms is not None else ready_at_ms

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

    def fmt_pending_ready_time(self):
        return datetime.fromtimestamp(
            self.pending_at_ms / 1000, tz=UA_TZ).strftime("%H:%M")

# ══════════════════════════════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════════════════════════════

def load_from_api(farm_id: str, api_key: str) -> dict:
    r = requests.get(
        f"https://api.sunflower-land.com/community/farms/{farm_id}",
        headers={"x-api-key": api_key},
        timeout=25,
    )
    r.raise_for_status()
    data = r.json()
    return data.get("farm", data)

# ══════════════════════════════════════════════════════════════════════════════
# СКАНИРОВАНИЕ
# ══════════════════════════════════════════════════════════════════════════════

def _fix_ts(ts):
    """Конвертирует секунды → миллисекунды если нужно."""
    if ts and 0 < ts < 10_000_000_000:
        return ts * 1000
    return ts

def scan_farm(farm: dict, track: dict) -> list[Event]:
    events = []
    now_ms = int(time.time() * 1000)

    # ── CROPS ─────────────────────────────────────────────────────────────────
    if track.get("crops", True):
        crop_map: dict[str, list] = {}
        for pid, plot in farm.get("crops", {}).items():
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
                pending_at_ms=pnd))

    # ── TREES ─────────────────────────────────────────────────────────────────
    if track.get("trees", True):
        tt = []
        for tid, tree in farm.get("trees", {}).items():
            ch = _fix_ts(tree.get("wood", {}).get("choppedAt", 0))
            if ch:
                tt.append(ch + TREE_RESPAWN_MS)
        if tt:
            tt.sort(); rc = sum(1 for t in tt if t <= now_ms)
            pnd = tt[rc] if rc < len(tt) else tt[-1]
            events.append(Event("Trees", "🪵", tt[0], len(tt), rc,
                f"{rc}/{len(tt)} готово" if rc else f"{len(tt)} деревьев",
                pending_at_ms=pnd))

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
                m = _fix_ts(s.get("stone", {}).get("minedAt", 0))
                if m:
                    st.append(m + respawn)
            if st:
                st.sort(); rc = sum(1 for t in st if t <= now_ms)
                pnd = st[rc] if rc < len(st) else st[-1]
                events.append(Event(label, emoji, st[0], len(st), rc,
                    f"{rc}/{len(st)} готово" if rc else f"{len(st)} шт.",
                    pending_at_ms=pnd))

    # ── OIL ───────────────────────────────────────────────────────────────────
    if track.get("oil", False):
        ot = []
        for oid, s in farm.get("oilReserves", {}).items():
            d = _fix_ts(s.get("oil", {}).get("drilledAt", 0))
            if d:
                ot.append(d + OIL_RESPAWN_MS)
        if ot:
            ot.sort(); rc = sum(1 for t in ot if t <= now_ms)
            pnd = ot[rc] if rc < len(ot) else ot[-1]
            events.append(Event("Oil", "🛢️", ot[0], len(ot), rc,
                f"{rc}/{len(ot)} готово" if rc else f"{len(ot)} скважин",
                pending_at_ms=pnd))

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
                f"{rc}/{total} готово" if rc else f"{total} узл."))

    # ── SUNSTONES ─────────────────────────────────────────────────────────────
    if track.get("sunstones", False):
        ss = []
        for ssid, s in farm.get("sunstones", {}).items():
            m = _fix_ts(s.get("stone", {}).get("minedAt", 0))
            if m:
                ss.append(m + SUNSTONE_RESPAWN_MS)
        if ss:
            ss.sort(); rc = sum(1 for t in ss if t <= now_ms)
            pnd = ss[rc] if rc < len(ss) else ss[-1]
            events.append(Event("Sunstones", "🌟", ss[0], len(ss), rc,
                f"{rc}/{len(ss)} готово" if rc else f"{len(ss)} жил",
                pending_at_ms=pnd))

    # ── FRUITS ────────────────────────────────────────────────────────────────
    if track.get("fruits", True):
        fruit_map: dict[str, list] = {}
        for pid, patch in farm.get("fruitPatches", {}).items():
            fr = patch.get("fruit")
            if not fr or fr.get("harvestsLeft", 0) == 0:
                continue
            name = fr.get("name", "Фрукт")
            hv = _fix_ts(fr.get("harvestedAt", 0))
            if not hv:
                continue
            regrow = FRUIT_REGROW_MS.get(name, 14*3_600_000)
            fruit_map.setdefault(name, []).append(hv + regrow)
        for name, times in fruit_map.items():
            times.sort(); rc = sum(1 for t in times if t <= now_ms)
            pnd = times[rc] if rc < len(times) else times[-1]
            events.append(Event(name, "🍎", times[0], len(times), rc,
                f"{rc}/{len(times)} готово" if rc else f"{len(times)} деревьев",
                pending_at_ms=pnd))

    # ── FLOWERS ───────────────────────────────────────────────────────────────
    if track.get("flowers", True):
        flower_map: dict[str, list] = {}
        for bid, bed in farm.get("flowers", {}).get("flowerBeds", {}).items():
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
            grow = FLOWER_GROW_MS.get(name, FLOWER_GROW_MS["default"])
            flower_map.setdefault(name, []).append(planted + grow)
        for name, times in flower_map.items():
            times.sort(); rc = sum(1 for t in times if t <= now_ms)
            pnd = times[rc] if rc < len(times) else times[-1]
            events.append(Event(name, "🌸", times[0], len(times), rc,
                f"{rc}/{len(times)} готово" if rc else f"{len(times)} грядок",
                pending_at_ms=pnd))

    # ── HONEY ─────────────────────────────────────────────────────────────────
    if track.get("honey", True):
        ht = []; hive_swarm = 0
        for hid, hive in farm.get("beehives", {}).items():
            if hive.get("swarm"):
                hive_swarm += 1
            for fl_link in hive.get("flowers", []):
                until = _fix_ts(fl_link.get("attachedUntil", 0))
                if until:
                    ht.append(until); break
        bee_swarm = len(farm.get("collectibles", {}).get("Bee Swarm", []))
        swarm_total = hive_swarm + bee_swarm
        if ht:
            ht.sort(); rc = sum(1 for t in ht if t <= now_ms)
            pnd = ht[rc] if rc < len(ht) else ht[-1]
            extra = f"🐝 Bee Swarm x{swarm_total}" if swarm_total else ""
            events.append(Event("Honey", "🍯", ht[0], len(ht), rc,
                extra, pending_at_ms=pnd))

    # ── MUSHROOMS ─────────────────────────────────────────────────────────────
    if track.get("mushrooms", False):
        mush = farm.get("mushrooms", {})
        sa = _fix_ts(mush.get("spawnedAt", 0))
        if sa:
            events.append(Event("Mushrooms", "🍄", sa + MUSH_SPAWN_MS, 1,
                extra="новая партия"))

    # ── ANIMALS ───────────────────────────────────────────────────────────────
    if track.get("animals", False):
        ag: dict[str, list] = {}
        for src in ("henHouse", "barn"):
            for aid, animal in farm.get(src, {}).get("animals", {}).items():
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
            events.append(Event(atype, emoji, first, len(times), rc,
                f"{rc}/{len(times)} проснулось" if rc else f"{len(times)} животных"))

    events.sort(key=lambda e: e.ready_at_ms)
    return events

# ══════════════════════════════════════════════════════════════════════════════
# ФОРМАТИРОВАНИЕ СООБЩЕНИЙ
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_ms_human(ms: int) -> str:
    if ms <= 0: return "сейчас"
    s = ms // 1000; h, rem = divmod(s, 3600); m, sc = divmod(rem, 60)
    if h >= 24:
        d = h // 24; h = h % 24
        return f"через {d}д {h:02d}:{m:02d}:{sc:02d}"
    if h > 0: return f"через {h}ч {m:02d}м {sc:02d}с"
    if m > 0: return f"через {m}м {sc:02d}с"
    return f"через {sc}с"

def format_status_message(events: list[Event], farm_id: str) -> str:
    """Статус-сообщение — закреп (редактируется, не уведомляет)."""
    if not events:
        return f"🌻 Ферма <b>{farm_id}</b>\n\nНет отслеживаемых ресурсов."

    pending = [e for e in events if e.ready_count < e.count]
    lines = [f"🌻 <b>Ферма {farm_id}</b>"]

    if not pending:
        lines.append("\n✅ <b>Всё готово к сбору!</b>")
    else:
        lines.append("")
        for e in sorted(pending, key=lambda x: x.pending_at_ms)[:20]:
            cnt_label = f" [{e.count - e.ready_count}]" if e.count > 1 else ""
            ms_left = max(0, e.pending_at_ms - int(time.time() * 1000))
            swarm_extra = ""
            if e.name == "Honey" and e.extra:
                import re as _re
                m = _re.search(r"Swarm x(\d+)", e.extra)
                swarm_extra = f" (Swarm x{m.group(1)})" if m else ""
            lines.append(
                f"{e.emoji} <b>{e.name}{cnt_label}{swarm_extra}</b>"
                f" — {_fmt_ms_human(ms_left)} — {e.fmt_pending_ready_time()}"
            )

    ready_now = [e for e in events if e.ready_count > 0]
    if ready_now:
        lines.append("\n✅ <b>Готово к сбору:</b>")
        for e in ready_now:
            cnt = f" [{e.ready_count}/{e.count}]" if e.count > 1 else ""
            lines.append(f"  {e.emoji} {e.name}{cnt}")

    ts = datetime.now(tz=UA_TZ).strftime("%d.%m %H:%M")
    lines.append(f"\n<i>Обновлено: {ts}</i>")
    return "\n".join(lines)

def format_ready_alert(e: Event) -> str:
    cnt = f" [{e.ready_count}/{e.count}]" if e.count > 1 else ""
    is_honey = e.name == "Honey"
    extra_label = f" ({e.extra})" if (e.extra and is_honey) else ""
    return f"{e.emoji} <b>{e.name}{cnt}{extra_label} — готово к сбору ✅</b>"

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

def tg_edit(token: str, chat_id: int, message_id: int, text: str) -> bool:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/editMessageText",
            json={"chat_id": chat_id, "message_id": message_id,
                  "text": text, "parse_mode": "HTML"},
            timeout=20)
        return r.ok
    except Exception:
        return False

def tg_delete(token: str, chat_id: int, message_id: int):
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/deleteMessage",
            json={"chat_id": chat_id, "message_id": message_id},
            timeout=10)
    except Exception:
        pass

def tg_upsert_status(token: str, chat_id: int, text: str,
                     message_id: int | None) -> int:
    """Создаёт или редактирует статус-сообщение. Возвращает message_id."""
    if message_id:
        if tg_edit(token, chat_id, message_id, text):
            return message_id
    mid = tg_send(token, chat_id, text, silent=True)
    return mid or message_id or 0
