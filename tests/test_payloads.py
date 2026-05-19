import pytest
from worker.payloads.list_horarios import build_horarios_list

def test_build_horarios_list_success():
    agendamento = {"telefone": "5511999999999"}
    slots = [
        {"inicio": "2026-05-12T09:00:00-03:00", "fim": "2026-05-12T11:00:00-03:00"},
        {"inicio": "2026-05-13T14:00:00Z", "label": "Custom Label"},
        {"iso_date": "2026-05-14T10:00:00-03:00"}
    ]
    
    payload = build_horarios_list(agendamento, slots)
    
    assert payload["number"] == "5511999999999"
    assert len(payload["sections"][0]["rows"]) == 3
    
    rows = payload["sections"][0]["rows"]
    # Test format with range
    assert rows[0]["rowId"] == "SLOT:2026-05-12T09:00:00-03:00"
    assert "09h-11h" in rows[0]["title"]
    assert "Ter" in rows[0]["title"] # 2026-05-12 is Tuesday
    
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
