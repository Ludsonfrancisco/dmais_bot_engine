# Fluxo de Conversa — dmais_bot_engine

Documento da máquina de estados e fluxos conversacionais do bot AT3 Internet.

---

## Visão geral

A conversa entre bot e cliente é uma **máquina de estados finita** armazenada em Redis (`state:<telefone>`). Cada mensagem do cliente avança um estado; respostas inválidas são contadas (até 3 antes de virar FALHA).

```
                          [ enviar_inicial ]
                                  │
                          send AT3 message
                          ↓
                  ┌── AGUARDANDO_INICIAL ──┐
                  │                        │
            ┌─────┼──────────────┬─────────┼──────────┐
            │"1"  │ "confirmar"  │"2"      │"3"       │
            │     │              │ "remarcar"│ "entreguei"
            ▼     ▼              ▼         ▼          │
   AGUARDANDO_PERIODO     AGUARDANDO_DATA_REMARCAR    │
   ctx: {data}            ctx: {mapping idx→ISO}      │
            │                    │                    │
            │ "1"/"2"             │ "1".."3" (data)   │
            │ MANHA/TARDE         ▼                   │
            │              AGUARDANDO_PERIODO_REMARCAR│
            │              ctx: {data picked}         │
            │                    │                    │
            │                    │ "1"/"2"            │
            │                    │ MANHA/TARDE        ▼
            ▼                    ▼          AGUARDANDO_TEXTO_ENTREGUE
   POST /whatsapp-webhook  POST /whatsapp-webhook     │
   tipo=CONFIRMAR          tipo=REMARCAR              │ (qualquer texto)
   slot=<ISO>              slot=<ISO>                 │
            │                    │                    ▼
            │                    │           POST /whatsapp-webhook
            │                    │           tipo=JA_ENTREGUE
            │                    │           raw=<texto livre>
            │                    │                    │
            ▼                    ▼                    ▼
       Reply AT3            Reply AT3            Reply AT3
   "Coleta confirmada"   "Coleta remarcada"  "Agradece informação"
       (encerra)             (encerra)             (encerra)
```

---

## Mensagens trocadas (exemplos)

### Mensagem inicial enviada pelo bot

```
Olá {nome}! Tudo bem?

Aqui é da AT3 Internet. Gostaríamos de agendar a visita do técnico
para realizar a coleta do equipamento agendada para {DD/MM}.

Responda com o número da opção:
1 — Confirmar coleta
2 — Remarcar para outro dia
3 — Já entreguei
```

> Se `data_agendada` estiver no passado, o bot substitui por **amanhã** automaticamente (handle de planilhas desatualizadas).

### Após "1" (Confirmar) — pergunta de período

```
Ótimo! Para Terça, 19/05, qual período seria melhor para a coleta?

Responda com o número da opção:
1 — Manhã (08:00 às 12:00)
2 — Tarde (12:00 às 18:00)
```

### Após "2" (Remarcar) — lista de datas

```
Sem problemas! Escolha uma nova data para a coleta:

Responda com o número da opção:
1 — Terça, 19/05
2 — Quarta, 20/05
3 — Quinta, 21/05
```

### Após "3" (Já entreguei) — pergunta de texto livre

```
Obrigado pela informação! 🙏

Para concluirmos, pode nos contar **onde**, **a quem** e **quando**
você entregou o equipamento? Pode responder em uma única mensagem.
```

### Reply final — CONFIRMAR

```
✅ A AT3 Internet agradece a sua confirmação!

Nosso técnico passará no dia *Terça, 19/05* no período da *manhã*
para realizar a coleta do equipamento.

Caso precise alterar, é só nos avisar. Tenha um ótimo dia! 🙌
```

### Reply final — REMARCAR

```
✅ A AT3 Internet agradece!

Sua coleta foi remarcada com sucesso. Nosso técnico passará no dia
*Quarta, 20/05* no período da *tarde*.

Caso precise alterar novamente, é só nos avisar. Tenha um ótimo dia! 🙌
```

### Reply final — JA_ENTREGUE

```
🙏 A AT3 Internet agradece a informação!

Vamos atualizar nosso sistema com os dados que você nos passou.
Tenha um ótimo dia! 🙌
```

### Fallback (resposta inválida) — UMA mensagem unificada

```
Desculpe, não entendi sua resposta. 🙏

Olá {nome}! Tudo bem?

Aqui é da AT3 Internet. Gostaríamos de agendar a visita do técnico...

Responda com o número da opção:
1 — Confirmar coleta
2 — Remarcar para outro dia
3 — Já entreguei
```

Após **3 respostas inválidas seguidas**, o bot:
- Posta `tipo=FALHA` para o Django (move kanban para FALHA)
- Limpa o estado da conversa
- Para de responder

---

## Tabela de transições

