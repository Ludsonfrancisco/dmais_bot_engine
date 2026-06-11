from worker.evolution_client import evolution_client
from worker.reports.destinations import get_report_destinations, mask_group_jid
from worker.settings import Settings, settings

_TEST_PREFIX = "[AMBIENTE DE TESTE]"


def _text_for_destination(text: str, *, is_test: bool) -> str:
    body = text.strip()
    if is_test and not body.startswith(_TEST_PREFIX):
        return f"{_TEST_PREFIX}\n{body}"
    return body


async def send_report_text(text: str, config: Settings = settings) -> list[dict]:
    """Send a report text to the configured WhatsApp report destinations."""
    results: list[dict] = []

    for destination in get_report_destinations(config):
        body = _text_for_destination(text, is_test=destination.is_test)
        response = await evolution_client.send_group_text_message(
            destination.group_jid, body
        )
        results.append(
            {
                "target": destination.name,
                "group_jid": mask_group_jid(destination.group_jid),
                "response": response,
            }
        )

    return results
