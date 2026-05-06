from datetime import datetime

from worker.logs import get_logger

logger = get_logger(__name__)

_DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def _format_title(inicio: str, fim: str) -> str:
    dt_i = datetime.fromisoformat(inicio)
    dt_f = datetime.fromisoformat(fim)
    dia = _DIAS[dt_i.weekday()]
    data = dt_i.strftime("%d/%m")
    return f"{dia} {data} às {dt_i.strftime('%Hh')}-{dt_f.strftime('%Hh')}"


def build_horarios_list(agendamento: dict, slots: list[dict]) -> dict:
    """Monta payload da List Message de horários (PRD §6.2). Máx 10 slots."""
    limited = slots[:10]

    rows = [
        {
            "rowId": f"SLOT:{slot['inicio']}",
            "title": _format_title(slot["inicio"], slot["fim"]),
            "description": "",
        }
        for slot in limited
    ]

    logger.debug(
        "payload.horarios_list.built",
        agendamento_id=agendamento.get("agendamento_id"),
        num_slots=len(rows),
    )

    return {
        "number": agendamento["telefone"],
        "title": "Escolha um novo horário",
        "description": "Selecione um dos horários disponíveis abaixo:",
        "buttonText": "Ver horários",
        "footerText": "DMais Logística Reversa",
        "sections": [{"title": "Horários disponíveis", "rows": rows}],
    }
