"""
Сверяет CROP_GROW_MS / FRUIT_REGROW_MS в sfl_core.py с исходниками
sunflower-land на GitHub. Ничего не меняет в sfl_core.py автоматически —
только печатает diff, применять руками.

Запуск:
    python tools/sync_crop_timers.py

Источники:
    crops.ts  -> CROP_SEEDS[*].plantSeconds  (yield: <CropName>)
    fruits.ts -> PATCH_FRUIT_SEEDS[*].plantSeconds (yield: <FruitName>)
"""
import re
import sys
import urllib.request

RAW_BASE = "https://raw.githubusercontent.com/sunflower-land/sunflower-land/main/src/features/game/types"

CROPS_URL = f"{RAW_BASE}/crops.ts"
FRUITS_URL = f"{RAW_BASE}/fruits.ts"

# путь до sfl_core.py относительно этого файла
CORE_PATH = __file__.rsplit("/tools/", 1)[0] + "/sfl_core.py"

SECONDS_EXPR = re.compile(r"(\d+)\s*\*\s*60\s*\*\s*60|(\d+)\s*\*\s*60(?!\s*\*)")


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=20) as r:
        return r.read().decode("utf-8")


def parse_seed_seconds(ts_source: str) -> dict[str, int]:
    """
    Ищет записи вида:
        "X Seed": {
            ...
            plantSeconds: N * 60 * 60,
            ...
            yield: "CropName",
        },
    Блоки могут содержать вложенные {..} (bumpkinLevel: {...}), поэтому
    режем по границам "... Seed": { ... до следующего '"... Seed":' или конца записей.
    """
    result: dict[str, int] = {}
    seed_starts = [m.start() for m in re.finditer(r'"\s*[\w ]+ Seed"\s*:\s*\{', ts_source)]
    for i, start in enumerate(seed_starts):
        end = seed_starts[i + 1] if i + 1 < len(seed_starts) else len(ts_source)
        body = ts_source[start:end]
        sec_match = re.search(r"plantSeconds:\s*([^\n,]+)", body)
        yield_match = re.search(r'yield:\s*"([^"]+)"', body)
        if not sec_match or not yield_match:
            continue
        seconds = eval_seconds_expr(sec_match.group(1))
        if seconds is None:
            continue
        result[yield_match.group(1)] = seconds
    return result


def eval_seconds_expr(expr: str) -> int | None:
    """Считает выражения вида '24 * 60 * 60' или '60_000' безопасно (без eval)."""
    expr = expr.strip()
    parts = [p.strip() for p in expr.split("*")]
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    result = 1
    for n in nums:
        result *= n
    return result


def load_current_core_dict(varname: str) -> dict[str, int]:
    """Парсит текущий словарь CROP_GROW_MS / FRUIT_REGROW_MS прямо из sfl_core.py."""
    with open(CORE_PATH, encoding="utf-8") as f:
        src = f.read()
    m = re.search(rf"{varname}[^=]*=\s*\{{(.*?)\n\}}", src, re.S)
    if not m:
        print(f"! Не нашёл {varname} в sfl_core.py")
        return {}
    body = m.group(1)
    result: dict[str, int] = {}
    for line in body.splitlines():
        line = line.split("#")[0].strip().rstrip(",")
        if not line or ":" not in line:
            continue
        name_part, val_part = line.split(":", 1)
        name = name_part.strip().strip('"')
        seconds_ms = eval_seconds_expr(val_part.strip())
        if seconds_ms is not None:
            result[name] = seconds_ms // 1000  # в скрипте храним мс, тут сводим к секундам
    return result


def diff(label: str, current_sec: dict[str, int], upstream_sec: dict[str, int]):
    print(f"\n=== {label} ===")
    missing = sorted(set(upstream_sec) - set(current_sec))
    extra = sorted(set(current_sec) - set(upstream_sec))
    changed = sorted(
        name for name in set(current_sec) & set(upstream_sec)
        if current_sec[name] != upstream_sec[name]
    )

    if missing:
        print("Отсутствуют в скрипте (нужно добавить):")
        for name in missing:
            h = upstream_sec[name] / 3600
            print(f'    "{name}": {h:g}*3_600_000  # {upstream_sec[name]}s')
    if changed:
        print("Расхождение значений:")
        for name in changed:
            print(f"    {name}: в скрипте {current_sec[name]}s, в игре {upstream_sec[name]}s")
    if extra:
        print("Есть в скрипте, но нет в upstream-списке (могли переименовать/убрать, либо это не Seed-запись):")
        for name in extra:
            print(f"    {name}")
    if not (missing or changed or extra):
        print("Расхождений нет.")


def main():
    crops_ts = fetch(CROPS_URL)
    fruits_ts = fetch(FRUITS_URL)

    upstream_crops = parse_seed_seconds(crops_ts)
    upstream_fruits = parse_seed_seconds(fruits_ts)

    current_crop = load_current_core_dict("CROP_GROW_MS")
    current_fruit = load_current_core_dict("FRUIT_REGROW_MS")

    diff("CROP_GROW_MS (crops.ts)", current_crop, upstream_crops)
    diff("FRUIT_REGROW_MS (fruits.ts)", current_fruit, upstream_fruits)

    print("\nПримечание: ресурсы (дерево/камень/золото/крим/масло/соль/сансто́ун/грибы) "
          "и таймеры цветов не описаны в resources.ts/flowers.ts как готовые секунды — "
          "их автосинк не покрывает, сверять вручную.")


if __name__ == "__main__":
    main()
