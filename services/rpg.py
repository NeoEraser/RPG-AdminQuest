import math

TITLES_CONFIG = [
    {"name": "AnyKeyMan", "total_exp": 200, "first_exp": 1, "last_exp": 3},   # среднее 2
    {"name": "Junior",      "total_exp": 1000, "first_exp": 5, "last_exp": 15}, # среднее 10
    {"name": "Middle",      "total_exp": 5000, "first_exp": 25, "last_exp": 75},# среднее 50
    {"name": "Senior",      "total_exp": 25000, "first_exp": 125, "last_exp": 375},# среднее 250
]

LEVELS_PER_TITLE = 100

def _build_exp_table(first_exp: int, last_exp: int, total_exp: int) -> list[int]:
    """
    Строит таблицу EXP для переходов между уровнями внутри титула.
    first_exp -> EXP для перехода 1→2
    last_exp -> EXP для перехода 99→100
    """
    exp_table = []
    for level in range(1, LEVELS_PER_TITLE + 1):
        exp_needed = first_exp + (level - 1) * (last_exp - first_exp) / (LEVELS_PER_TITLE - 1)
        exp_table.append(round(exp_needed))
    
    # Корректируем последний элемент, чтобы сумма совпала с total_exp
    diff = total_exp - sum(exp_table)
    exp_table[-1] += diff
    
    return exp_table

# Предрассчитываем таблицы EXP для каждого титула
EXP_TABLES = [_build_exp_table(cfg["first_exp"], cfg["last_exp"], cfg["total_exp"]) for cfg in TITLES_CONFIG]

# Предрассчитываем кумулятивные EXP для каждого уровня
CUMULATIVE_EXP = []
running_total = 0

for title_idx, cfg in enumerate(TITLES_CONFIG):
    title_cumulative = []
    for level in range(LEVELS_PER_TITLE + 1):
        title_cumulative.append(running_total)
        if level < LEVELS_PER_TITLE:
            running_total += EXP_TABLES[title_idx][level]
    CUMULATIVE_EXP.append(title_cumulative)

def calculate_level(total_exp: int) -> int:
    """Возвращает общий уровень (1–400)"""
    if total_exp <= 0:
        return 1
    
    # Идем с конца, чтобы найти максимальный доступный уровень
    for title_idx in range(len(TITLES_CONFIG) - 1, -1, -1):
        for level_in_title in range(LEVELS_PER_TITLE, 0, -1):
            exp_needed = CUMULATIVE_EXP[title_idx][level_in_title - 1]
            if total_exp >= exp_needed:
                global_level = title_idx * LEVELS_PER_TITLE + level_in_title
                return min(global_level, 400)
    
    return 1

def get_title_and_level(global_level: int) -> tuple[str, int]:
    """Возвращает (титул, уровень_внутри_титула) по общему уровню"""
    if global_level <= 0:
        return TITLES_CONFIG[0]["name"], 1
    
    title_idx = (global_level - 1) // LEVELS_PER_TITLE
    
    if title_idx >= len(TITLES_CONFIG):
        return TITLES_CONFIG[-1]["name"], LEVELS_PER_TITLE
    
    level_in_title = global_level - title_idx * LEVELS_PER_TITLE
    return TITLES_CONFIG[title_idx]["name"], level_in_title

def exp_for_next_level(current_level: int) -> int:
    """Возвращает общее количество EXP для достижения указанного уровня (кумулятивно)"""
    if current_level <= 1:
        return 0
    
    title_idx = (current_level - 1) // LEVELS_PER_TITLE
    
    if title_idx >= len(TITLES_CONFIG):
        return CUMULATIVE_EXP[-1][-1]
    
    level_in_title = current_level - title_idx * LEVELS_PER_TITLE
    return CUMULATIVE_EXP[title_idx][level_in_title - 1]

def get_tag_title(level: int) -> str:
    """Возвращает тег для Telegram в формате 'Title Lvl' (до 16 символов)"""
    title, lvl = get_title_and_level(level)
    return f"{title} {lvl} lvl"