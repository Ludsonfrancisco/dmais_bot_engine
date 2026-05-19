from datetime import datetime

from worker.logs import get_logger

logger = get_logger(__name__)

_DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
MAX_SLOTS = 10


def _format_title(inicio: str, fim: str) -> str:
    dt_i = datetime.fromisoformat(inicio)
    dt_f = datetime.fromisoformat(fim)
    dia = _DIAS[dt_i.weekday()]
    data = dt_i.strftime("%d/%m")
    return f"{dia} {data} às {dt_i.strftime('%Hh')}-{dt_f.strftime('%Hh')}"


def build_horarios_text(agendamento: dict, slots: list[dict]) -> tuple[str, str, dict[str, str]]:
    """Monta texto da mensagem de horários numerados (até 10).

    Retorna (telefone, texto, mapping) onde mapping = {"1": "<iso>", "2": "<iso>", ...}
    para o handler resolver depois qual slot o usuário escolheu.
    """
    limited = slots[:MAX_SLOTS]

    linhas = ["Escolha um dos horários disponíveis respondendo com o número:"]
    mapping: dict[str, str] = {}
    for idx, slot in enumerate(limited, start=1):
        linhas.append(f"{idx} — {_format_title(slot['inicio'], slot['fim'])}")
        mapping[str(idx)] = slot["inicio"]

    texto = "\n".join(linhas)
    telefone = agendamento["telefone"]

    logger.debug(
        "payload.horarios_text.built",
        agendamento_id=agendamento.get("agendamento_id"),
        num_slots=len(mapping),
    )
    return telefone, texto, mapping
