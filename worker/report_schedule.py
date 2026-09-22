"""Agenda dos relatorios do grupo, lida das settings.

Ate 09/2026 os horarios ficavam fixos no codigo (bom dia 06:00, ciclos 06:10 a
20:10). Agora vem de `REPORT_MORNING_TIME`, `REPORT_CYCLE_FIRST`,
`REPORT_CYCLE_LAST` e `REPORT_CYCLE_INTERVAL_HOURS`, e a mensagem de bom dia
anuncia exatamente o que o scheduler vai executar.
"""

from datetime import datetime

from worker.settings import settings


def _hhmm(value: str) -> tuple[int, int]:
    hour, minute = (int(part) for part in value.split(":"))
    return hour, minute


MORNING_HOUR, MORNING_MINUTE = _hhmm(settings.REPORT_MORNING_TIME)
FIRST_CYCLE_HOUR, FIRST_CYCLE_MINUTE = _hhmm(settings.REPORT_CYCLE_FIRST)
LAST_CYCLE_HOUR, LAST_CYCLE_MINUTE = _hhmm(settings.REPORT_CYCLE_LAST)
INTERVAL_HOURS = settings.REPORT_CYCLE_INTERVAL_HOURS


def cycle_hours() -> tuple[int, ...]:
    """Horas em que um ciclo pode disparar (06, 08, ... 20 por padrao)."""
    return tuple(range(FIRST_CYCLE_HOUR, LAST_CYCLE_HOUR + 1, INTERVAL_HOURS))


def cycle_labels() -> tuple[str, ...]:
    """Horarios dos ciclos como aparecem para o time, ex. ('06:30', ...)."""
    return tuple(
        f"{hour:02d}:{(LAST_CYCLE_MINUTE if hour == LAST_CYCLE_HOUR else FIRST_CYCLE_MINUTE):02d}"
        for hour in cycle_hours()
    )


def is_morning_time(now: datetime) -> bool:
    return now.hour == MORNING_HOUR and now.minute >= MORNING_MINUTE


def is_cycle_time(now: datetime) -> bool:
    if now.hour not in cycle_hours():
        return False
    if now.hour == LAST_CYCLE_HOUR:
        return now.minute >= LAST_CYCLE_MINUTE
    return now.minute >= FIRST_CYCLE_MINUTE
