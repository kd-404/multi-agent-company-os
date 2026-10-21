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
        # This SDK version (azure-ai-projects 1.0.0b5) builds the client from
        # subscription/resource-group/project-name, not an endpoint URL.
        _client = AIProjectClient(
            credential=DefaultAzureCredential(),
            subscription_id=settings.AZURE_SUBSCRIPTION_ID,
            resource_group_name=settings.AZURE_RESOURCE_GROUP,
            project_name=settings.FOUNDRY_PROJECT_NAME,
        )
    return _client


@router.post("/api/chat")
def chat(
    message: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    client = get_foundry_client()

    # One thread per user, reused across the session, so follow-up questions
    # keep context ("what about its budget?" after "tell me about Loomwell").
    thread = client.agents.threads.create()

    client.agents.messages.create(thread_id=thread.id, role="user", content=message)

    run = client.agents.runs.create_and_process(
        thread_id=thread.id, agent_id=settings.FOUNDRY_CEO_AGENT_ID
    )

    reply_text = "Sorry, I couldn't get an answer just now."
    if run.status == "completed":
        messages = client.agents.messages.list(thread_id=thread.id)
        for m in messages:
            if m.role == "assistant" and m.text_messages:
                reply_text = m.text_messages[-1].text.value
                break

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
