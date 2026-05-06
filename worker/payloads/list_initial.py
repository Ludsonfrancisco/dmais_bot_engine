import re

from worker.logs import get_logger

logger = get_logger(__name__)

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

_ROWS = [
    {"rowId": "CONFIRMAR",   "title": "Confirmar coleta",        "description": "Mantém o horário agendado"},
    {"rowId": "REMARCAR",    "title": "Remarcar para outro dia", "description": "Escolher novo horário"},
    {"rowId": "JA_ENTREGUE", "title": "Já entreguei",            "description": "Produto já foi devolvido"},
]


def _reject_url(value: str, field: str) -> None:
    if _URL_RE.search(value):
        raise ValueError(f"campo '{field}' contém URL — proibido pelas regras de negócio")


def build_initial_list(agendamento: dict) -> dict:
    """Monta payload da List Message inicial (PRD §6.1)."""
    nome = agendamento["nome"]
    telefone = agendamento["telefone"]
    data = agendamento["data"]
    hora = agendamento["hora"]

    for value, field in ((nome, "nome"), (data, "data"), (hora, "hora")):
        _reject_url(value, field)

    description = f"Olá {nome}! Sua coleta está agendada para {data} às {hora}. O que deseja fazer?"

    logger.debug("payload.initial_list.built", agendamento_id=agendamento.get("agendamento_id"))

    return {
        "number": telefone,
        "title": "Confirmação de Coleta",
        "description": description,
        "buttonText": "Selecionar opção",
        "footerText": "DMais Logística Reversa",
        "sections": [{"title": "Opções", "rows": _ROWS}],
    }
