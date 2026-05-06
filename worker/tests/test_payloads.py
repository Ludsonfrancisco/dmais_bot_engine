from worker.payloads.list_horarios import build_horarios_list
from worker.payloads.list_initial import build_initial_list

_AGENDAMENTO = {
    "agendamento_id": 1,
    "nome": "Fulano",
    "telefone": "5511999998888",
    "data": "2026-05-08",
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


def test_build_initial_list_has_three_rows():
    payload = build_initial_list(_AGENDAMENTO)
    rows = payload["sections"][0]["rows"]
    assert len(rows) == 3
    assert {r["rowId"] for r in rows} == {"CONFIRMAR", "REMARCAR", "JA_ENTREGUE"}


def test_build_initial_list_no_url():
    payload = build_initial_list(_AGENDAMENTO)
    fields_to_check = [
        payload.get("title", ""),
        payload.get("description", ""),
        payload.get("footerText", ""),
    ]
    for row in payload["sections"][0]["rows"]:
        fields_to_check += [row.get("title", ""), row.get("description", "")]

    for field in fields_to_check:
        assert "http" not in field.lower(), f"URL encontrada em: {field!r}"


def test_build_horarios_list_limits_to_ten():
    payload = build_horarios_list(_AGENDAMENTO, _12_SLOTS)
    rows = payload["sections"][0]["rows"]
    assert len(rows) == 10


def test_build_horarios_list_row_id_starts_with_slot():
    payload = build_horarios_list(_AGENDAMENTO, _12_SLOTS[:5])
    for row in payload["sections"][0]["rows"]:
        assert row["rowId"].startswith("SLOT:")


def test_build_horarios_list_title_pt_br():
    # 2026-05-11 is Monday → "Seg"
    slots = [
        {
            "slot_id": 1,
            "inicio": "2026-05-11T09:00:00-03:00",
            "fim": "2026-05-11T11:00:00-03:00",
        }
    ]
    payload = build_horarios_list(_AGENDAMENTO, slots)
    title = payload["sections"][0]["rows"][0]["title"]
    assert "Seg" in title
    assert "11/05" in title
    assert "09h" in title
    assert "11h" in title
