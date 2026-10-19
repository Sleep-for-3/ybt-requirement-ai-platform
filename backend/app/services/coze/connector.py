from typing import Any

from app.core.settings import get_settings


class CozeConnector:
    """Optional Coze Studio workflow connector.

    Coze Studio is a workflow orchestrator only. The platform remains the system
    of record for projects, knowledge chunks, SQL parse results, drafts, and evidence.
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    async def run_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.coze_enabled:
            return {
                "enabled": False,
                "message": "Coze Studio 集成在本次 MVP 中未启用。",
                "payload_keys": sorted(payload.keys()),
            }
        return {
            "enabled": True,
            "message": "Coze Studio 的 HTTP 集成将在后续阶段提供。",
            "workflow_id": self.settings.coze_workflow_id,
        }
