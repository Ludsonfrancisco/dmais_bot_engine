"""Format WhatsApp report messages."""


def format_morning_message() -> str:
    """Mensagem das 06:00 com cronograma do dia."""
    return (
        "☀️ *BOM DIA, TIME DMAIS!* 🚀\n"
        "\n"
        "Iniciando a nossa operação! Para garantir que todos tenham a visão"
        " clara do campo e possamos agir rápido, nosso painel de"
        " monitoramento rodará em ciclos exatos de 2 horas.\n"
        "\n"
        "🕒 *CRONOGRAMA DE ATUALIZAÇÕES:*\n"
        "06:10 | 08:10 | 10:10 | 12:10\n"
        "14:10 | 16:10 | 18:10 | 20:10\n"
        "\n"
        "📌 *O QUE ACOMPANHAREMOS HOJE:*\n"
        "\n"
        "1. Giro da Operação: Variação do ritmo de:\n"
        "▫️ Reparos (🔧)\n"
        "▫️ Ativações (⚡)\n"
        "▫️ MEs (🏠)\n"
        "▫️ Serviços (🛠️)\n"
        "\n"
        "2. Radar de Cidades: Destaques de onde estamos melhorando e"
        " alertas para foco imediato.\n"
        "\n"
        "3. Anexos Visuais: Prints do Backlog Geral, Área Dmais e"
        " Reparos Abortados.\n"
        "\n"
        "Foco na qualidade e na agilidade. Um excelente dia de trabalho e"
        " grandes resultados para todos nós! 👊"
    )


def format_cycle_report(
    hour: str,
    entrante: str,
    download: str,
    group_counts: dict,
    group_deltas: dict,
    city_deltas: dict,
    has_previous: bool,
) -> str:
    """Relatório bi-horário com variação e radar de cidades."""

    try:
        h = int(hour.split(":")[0])
        window = f"{h:02d}h"
    except (ValueError, IndexError):
        window = hour

    group_lines = _format_group_section(group_counts, group_deltas, has_previous)
    radar_lines = _format_city_radar(city_deltas, has_previous)
    footer_parts = [f"⏱️ Último entrante: {entrante}"]
    if download:
        footer_parts.append(f"Base: {download}")
    footer = " | ".join(footer_parts)

    parts = [
        f"📊 *GIRO DA OPERAÇÃO | Atualização das {window}*",
        "",
        f"📈 *VARIAÇÃO (ÚLTIMAS 2 HORAS):*",
        group_lines,
    ]
    if radar_lines:
        parts.append("")
        parts.append(radar_lines)
    parts.append("")
    parts.append(footer)
    return "\n".join(parts)


def _format_group_section(counts: dict, deltas: dict, has_previous: bool) -> str:
    groups_order = [
        ("REPARO", "🔧 Reparos"),
        ("ATIVACAO", "⚡ Instalações"),
        ("ME", "🏠 MEs"),
        ("SERVICOS", "🛠️ Serviços"),
        ("SERVIÇOS", "🛠️ Serviços"),
    ]
    seen_labels = set()
    lines = []

    for key, label in groups_order:
        if label in seen_labels:
            continue
        seen_labels.add(label)
        total = counts.get(key, 0)
        delta = deltas.get(key, 0) if has_previous else 0

        if has_previous and delta > 0:
            lines.append(f"   {label}:  {total}  (↑{delta})")
        elif has_previous and delta < 0:
            lines.append(f"   {label}:  {total}  (↓{abs(delta)})")
        else:
            lines.append(f"   {label}:  {total}  —")

    return "\n".join(lines)


def _format_city_radar(city_deltas: dict, has_previous: bool) -> str:
    if not has_previous or not city_deltas:
        return ""

    radar_groups = {"REPARO", "ATIVACAO"}
    skip_groups = {"ME", "SERVICOS", "SERVIÇOS", "CANCELAMENTO", "Cancelamento Desc. CAB.", "Moni. CCRI"}

    improvements = []   # delta < 0 (qualquer grupo)
    sales_list = []     # delta > 0, ATIVACAO
    warnings_list = []  # delta > 0, outros

    for cidade, groups in city_deltas.items():
        for grupo, delta in groups.items():
            if grupo in skip_groups:
                continue
            if grupo not in radar_groups:
                continue
            if delta < 0:
                improvements.append((abs(delta), cidade, grupo, delta))
            elif delta > 0 and grupo == "ATIVACAO":
                sales_list.append((abs(delta), cidade, delta))
            elif delta > 0:
                warnings_list.append((abs(delta), cidade, grupo, delta))

    improvements.sort(key=lambda x: -x[0])
    warnings_list.sort(key=lambda x: -x[0])
    sales_list.sort(key=lambda x: -x[0])

    lines = [f"📍 *RADAR DE CIDADES (ÚLTIMAS 2 HORAS):*"]

    if improvements:
        lines.append("")
        lines.append("✅ *Destaques (Redução de Fila):*")
        for _, cidade, grupo, delta in improvements:
            gname = _radar_group_name(grupo, delta)
            lines.append(f"▪️ {cidade}: {delta} {gname}")

    if sales_list:
        lines.append("")
        lines.append("🙌⚠️ *Novas Vendas (Atenção à Fila):*")
        for _, cidade, delta in sales_list:
            lines.append(f"▪️ {cidade}: +{delta} Instalação (Bora ativar!)")

    if warnings_list:
        lines.append("")
        lines.append("🚨 *Pontos de Risco (Aumento de Fila):*")
        for _, cidade, grupo, delta in warnings_list:
            gname = _radar_group_name(grupo, delta)
            lines.append(f"▪️ {cidade}: +{delta} {gname}")

    return "\n".join(lines)


def _radar_group_name(grupo: str, delta: int) -> str:
    """Nome do grupo no radar, sensível ao contexto (positivo/negativo)."""
    if grupo == "ATIVACAO":
        return "Instalações no backlog" if delta < 0 else "Instalação"
    if grupo == "REPARO":
        return "Reparos" if delta < 0 else "Reparo (aumentando o Backlog)"
    return grupo
