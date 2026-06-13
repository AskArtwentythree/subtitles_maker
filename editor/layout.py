"""Проверка и устранение наложений элементов на таймлайне.

Модель «зон» вертикального кадра:
  - TOP    — плашки-подписи (label);
  - CENTER — сам продукт (текст не ставим);
  - BOTTOM — субтитры;
  - BOTTOM — аутро-CTA (поверх нижней зоны, в самом конце).

Опасные пересечения по времени+зоне:
  1. Интро (полный экран) в начале vs субтитры первого клипа.
  2. Аутро-CTA (низ) в конце vs субтитры последнего клипа  ← баг с «жми, чтобы узнать больше».
Плашки (верх) и субтитры (низ) разведены по зонам, поэтому не конфликтуют.

resolve_collisions() подрезает/прячет субтитры под окна интро/аутро и возвращает
отчёт. verify() пере-сканирует и подтверждает, что наложений не осталось.
"""

# Длины оверлеев интро/аутро (должны совпадать с рендерерами; пишем их в EDL).
INTRO_SEC = 1.4
OUTRO_SEC = 1.8
INTRO_GUARD = 0.1     # зазор после исчезновения интро
OUTRO_GUARD = 0.2     # зазор до появления CTA
MIN_VISIBLE = 0.8     # если после подрезки остаётся меньше — субтитр лучше скрыть
                      # (короткий «огрызок» читается как глюк-моргание)


def resolve_collisions(edl: dict) -> tuple[dict, list[str]]:
    """Развести субтитры с интро/аутро. Возвращает (edl, отчёт)."""
    clips = edl.get("clips", [])
    report: list[str] = []
    if not clips:
        edl["intro_sec"] = 0.0
        edl["outro_sec"] = 0.0
        return edl, report

    intro_sec = INTRO_SEC if (edl.get("intro") or {}).get("title") else 0.0
    outro_sec = OUTRO_SEC if (edl.get("outro") or {}).get("cta") else 0.0

    # --- Начало: субтитры первого клипа не должны лезть под интро ---
    if intro_sec > 0:
        first = clips[0]
        guard = intro_sec + INTRO_GUARD
        kept = []
        for cap in first.get("captions", []):
            if cap["end"] - guard < MIN_VISIBLE:
                report.append(f"субтитр «{cap['text'][:24]}…» скрыт под интро")
                continue
            if cap["start"] < guard:
                cap["start"] = round(guard, 3)
                report.append(f"субтитр «{cap['text'][:24]}…» сдвинут из-под интро")
            kept.append(cap)
        first["captions"] = kept

    # --- Конец: субтитры последнего клипа не должны лезть под CTA ---
    if outro_sec > 0:
        last = clips[-1]
        dur = last["src_end"] - last["src_start"]
        limit = dur - outro_sec - OUTRO_GUARD
        kept = []
        for cap in last.get("captions", []):
            if limit - cap["start"] < MIN_VISIBLE:
                report.append(f"субтитр «{cap['text'][:24]}…» скрыт под аутро-CTA")
                continue
            if cap["end"] > limit:
                cap["end"] = round(limit, 3)
                report.append(f"субтитр «{cap['text'][:24]}…» подрезан под аутро-CTA")
            kept.append(cap)
        last["captions"] = kept

    edl["intro_sec"] = intro_sec
    edl["outro_sec"] = outro_sec
    return edl, report


def verify(edl: dict) -> list[str]:
    """Пере-проверка: вернуть список оставшихся наложений (пусто = чисто)."""
    issues: list[str] = []
    clips = edl.get("clips", [])
    intro_sec = edl.get("intro_sec", 0.0)
    outro_sec = edl.get("outro_sec", 0.0)

    for i, c in enumerate(clips):
        caps = c.get("captions", [])
        dur = c["src_end"] - c["src_start"]
        # Субтитры внутри клипа не должны пересекаться между собой.
        for a, b in zip(caps, caps[1:]):
            if b["start"] < a["end"] - 0.01:
                issues.append(f"клип {i}: субтитры пересекаются по времени")
        # Под интро (первый клип) / под аутро (последний клип) субтитров быть не должно.
        if i == 0 and intro_sec > 0:
            for cap in caps:
                if cap["start"] < intro_sec + INTRO_GUARD - 0.01:
                    issues.append(f"клип 0: субтитр всё ещё под интро")
        if i == len(clips) - 1 and outro_sec > 0:
            limit = dur - outro_sec - OUTRO_GUARD
            for cap in caps:
                if cap["end"] > limit + 0.01:
                    issues.append(f"клип {i}: субтитр всё ещё под аутро-CTA")
    return issues
