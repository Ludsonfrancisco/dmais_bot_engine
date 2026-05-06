"""
worker.payloads.list_horarios
==============================
Montagem do payload da List Message de horários disponíveis para remarcação.

Referência: PRD.md §6.2 — List Message de horários.

Funcionalidades planejadas:
    - build_horarios_list(agendamento: dict, slots: list[dict]) -> dict
    - Limita a 10 slots máximo (limite do WhatsApp por seção).
    - rowId = "SLOT:<iso8601>" para parsing do horário escolhido.
    - Formata title legível em pt-BR: "Seg 12/05 às 09h-11h".
    - Campos dinâmicos: number do agendamento.

Payload de saída (enviado à EvolutionAPI):
    {
        "number": "55<DDD><numero>",
        "title": "Escolha um novo horário",
        "description": "Selecione um dos horários disponíveis abaixo:",
        "buttonText": "Ver horários",
        "footerText": "DMais Logística Reversa",
        "sections": [{
            "title": "Horários disponíveis",
            "rows": [
                { "rowId": "SLOT:2026-05-12T09:00:00-03:00", "title": "Seg 12/05 às 09h-11h", "description": "" }
            ]
        }]
    }
"""

# TODO: Implementar na task 10.C.16
