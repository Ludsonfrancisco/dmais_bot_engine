import re
from datetime import date, datetime, timedelta

from worker.logs import get_logger

logger = get_logger(__name__)

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

OPCOES_INICIAIS = [
    ("CONFIRMAR",   "Confirmar coleta"),
    ("REMARCAR",    "Remarcar para outro dia"),
    ("JA_ENTREGUE", "Já entreguei"),
]

def _proximos_dias_uteis(n: int = 3, data_base: date | None = None) -> list[str]:
    """Retorna os próximos *n* dias úteis (seg–sáb, excluindo domingo) a partir
    de amanhã em relação a *data_base* (default = hoje)."""
    if data_base is None:
        data_base = date.today()
    resultado: list[str] = []
    candidato = data_base + timedelta(days=1)
    while len(resultado) < n:
        if candidato.weekday() != 6:  # 6 = domingo
            resultado.append(candidato.isoformat())
        candidato += timedelta(days=1)
    return resultado

# Períodos (alinhado a Agendamento.janela_horario do dmais_portal: MANHA/TARDE/NOITE)
PERIODOS = [
    ("MANHA", "Manhã (08:00 às 12:00)"),
    ("TARDE", "Tarde (12:00 às 18:00)"),
]

_DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]

# Mensagem para opção 3 (Já entreguei) — pergunta de texto livre
MSG_JA_ENTREGUE_PERGUNTA = (
    "Obrigado pela informação! 🙏\n\n"
    "Para concluirmos, pode nos contar **onde**, **a quem** e **quando** "
    "você entregou o equipamento? Pode responder em uma única mensagem."
)


def _reject_url(value: str, field: str) -> None:
    if _URL_RE.search(value):
        raise ValueError(f"campo '{field}' contém URL — proibido pelas regras de negócio")


def _format_data_curta(data_str: str) -> str:
    """YYYY-MM-DD → DD/MM. Se não bater, retorna a string original."""
    try:
        return date.fromisoformat(data_str).strftime("%d/%m")
    except (ValueError, TypeError):
        return data_str


def _format_data_humana(data_str: str) -> str:
    """YYYY-MM-DD → 'Terça, 19/05'. Se não bater, retorna a string original."""
    try:
        d = date.fromisoformat(data_str)
        return f"{_DIAS_SEMANA[d.weekday()]}, {d.strftime('%d/%m')}"
    except (ValueError, TypeError):
        return data_str


def build_initial_text(agendamento: dict) -> tuple[str, str]:
    """Mensagem inicial (estilo AT3) com 3 opções: Confirmar / Remarcar / Já entreguei."""
    nome = agendamento["nome"]
    telefone = agendamento["telefone"]
    data = agendamento["data"]
    _reject_url(nome, "nome")
    _reject_url(str(data), "data")

    data_curta = _format_data_curta(data)

    linhas = [
        f"Olá {nome}! Tudo bem?",
        "",
        "Aqui é da AT3 Internet. Gostaríamos de agendar a visita do técnico "
        f"para realizar a coleta do equipamento agendada para {data_curta}.",
        "",
        "Responda com o número da opção:",
    ]
    for idx, (_id, titulo) in enumerate(OPCOES_INICIAIS, start=1):
        linhas.append(f"{idx} — {titulo}")

    texto = "\n".join(linhas)

    logger.debug("payload.initial_text.built", agendamento_id=agendamento.get("agendamento_id"))
    return telefone, texto


def build_periodo_text(data_str: str) -> str:
    """Menu de período para uma data específica. Retorna apenas o texto."""
    data_humana = _format_data_humana(data_str)
    linhas = [
        f"Ótimo! Para {data_humana}, qual período seria melhor para a coleta?",
        "",
        "Responda com o número da opção:",
    ]
    for idx, (_id, titulo) in enumerate(PERIODOS, start=1):
        linhas.append(f"{idx} — {titulo}")
    return "\n".join(linhas)


def build_datas_remarcar_text(n_dias: int = 3, data_base: date | None = None) -> tuple[str, dict[str, str]]:
    """Menu de datas para remarcação (dinâmico). Retorna (texto, mapping idx→ISO date).

    *data_base* controla a data de referência (default = hoje).  Parâmetros
    expostos apenas para testabilidade; na chamada normal não é passado nenhum
    argumento.
    """
    datas = _proximos_dias_uteis(n=n_dias, data_base=data_base)
    linhas = [
        "Sem problemas! Escolha uma nova data para a coleta:",
        "",
        "Responda com o número da opção:",
    ]
    mapping: dict[str, str] = {}
    for idx, data_iso in enumerate(datas, start=1):
        linhas.append(f"{idx} — {_format_data_humana(data_iso)}")
        mapping[str(idx)] = data_iso
    return "\n".join(linhas), mapping


def slot_iso_de(data_str: str, periodo: str) -> str:
    """Combina data (YYYY-MM-DD) + periodo (MANHA/TARDE) em ISO 8601 com offset -03:00."""
    hora = {"MANHA": 8, "TARDE": 12}.get(periodo, 8)
    try:
        dt = datetime.fromisoformat(data_str).replace(hour=hora, minute=0, second=0)
    except ValueError:
        # data_str já é ISO completo? tenta direto
        try:
            dt = datetime.fromisoformat(data_str).replace(hour=hora, minute=0, second=0)
        except ValueError:
            return f"{data_str}T{hora:02d}:00:00-03:00"
    return dt.strftime("%Y-%m-%dT%H:%M:%S-03:00")
