"""
Расчёт времени готовности по «окнам ускорения» (speed windows) — порт логики игры.

Источник: sunflower-land/src/features/game/lib/boostWindows.ts, collectibleBuilt.ts.

Как это работает в игре (новая модель):
  * plantedAt / choppedAt / minedAt / drilledAt / harvestedAt — РЕАЛЬНОЕ время старта
    (раньше игра «сдвигала» его назад на размер буста).
  * baseDurationMs — длительность «работы» уже с учётом постоянных бонусов (скиллы, вещи).
  * Временные бусты (тотемы, часовые, святилища, Power hour, Sunshower, удобрения)
    не вшиты в данные, а считаются окнами: speed × время. Готовность — момент, когда
    накопленная «работа» (длительность окна × speed) достигла baseDurationMs.

Если у ресурса нет baseDurationMs (старый формат) — вызывающий код использует прежнюю
формулу «старт + константа».

НЕ учтено (в данных фермы этого нет / слишком сложно переносить):
  * Sunshower Guardian (доп. ×2 в сезонный Sunshower при выставленном страже сезона).
"""
from __future__ import annotations

H = 3_600_000
DAY = 24 * H
MAX_TS = 2 ** 53 - 1

# Время жизни временных бустов (EXPIRY_COOLDOWNS в игре)
EXPIRY_MS: dict[str, int] = {
    "Time Warp Totem":   4 * H,
    "Super Totem":       7 * DAY,
    "Gourmet Hourglass": 6 * H,
    "Harvest Hourglass": 9 * H,
    "Timber Hourglass":  4 * H,
    "Ore Hourglass":     5 * H,
    "Orchard Hourglass": 8 * H,
    "Blossom Hourglass": 12 * H,
    "Fisher's Hourglass": 4 * H,
    # Все pet-святилища — 7 дней
    "Sparrow Shrine": 7 * DAY, "Toucan Shrine": 7 * DAY, "Moth Shrine": 7 * DAY,
    "Badger Shrine":  7 * DAY, "Mole Shrine":   7 * DAY, "Stag Shrine": 7 * DAY,
}

# Множители скорости (CROP_PLOT_/TREE_/MINE_/FRUIT_/FLOWER_/OIL_BOOST_SPEED)
SP_TOTEM = 2
CROP_SPEED = {"Sparrow Shrine": 1.35, "Harvest Hourglass": 1.35,
              "Power hour": 2, "Rapid Root": 2, "Sproutroot Surprise": 2, "sunshower": 2}
TREE_SPEED = {"Timber Hourglass": 1.35, "Badger Shrine": 1.35}
MINE_SPEED = {"Ore Hourglass": 2, "Badger Shrine": 1.35, "Mole Shrine": 1.35}
FRUIT_SPEED = {"Orchard Hourglass": 1.35, "Toucan Shrine": 1.35, "Turbofruit Mix": 1.25}
FLOWER_SPEED = {"Blossom Hourglass": 1.35, "Moth Shrine": 1.35}
OIL_SPEED = {"Stag Shrine": 1.35}


