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

    h = int(hour.split(":")[0])
    next_h = h + 2
    window = f"{h:02d}h às {next_h:02d}h"

    group_lines = _format_group_section(group_counts, group_deltas, has_previous)
    radar_lines = _format_city_radar(city_deltas, has_previous)

    return (
        f"📊 *GIRO DA OPERAÇÃO | {window}*\n"
        f"\n"
        f"{group_lines}"
        f"\n\n"
        f"{radar_lines}"
        f"\n\n"
        f"⏱️ Último entrante: {entrante} | Base: {download}\n"
        f"📎 Anexos: Backlog Geral, Área Dmais e Reparos Abortados"
    )


def _format_group_section(counts: dict, deltas: dict, has_previous: bool) -> str:
    # Order: Reparo, Ativação, ME, Serviços
    groups_order = [
        ("REPARO", "🔧 Reparo:"),
        ("ATIVACAO", "⚡ Ativação:"),
        ("ME", "🏠 ME:"),
        ("SERVICOS", "🛠️ Serviços:"),
        ("SERVIÇOS", "🛠️ Serviços:"),
    ]
    seen = set()

    if not has_previous:
        lines = ["📈 *CENÁRIO GERAL (CONTAGEM ATUAL):*"]
        for key, label in groups_order:
            if key in seen:
                continue
            seen.add(key)
            total = counts.get(key, 0)
            lines.append(f"      {label} {total}")
        return "\n".join(lines)

    lines = ["📈 *CENÁRIO GERAL (VARIAÇÃO ÚLTIMAS 2H):*"]
    for key, label in groups_order:
        if key in seen:
            continue
        seen.add(key)
        total = counts.get(key, 0)
        delta = deltas.get(key, 0)
        if delta > 0:
            lines.append(f"      {label} {total} (+{delta})")
        elif delta < 0:
            lines.append(f"      {label} {total} ({delta})")
        elif total > 0:
            lines.append(f"      {label} {total}")
    return "\n".join(lines)


def _format_city_radar(city_deltas: dict, has_previous: bool) -> str:
    if not has_previous or not city_deltas:
        return ""

    priority_groups = {"REPARO": 2, "ATIVACAO": 2}
    improvements = []
    warnings_list = []

    for cidade, groups in city_deltas.items():
        for grupo, delta in groups.items():
            weight = priority_groups.get(grupo, 1)
            if delta < 0 and grupo == "REPARO":
                improvements.append((abs(delta) * weight, cidade, grupo, delta))
            elif delta > 0 and grupo == "ATIVACAO":
                improvements.append((abs(delta) * weight, cidade, grupo, delta))
            elif delta > 0 and grupo == "REPARO":
                warnings_list.append((abs(delta) * weight, cidade, grupo, delta))
            elif delta < 0 and grupo == "ATIVACAO":
                warnings_list.append((abs(delta) * weight, cidade, grupo, delta))
            elif delta > 0:
                warnings_list.append((abs(delta) * weight, cidade, grupo, delta))
            elif delta < 0:
                improvements.append((abs(delta) * weight, cidade, grupo, delta))

    improvements.sort(key=lambda x: -x[0])
    warnings_list.sort(key=lambda x: -x[0])

    lines = ["📍 *RADAR DE CIDADES (ÚLTIMAS 2H):*"]

    if improvements:
        _, cidade, grupo, delta = improvements[0]
        gname = _group_name(grupo)
        if delta < 0:
            lines.append(f"✅ Destaque: {cidade} ({abs(delta)} {gname} no Backlog)")
        else:
            lines.append(f"✅ Destaque: {cidade} (+{delta} {gname} concluídas)")

    if warnings_list:
        _, cidade, grupo, delta = warnings_list[0]
        gname = _group_name(grupo)
        if delta > 0:
            lines.append(f"⚠️ Atenção: {cidade} (+{delta} {gname} pendentes)")
        else:
            lines.append(f"⚠️ Atenção: {cidade} (Queda no ritmo de {gname})")

    return "\n".join(lines)


def _group_name(key: str) -> str:
    mapping = {
        "REPARO": "Reparos",
        "ATIVACAO": "Ativações",
        "ME": "ME",
        "SERVICOS": "Serviços",
        "SERVIÇOS": "Serviços",
    }
    return mapping.get(key, key)
