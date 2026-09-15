"""
NexusRAG API router — aggregates workspace, document, and RAG endpoints.
"""
from fastapi import APIRouter

from app.api.workspaces import router as workspaces_router
from app.api.documents import router as documents_router
from app.api.rag import router as rag_router
from app.api.config import router as config_router
from app.api.expert import router as expert_router
from app.api.stt import router as stt_router
from app.api.business import router as business_router
from app.api.business_chat import router as business_chat_router
from app.api.n8n_agent import router as n8n_agent_router

api_router = APIRouter()
api_router.include_router(workspaces_router)
api_router.include_router(documents_router)
api_router.include_router(rag_router)
api_router.include_router(config_router)
api_router.include_router(expert_router)
api_router.include_router(stt_router)
api_router.include_router(business_router)
api_router.include_router(business_chat_router)
api_router.include_router(n8n_agent_router)
