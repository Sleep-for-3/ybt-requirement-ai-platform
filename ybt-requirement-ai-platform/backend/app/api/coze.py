from fastapi import APIRouter

from app.services.coze import CozeConnector

router = APIRouter(prefix="/coze", tags=["coze"])


@router.get("/status")
async def coze_status() -> dict:
    connector = CozeConnector()
    return await connector.run_workflow({"healthcheck": True})
