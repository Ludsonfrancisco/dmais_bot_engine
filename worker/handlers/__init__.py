"""
worker.handlers
===============
Subpacote com handlers de fluxo do motor de mensagens.

Cada handler é uma função assíncrona que orquestra um passo do fluxo:

Módulos:
    - enviar_inicial: Envia List Message inicial (3 opções) para agendamento pendente.
    - enviar_slots: Busca slots no Django e envia List Message de horários.
    - on_response: Processa webhook recebido da EvolutionAPI (classifica e roteia).
    - on_timeout: Trata agendamentos com timeout sinalizado pelo Django.
"""
