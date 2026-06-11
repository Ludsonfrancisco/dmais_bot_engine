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
    window = f"{h:02d}h"

    group_lines = _format_group_section(group_counts, group_deltas, has_previous)
    radar_lines = _format_city_radar(city_deltas, has_previous)
    footer_parts = [f"🕐 Entrante {entrante}"]
    if download:
        footer_parts.append(f"Base {download}")
    footer = "  ·  ".join(footer_parts)

    parts = [
        f"📊 *GIRO DA OPERAÇÃO*",
        f"_{window}_",
        "",
        group_lines,
    ]
    if radar_lines:
        parts.append("")
        parts.append(radar_lines)
    parts.append("")
    parts.append(f"_{footer}_")
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
            lines.append(f"    {label}  {total}  ↑{delta}")
        elif has_previous and delta < 0:
            lines.append(f"    {label}  {total}  ↓{abs(delta)}")
        else:
            lines.append(f"    {label}  {total}  —")

    return "\n".join(lines)


def _format_city_radar(city_deltas: dict, has_previous: bool) -> str:
    if not has_previous or not city_deltas:
        return ""

    priority_groups = {"REPARO": 2, "ATIVACAO": 2}
    skip_groups = {"ME", "SERVICOS", "SERVIÇOS", "CANCELAMENTO", "Cancelamento Desc. CAB.", "Moni. CCRI"}
    improvements = []
    ativacao_ritmo = []  # Ativação caindo = executando bem
    warnings_list = []
    sales_list = []

    for cidade, groups in city_deltas.items():
        for grupo, delta in groups.items():
            if grupo in skip_groups:
                continue
            weight = priority_groups.get(grupo, 1)
            if delta < 0 and grupo == "ATIVACAO":
                ativacao_ritmo.append((abs(delta) * weight, cidade, delta))
            elif delta < 0:
                improvements.append((abs(delta) * weight, cidade, grupo, delta))
            elif delta > 0 and grupo == "ATIVACAO":
                sales_list.append((abs(delta) * weight, cidade, delta))
            elif delta > 0:
                warnings_list.append((abs(delta) * weight, cidade, grupo, delta))

    improvements.sort(key=lambda x: -x[0])
    ativacao_ritmo.sort(key=lambda x: -x[0])
    warnings_list.sort(key=lambda x: -x[0])
    sales_list.sort(key=lambda x: -x[0])

    lines = []

    if improvements:
        _, cidade, grupo, delta = improvements[0]
        gname = _group_name(grupo)
        lines.append(f"✅ {cidade}: {abs(delta)} {gname} a menos")

    if ativacao_ritmo:
        _, cidade, delta = ativacao_ritmo[0]
        lines.append(f"⚡ {cidade}: -{abs(delta)} instalações, no caminho certo ✅")

    if sales_list:
        _, cidade, delta = sales_list[0]
        lines.append(f"🙌 {cidade} vendeu +{delta} instalações ⚠️")

    if warnings_list:
        _, cidade, grupo, delta = warnings_list[0]
        gname = _group_name(grupo)
        lines.append(f"⚠️ {cidade}: +{delta} {gname}")

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
