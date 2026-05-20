import pytest
from datetime import date

from worker.payloads.list_horarios import build_horarios_list, build_horarios_text
from worker.payloads.list_initial import (
    _proximos_dias_uteis,
    build_datas_remarcar_text,
    build_initial_text,
    build_periodo_text,
    slot_iso_de,
)

_AGENDAMENTO = {
    "agendamento_id": 1,
    "nome": "Fulano",
    "telefone": "5511999998888",
    "data": "2026-05-19",
    "hora": "14:00",
}

_12_SLOTS = [
    {
        "slot_id": i,
        "inicio": f"2026-05-{10 + i:02d}T09:00:00-03:00",
        "fim": f"2026-05-{10 + i:02d}T11:00:00-03:00",
    }
    for i in range(1, 13)
]


# ─────────────────────────────────────────────────────────────
# build_initial_text — 3 opções com branding AT3
# ─────────────────────────────────────────────────────────────

def test_initial_text_has_at3_branding_and_3_options():
    telefone, texto = build_initial_text(_AGENDAMENTO)
    assert telefone == "5511999998888"
    assert "AT3 Internet" in texto
    assert "1 — Confirmar coleta" in texto
    assert "2 — Remarcar para outro dia" in texto
    assert "3 — Já entreguei" in texto


def test_initial_text_includes_nome_e_data_formatada():
    _, texto = build_initial_text(_AGENDAMENTO)
    assert "Fulano" in texto
    assert "19/05" in texto


def test_initial_text_rejects_url_in_nome():
    bad = {**_AGENDAMENTO, "nome": "Fulano http://evil.com"}
    with pytest.raises(ValueError, match="URL"):
        build_initial_text(bad)


def test_initial_text_no_url_in_output():
    _, texto = build_initial_text(_AGENDAMENTO)
    assert "http" not in texto.lower()


# ─────────────────────────────────────────────────────────────
# build_periodo_text — pergunta de manhã/tarde
# ─────────────────────────────────────────────────────────────

def test_periodo_text_lists_manha_tarde_para_data():
    texto = build_periodo_text("2026-05-19")
    assert "Terça, 19/05" in texto
    assert "1 — Manhã" in texto
    assert "2 — Tarde" in texto
    assert "08:00" in texto and "12:00" in texto and "18:00" in texto


# ─────────────────────────────────────────────────────────────
# _proximos_dias_uteis — geração dinâmica de dias úteis
# ─────────────────────────────────────────────────────────────

def test_proximos_dias_uteis_retorna_3_por_default():
    datas = _proximos_dias_uteis(data_base=date(2026, 5, 18))  # segunda
    assert len(datas) == 3
    assert datas[0] == "2026-05-19"  # terça
    assert datas[1] == "2026-05-20"  # quarta
    assert datas[2] == "2026-05-21"  # quinta


def test_proximos_dias_uteis_pula_domingo():
    # Sexta 2026-05-22 → próximos 2 úteis: sáb 23, seg 25 (domingo 24 pulado)
    datas = _proximos_dias_uteis(n=2, data_base=date(2026, 5, 22))
    assert datas == ["2026-05-23", "2026-05-25"]


def test_proximos_dias_uteis_n_customizavel():
    datas = _proximos_dias_uteis(n=5, data_base=date(2026, 5, 18))
    assert len(datas) == 5


# ─────────────────────────────────────────────────────────────
# build_datas_remarcar_text — datas dinâmicas
# ─────────────────────────────────────────────────────────────

def test_datas_remarcar_returns_3_dates_and_mapping():
    texto, mapping = build_datas_remarcar_text(data_base=date(2026, 5, 18))
    assert len(mapping) == 3
    assert set(mapping.keys()) == {"1", "2", "3"}
    assert mapping["1"] == "2026-05-19"
    assert mapping["2"] == "2026-05-20"
    assert mapping["3"] == "2026-05-21"
    assert "Terça, 19/05" in texto
    assert "Quarta, 20/05" in texto


# ─────────────────────────────────────────────────────────────
# slot_iso_de — converte data + período em ISO 8601
# ─────────────────────────────────────────────────────────────

def test_slot_iso_de_manha_retorna_08h():
    assert slot_iso_de("2026-05-19", "MANHA") == "2026-05-19T08:00:00-03:00"


def test_slot_iso_de_tarde_retorna_12h():
    assert slot_iso_de("2026-05-19", "TARDE") == "2026-05-19T12:00:00-03:00"


# ─────────────────────────────────────────────────────────────
# build_horarios_text — usado em fluxo legado (preservado)
# ─────────────────────────────────────────────────────────────

def test_build_horarios_text_limits_to_ten():
    _, _, mapping = build_horarios_text(_AGENDAMENTO, _12_SLOTS)
    assert len(mapping) == 10


def test_build_horarios_text_mapping_resolves_to_iso():
    _, _, mapping = build_horarios_text(_AGENDAMENTO, _12_SLOTS[:3])
    assert mapping["1"] == "2026-05-11T09:00:00-03:00"


def test_build_horarios_text_title_pt_br():
    slots = [{"slot_id": 1, "inicio": "2026-05-11T09:00:00-03:00", "fim": "2026-05-11T11:00:00-03:00"}]
    _, texto, _ = build_horarios_text(_AGENDAMENTO, slots)
    assert "Seg" in texto and "11/05" in texto


# ─────────────────────────────────────────────────────────────
# build_horarios_list — Evolution list message payload
# ─────────────────────────────────────────────────────────────

def test_build_horarios_list_success():
    agendamento = {"telefone": "5511999999999"}
    slots = [
        {"inicio": "2026-05-12T09:00:00-03:00", "fim": "2026-05-12T11:00:00-03:00"},
        {"inicio": "2026-05-13T14:00:00Z", "label": "Custom Label"},
        {"iso_date": "2026-05-14T10:00:00-03:00"},
    ]

    payload = build_horarios_list(agendamento, slots)

    assert payload["number"] == "5511999999999"
    assert len(payload["sections"][0]["rows"]) == 3

    rows = payload["sections"][0]["rows"]
    # Test format with range
    assert rows[0]["rowId"] == "SLOT:2026-05-12T09:00:00-03:00"
    assert "09h-11h" in rows[0]["title"]
    assert "Ter" in rows[0]["title"]  # 2026-05-12 is Tuesday

    # Test custom label
    assert rows[1]["title"] == "Custom Label"
    assert rows[1]["rowId"] == "SLOT:2026-05-13T14:00:00Z"

    # Test single time
    assert rows[2]["rowId"] == "SLOT:2026-05-14T10:00:00-03:00"
    assert "10h" in rows[2]["title"]


def test_build_horarios_list_limit_10():
    agendamento = {"telefone": "5511999999999"}
    slots = [{"inicio": f"2026-05-12T{i:02d}:00:00-03:00"} for i in range(15)]

    payload = build_horarios_list(agendamento, slots)
    assert len(payload["sections"][0]["rows"]) == 10


def test_build_horarios_list_missing_telefone():
    with pytest.raises(ValueError, match="telefone"):
        build_horarios_list({}, [])


def test_build_horarios_list_empty_slots():
    agendamento = {"telefone": "5511999999999"}
    payload = build_horarios_list(agendamento, [])
    assert payload["sections"][0]["rows"] == []