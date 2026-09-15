import hmac
import logging

from fastapi import Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def verify_n8n_webhook_secret(
    request: Request,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
) -> None:
    """Shared auth for every endpoint n8n calls back into.

    Constant-time compare against N8N_CALLBACK_SECRET, fail-closed if the
    secret isn't configured. Used by approval-callback, agent-content,
    agent-report and agent/pending so they share one trust boundary and one
    place to change it. Takes the request rather than a document id so
    collection endpoints can use it too.
    """
    if not settings.N8N_CALLBACK_SECRET or not x_webhook_secret or not hmac.compare_digest(
        x_webhook_secret, settings.N8N_CALLBACK_SECRET
    ):
        logger.warning(f"Rejected n8n webhook call for {request.url.path}: invalid webhook secret")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")
