"""
CEO chatbot endpoint. Talks to a Foundry Agent (created once in the portal)
that has a File Search tool attached over two vector stores:
  1. "project-status" docs  -> ongoing project info
  2. "people" docs          -> who's who / roles
This is the RAG layer: the agent only answers from what's in those stores
and cites the source file, it does not freelance.
"""
from fastapi import APIRouter, Depends, Form
from sqlalchemy.orm import Session
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

from ..config import settings
from ..db import get_db, ChatMessage
from ..auth import get_current_user

router = APIRouter()

_client: AIProjectClient | None = None


def get_foundry_client() -> AIProjectClient:
    global _client
    if _client is None:
        # Current (GA-era) azure-ai-projects client only needs endpoint +
        # credential. Earlier in this project we were pinned to the very
        # old 1.0.0b5 beta (Jan 2025), which (a) needed subscription_id /
        # resource_group_name / project_name as well, and (b) spoke an API
        # version the Foundry backend has since moved past, failing with
        # "(BadRequest) API version not supported". Upgrading the pinned
        # version (see requirements.txt) and dropping those extra kwargs
        # fixes both at once. Plain DefaultAzureCredential is correct here;
        # this client resolves its own token audience internally.
        _client = AIProjectClient(
            endpoint=settings.FOUNDRY_PROJECT_ENDPOINT,
            credential=DefaultAzureCredential(),
        )
    return _client


@router.post("/api/chat")
def chat(
    message: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    client = get_foundry_client()

    # One thread per message for now (simplest thing that works); the
    # current SDK nests these under .agents.threads / .agents.messages /
    # .agents.runs rather than exposing flat create_thread()-style methods.
    thread = client.agents.threads.create()

    client.agents.messages.create(thread_id=thread.id, role="user", content=message)

    run = client.agents.runs.create_and_process(
        thread_id=thread.id, agent_id=settings.FOUNDRY_CEO_AGENT_ID
    )

    reply_text = "Sorry, I couldn't get an answer just now."
    if run.status == "completed":
        messages = client.agents.messages.list(thread_id=thread.id)
        for m in messages:
            if m.role == "assistant":
                for content in m.content:
                    if content.type == "text":
                        reply_text = content.text.value
                        break
                break
    else:
        reply_text = f"Sorry, the assistant run didn't complete (status: {run.status})."

    db.add(ChatMessage(user_id=user.id, role="user", content=message))
    db.add(ChatMessage(user_id=user.id, role="assistant", content=reply_text))
    db.commit()

    return {"reply": reply_text}


@router.get("/api/chat/history")
def chat_history(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == user.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    return [{"role": r.role, "content": r.content} for r in rows]