def _d(x) -> dict:
    return x if isinstance(x, dict) else {}


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _merge(windows: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    """Склеиваем пересекающиеся окна ОДИНАКОВОЙ скорости (порт mergeWindows)."""
    windows = [w for w in windows if w[1] > w[0]]
    if len(windows) <= 1:
        return windows
    ws = sorted(windows, key=lambda w: w[0])
    merged = [list(ws[0])]
    for f, t, s in ws[1:]:
        last = merged[-1]
        if s == last[2] and f <= last[1]:
            last[1] = max(last[1], t)
        else:
            merged.append([f, t, s])
    return [tuple(m) for m in merged]


def _placed(farm: dict, name: str) -> list[dict]:
    """Все экземпляры коллекционки со всех локаций (ферма, дом, интерьер)."""
    out: list[dict] = []
    interior = _d(farm.get("interior"))
    for src in (_d(farm.get("collectibles")),
                _d(_d(farm.get("home")).get("collectibles")),
                _d(_d(interior.get("ground")).get("collectibles")),
                _d(_d(interior.get("level_one")).get("collectibles"))):
        for item in (src.get(name) or []):
            if isinstance(item, dict):
                out.append(item)
    return out


def _boost_windows(farm: dict, name: str, speed: float) -> list[tuple]:
    """Окна временного коллекционного буста: текущие размещения + boostHistory."""
    win: list[tuple] = []
    expiry_ms = EXPIRY_MS.get(name, 0)
    for p in _placed(farm, name):
        created = _num(p.get("createdAt"))
        if created is None:
            continue
        expiry = created + expiry_ms + (_num(p.get("extendedMs")) or 0)
        removed = _num(p.get("removedAt"))
        to = min(expiry, removed) if removed is not None else expiry
        win.append((created, to, speed))
    for h in _d(farm.get("boostHistory")).get(name, []) or []:
        if isinstance(h, dict) and _num(h.get("from")) is not None and _num(h.get("to")) is not None:
            win.append((h["from"], h["to"], speed))
    return _merge(win)


def _totem_windows(farm: dict) -> list[tuple]:
    """Super Totem и Time Warp Totem — один и тот же буст ×2, не стакаются."""
    return _merge(_boost_windows(farm, "Super Totem", SP_TOTEM)
                  + _boost_windows(farm, "Time Warp Totem", SP_TOTEM))


def _power_hour_windows(farm: dict) -> list[tuple]:
    speed = CROP_SPEED["Power hour"]
    buff = _d(_d(farm.get("buffs")).get("Power hour"))
    started = _num(buff.get("startedAt"))
    live = []
    if started is not None:
        live.append((started, started + (_num(buff.get("durationMS")) or 0), speed))
    hist = [(h["from"], h["to"], speed)
            for h in (_d(farm.get("boostHistory")).get("Power hour") or [])
            if isinstance(h, dict) and _num(h.get("from")) is not None
            and _num(h.get("to")) is not None and h.get("from") != started]
    return _merge(live + hist)


def _sunshower_windows(farm: dict) -> list[tuple]:
    from datetime import datetime, timezone
    speed = CROP_SPEED["sunshower"]
    hist = [(h["from"], h["to"], speed)
            for h in (_d(farm.get("boostHistory")).get("Sunshower") or [])
            if isinstance(h, dict) and _num(h.get("from")) is not None
            and _num(h.get("to")) is not None]
    started = _num(_d(_d(farm.get("calendar")).get("sunshower")).get("startedAt"))
    if started is not None and not any(w[0] == started for w in hist):
        day = datetime.fromtimestamp(started / 1000, tz=timezone.utc)
        end = datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000 + DAY
        hist.insert(0, (started, end, speed))
    return hist


def crop_windows(farm: dict) -> list[tuple]:
    return (_boost_windows(farm, "Sparrow Shrine", CROP_SPEED["Sparrow Shrine"])
            + _boost_windows(farm, "Harvest Hourglass", CROP_SPEED["Harvest Hourglass"])
            + _totem_windows(farm) + _power_hour_windows(farm) + _sunshower_windows(farm))


def tree_windows(farm: dict) -> list[tuple]:
    return (_totem_windows(farm)
            + _boost_windows(farm, "Timber Hourglass", TREE_SPEED["Timber Hourglass"])
            + _boost_windows(farm, "Badger Shrine", TREE_SPEED["Badger Shrine"]))


def mine_windows(farm: dict, kind: str) -> list[tuple]:
    """kind: stones | iron | gold | crimstones"""
    if kind == "crimstones":
        return _boost_windows(farm, "Mole Shrine", MINE_SPEED["Mole Shrine"])
    shrine = "Badger Shrine" if kind == "stones" else "Mole Shrine"
    return (_totem_windows(farm)
            + _boost_windows(farm, "Ore Hourglass", MINE_SPEED["Ore Hourglass"])
            + _boost_windows(farm, shrine, MINE_SPEED[shrine]))


def fruit_windows(farm: dict) -> list[tuple]:
    return (_totem_windows(farm)
            + _boost_windows(farm, "Orchard Hourglass", FRUIT_SPEED["Orchard Hourglass"])
            + _boost_windows(farm, "Toucan Shrine", FRUIT_SPEED["Toucan Shrine"]))


def flower_windows(farm: dict) -> list[tuple]:
    return (_boost_windows(farm, "Blossom Hourglass", FLOWER_SPEED["Blossom Hourglass"])
            + _boost_windows(farm, "Moth Shrine", FLOWER_SPEED["Moth Shrine"]))


def oil_windows(farm: dict) -> list[tuple]:
    return _boost_windows(farm, "Stag Shrine", OIL_SPEED["Stag Shrine"])


def crop_fertiliser_windows(fertiliser) -> list[tuple]:
    f = _d(fertiliser)
    if f.get("name") in ("Rapid Root", "Sproutroot Surprise") and _num(f.get("fertilisedAt")) is not None:
        return [(f["fertilisedAt"], MAX_TS, CROP_SPEED[f["name"]])]
    return []


def fruit_fertiliser_windows(fertiliser) -> list[tuple]:
    f = _d(fertiliser)
    if f.get("name") == "Turbofruit Mix" and _num(f.get("fertilisedAt")) is not None:
        return [(f["fertilisedAt"], MAX_TS, FRUIT_SPEED["Turbofruit Mix"])]
    return []


def compute_ready_at(started_at: float, base_duration_ms: float, windows: list[tuple]) -> float:
    """Момент, когда накопленная работа достигает base_duration_ms (порт computeReadyAt)."""
    if base_duration_ms <= 0:
        return started_at
    clipped = [(max(f, started_at), t, s) for f, t, s in windows if t > max(f, started_at)]
    if not clipped:
        return started_at + base_duration_ms

    bounds = sorted({started_at, *[w[0] for w in clipped], *[w[1] for w in clipped]})
    acc = 0.0
    for i in range(len(bounds) - 1):
        f, t = bounds[i], bounds[i + 1]
        mid = (f + t) / 2
        speed = 1.0
        for wf, wt, ws in clipped:
            if wf <= mid < wt:
                speed *= ws
        work = (t - f) * speed
        if acc + work >= base_duration_ms:
            return f + (base_duration_ms - acc) / speed
        acc += work
    return bounds[-1] + (base_duration_ms - acc)
