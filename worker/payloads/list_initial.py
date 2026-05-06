"""
worker.payloads.list_initial
=============================
Montagem do payload da List Message inicial com 3 opções.

Referência: PRD.md §6.1 — List Message inicial.

Funcionalidades planejadas:
    - build_initial_list(agendamento: dict) -> dict
    - Monta payload com 3 rows:
        - CONFIRMAR  — "Confirmar coleta" / "Mantém o horário agendado"
        - REMARCAR   — "Remarcar para outro dia" / "Escolher novo horário"
        - JA_ENTREGUE — "Já entreguei" / "Produto já foi devolvido"
    - NUNCA incluir URLs no texto (regra de negócio).
    - Campos dinâmicos: number, description (nome, data, hora do agendamento).

Payload de saída (enviado à EvolutionAPI):
    {
        "number": "55<DDD><numero>",
        "title": "Confirmação de Coleta",
        "description": "Olá {nome}! Sua coleta está agendada para {data} às {hora}...",
        "buttonText": "Selecionar opção",
        "footerText": "DMais Logística Reversa",
        "sections": [{ "title": "Opções", "rows": [...] }]
    }
"""

# TODO: Implementar na task 10.C.15
