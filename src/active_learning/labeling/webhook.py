"""FastAPI webhook router for Label Studio annotation events.

Receives webhook callbacks from Label Studio when annotations are created,
updated, or deleted. In Phase B this will trigger Prefect retraining flows.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@webhook_router.post("/label-studio")
async def handle_label_studio_webhook(payload: dict[str, Any]) -> dict[str, str]:
    """Handle Label Studio annotation events.

    Label Studio sends different payload shapes depending on the action
    (e.g. ``ANNOTATION_CREATED``, ``ANNOTATION_UPDATED``). This endpoint
    logs the event and returns an acknowledgment. In Phase B, specific
    actions will trigger Prefect retraining flows.

    Args:
        payload: Raw webhook payload from Label Studio.

    Returns:
        Acknowledgment dict with status.
    """
    action = payload.get("action", "unknown")
    task_id = payload.get("task", {}).get("id") if isinstance(payload.get("task"), dict) else payload.get("task")
    project_raw = payload.get("project")
    project_id = project_raw.get("id") if isinstance(project_raw, dict) else project_raw

    logger.info(
        "Label Studio webhook received: action=%s, task_id=%s, project_id=%s",
        action,
        task_id,
        project_id,
    )

    return {"status": "received"}