| Estado atual              | Entrada do cliente            | Próximo estado                   | Ação                                  |
|---------------------------|-------------------------------|----------------------------------|---------------------------------------|
| (nenhum / inicial)        | bot envia primeiro            | `AGUARDANDO_INICIAL`             | Envia menu AT3                        |
| `AGUARDANDO_INICIAL`      | "1" ou "confirmar/confirmo/sim" | `AGUARDANDO_PERIODO`           | Envia menu de período                 |
| `AGUARDANDO_INICIAL`      | "2" ou "remarcar/remarca/trocar" | `AGUARDANDO_DATA_REMARCAR`    | Envia lista de datas                  |
| `AGUARDANDO_INICIAL`      | "3" ou "entreguei/ja entreguei" | `AGUARDANDO_TEXTO_ENTREGUE`    | Pergunta texto livre                  |
| `AGUARDANDO_INICIAL`      | qualquer outro                | `AGUARDANDO_INICIAL` (mantém)    | Fallback unificado + errors++         |
| `AGUARDANDO_PERIODO`      | "1" ou "manha/manhã"          | (limpa)                          | Webhook CONFIRMAR + slot 08:00 + reply|
| `AGUARDANDO_PERIODO`      | "2" ou "tarde"                | (limpa)                          | Webhook CONFIRMAR + slot 12:00 + reply|
| `AGUARDANDO_PERIODO`      | qualquer outro                | mantém                           | Fallback + errors++                   |
| `AGUARDANDO_DATA_REMARCAR`| "1".."3"                      | `AGUARDANDO_PERIODO_REMARCAR`    | Guarda data + envia menu período      |
| `AGUARDANDO_DATA_REMARCAR`| qualquer outro                | mantém                           | Fallback + errors++                   |
| `AGUARDANDO_PERIODO_REMARCAR` | "1"/"manha"               | (limpa)                          | Webhook REMARCAR + slot + reply       |
| `AGUARDANDO_PERIODO_REMARCAR` | "2"/"tarde"               | (limpa)                          | Webhook REMARCAR + slot + reply       |
| `AGUARDANDO_TEXTO_ENTREGUE`| qualquer texto não vazio     | (limpa)                          | Webhook JA_ENTREGUE + raw=texto + reply|
| (qualquer estado)         | 3 inválidas seguidas          | (limpa)                          | Webhook FALHA, bot para de responder  |

---

## Mapeamento ao kanban Django

| Bot → Django webhook `tipo` | Django status anterior | Django status novo |
|---|---|---|
| (worker envia inicial, PATCH status) | `PENDENTE_CONTATO` | `AGUARDANDO_CLIENTE` (+`tentativas++`) |
| `CONFIRMAR`                  | `AGUARDANDO_CLIENTE`   | `CONFIRMADO`       |
| `REMARCAR` (+ slot)          | `AGUARDANDO_CLIENTE`   | `REMARCADO` (+ atualiza `data_agendada` e `janela_horario`) |
| `JA_ENTREGUE`                | `AGUARDANDO_CLIENTE`   | `JA_ENTREGUE`      |
| `FALHA` (3 inválidas ou timeout) | `AGUARDANDO_CLIENTE` | `FALHA`            |
| `RESPOSTA_INVALIDA`          | (sem transição)        | só audit log       |

A transição **PENDENTE_CONTATO → AGUARDANDO_CLIENTE** acontece **quando o webhook handler recebe a primeira resposta válida**, ou imediatamente pelo PATCH do worker após enviar a mensagem inicial (incrementa `tentativas_envio` também).

---

## Proteções e edge cases

| Cenário | Como o bot lida |
|---|---|
| Cliente manda 3 msgs em rajada | `asyncio.Lock` por chat_id serializa o processamento (1 por vez) |
| Webhook duplicado da Evolution | `is_duplicate_event(event_id)` em Redis (SET NX EX 24h) |
| Número não existe no WhatsApp | `check_exists()` pré-flight: pula, posta FALHA, `mark_sent` |
| Data do agendamento no passado | `_adapt()` substitui por `today + 1` automaticamente |
| Mensagem de grupo / newsletter | Filtra `@g.us`/`@newsletter`/`@broadcast` antes de processar |
| WhatsApp anonimiza JID (`@lid`) | `_chat_id()` usa `remoteJidAlt` como fallback |
| Cliente manda saudação ("Olá", "Bom dia") | Trata como inválida → fallback unificado (fallback+menu em 1 msg) |
| Django offline (webhook falha) | `_post_webhook_safe` absorve erro; reply ao cliente continua |
| Worker reinicia | Estado persistido em Redis (TTL 24h) — retoma de onde parou |
| Polling repete envio | `was_sent(agendamento_id)` em Redis impede dispatch duplicado |

---

## Rate limit e jitter

- **`MAX_MESSAGES_PER_MINUTE=4`** (anti-bloqueio WhatsApp para contas não-business).
- Token bucket em Redis (`ratelimit:bucket`) — refill 4 tokens/min.
- **Jitter aleatório** entre dispatches no polling: `random.uniform(8, 22)` segundos — evita padrão fixo de 15s que dispara anti-spam da Meta.
- Jitter **não é aplicado em `skip`** (was_sent=True) — agendamentos já enviados são pulados instantaneamente.

---

## Referências de código

- Estados e classificadores: [`worker/handlers/on_response.py`](worker/handlers/on_response.py)
- Templates de texto: [`worker/payloads/list_initial.py`](worker/payloads/list_initial.py)
- Envio inicial + transição Django: [`worker/handlers/enviar_inicial.py`](worker/handlers/enviar_inicial.py)
- Adapter Django→worker + jitter: [`worker/main.py`](worker/main.py) `_adapt()` e `_poll_loop()`
- Webhook handler Django: [`../dmais_portal/logistica_reversa/api/views.py`](../dmais_portal/logistica_reversa/api/views.py) `WhatsAppWebhookView`
- State machine Django: [`../dmais_portal/logistica_reversa/state_machine.py`](../dmais_portal/logistica_reversa/state_machine.py)
