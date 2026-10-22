"""
CEO chatbot endpoint. Talks to the "ceo-assistant" agent built in the
New Microsoft Foundry portal, which has File Search over the project-status
and people docs (the RAG layer: it answers from those docs and cites them).

Why this looks the way it does:
  New Foundry agents are NOT the classic Assistants-style agents. They have
  no "asst_..." ID and are not driven with threads/runs. They are referenced
  by NAME and called through the OpenAI Responses API, via
  AIProjectClient.get_openai_client(). Using the classic threads/runs API
  against them fails with "Invalid 'assistant_id' ... Expected an ID that
  begins with 'asst'".
"""
import logging

from fastapi import APIRouter, Depends, Form
from sqlalchemy.orm import Session
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

from ..config import settings
from ..db import get_db, ChatMessage
from ..auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter()

_project: AIProjectClient | None = None
_openai = None
_bound_to_agent = False          # True if get_openai_client(agent_name=...) worked
_conversations: dict[int, str] = {}  # user_id -> conversation id (keeps follow-up context)


def _get_openai_client():
    """OpenAI-compatible client for the Foundry project (azure-ai-projects 2.x)."""
    global _project, _openai, _bound_to_agent
    if _openai is None:
        _project = AIProjectClient(
            endpoint=settings.FOUNDRY_PROJECT_ENDPOINT,
            credential=DefaultAzureCredential(),
        )
        try:
            # Current docs: client pre-bound to the named agent.
            _openai = _project.get_openai_client(agent_name=settings.FOUNDRY_CEO_AGENT_NAME)
            _bound_to_agent = True
        except TypeError:
            # Older 2.x releases: unbound client; agent passed per request instead.
            _openai = _project.get_openai_client()
            _bound_to_agent = False
    return _openai


def _ask_agent(user_id: int, text: str) -> str:
    client = _get_openai_client()

    conv_id = _conversations.get(user_id)
    if conv_id is None:
        conv_id = client.conversations.create().id
        _conversations[user_id] = conv_id

    kwargs = {"conversation": conv_id, "input": text}
    if not _bound_to_agent:
        kwargs["extra_body"] = {
            "agent": {"name": settings.FOUNDRY_CEO_AGENT_NAME, "type": "agent_reference"}
        }
    response = client.responses.create(**kwargs)
    return response.output_text or "The assistant returned an empty reply."


@router.post("/api/chat")
def chat(
    message: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        reply_text = _ask_agent(user.id, message)
    except Exception as e:  # show the real reason in the UI instead of a blank 500
        log.exception("CEO agent call failed")
        _conversations.pop(user.id, None)  # start fresh next time in case the conversation broke
        reply_text = f"[Agent error] {type(e).__name__}: {e}"

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
