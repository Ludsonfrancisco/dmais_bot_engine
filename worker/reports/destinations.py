from dataclasses import dataclass

from worker.settings import Settings, settings


@dataclass(frozen=True)
class ReportDestination:
    name: str
    group_jid: str

    @property
    def is_test(self) -> bool:
        return self.name == "test"


def parse_report_targets(raw_targets: str) -> list[str]:
    """Normalize REPORT_TARGETS preserving order and rejecting invalid values."""
    targets = [part.strip().lower() for part in raw_targets.split(",") if part.strip()]
    allowed = {"test", "production"}
    if not targets:
        raise ValueError(
            "REPORT_TARGETS must include at least one target: test or production"
        )

    invalid = sorted(set(targets) - allowed)
    if invalid:
        raise ValueError(f"Invalid REPORT_TARGETS value(s): {', '.join(invalid)}")

    return list(dict.fromkeys(targets))


def mask_group_jid(group_jid: str) -> str:
    """Mask a WhatsApp group JID for logs/API responses."""
    if "@" not in group_jid:
        return "***"
    local, domain = group_jid.split("@", 1)
    if len(local) <= 6:
        masked = "***"
    else:
        masked = f"{local[:4]}***{local[-2:]}"
    return f"{masked}@{domain}"


def get_report_destinations(config: Settings = settings) -> list[ReportDestination]:
    """Resolve report destinations from settings.

    This is intentionally strict: if REPORT_TARGETS asks for a target but its
    group JID is missing, fail before sending anything. Sprint 1 starts with
    REPORT_TARGETS=test so production cannot receive test messages by accident.
    """
    destinations: list[ReportDestination] = []

    for target in parse_report_targets(config.REPORT_TARGETS):
        if target == "test":
            group_jid = config.WHATSAPP_TEST_GROUP_JID.strip()
            if not group_jid:
                raise ValueError(
                    "WHATSAPP_TEST_GROUP_JID is required when REPORT_TARGETS includes test"
                )
        else:
            group_jid = config.WHATSAPP_REPORT_GROUP_JID.strip()
            if not group_jid:
                raise ValueError(
                    "WHATSAPP_REPORT_GROUP_JID is required when REPORT_TARGETS includes production"
                )

        if not group_jid.endswith("@g.us"):
            raise ValueError(
                f"{target} destination must be a WhatsApp group JID ending with @g.us"
            )

        destinations.append(ReportDestination(name=target, group_jid=group_jid))

    return destinations
