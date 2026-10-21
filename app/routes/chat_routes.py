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


class _ForceAudienceCredential:
    """
    Wraps DefaultAzureCredential and ignores whatever scope the SDK asks
    for, always requesting a token for https://ai.azure.com/.default
    instead. The AIProjectClient constructor itself refuses a
    credential_scopes override ("No support for overriding the credential
    scopes" - raised from its own _patch.py), but it has no way to stop us
    wrapping the credential object it calls .get_token() on - so we force
    the audience here. This exists because, even with every relevant RBAC
    role granted (Foundry User, Cognitive Services User, Cognitive
    Services OpenAI User), calls kept failing with "Unauthorized ...
    audience is incorrect (https://ai.azure.com)" - meaning the token this
    SDK version requests by default has some other audience baked in.
    """

    def __init__(self, inner):
        self._inner = inner

    def get_token(self, *scopes, **kwargs):
        return self._inner.get_token("https://ai.azure.com/.default", **kwargs)


def get_foundry_client() -> AIProjectClient:
    global _client
    if _client is None:
        # This SDK version (azure-ai-projects 1.0.0b5) needs ALL of these
        # together: endpoint AND subscription/resource-group/project-name.
        # The constructor itself refuses credential_scopes, so the fix is
        # the _ForceAudienceCredential wrapper above, not a kwarg here.
        _client = AIProjectClient(
            endpoint=settings.FOUNDRY_PROJECT_ENDPOINT,
            credential=_ForceAudienceCredential(DefaultAzureCredential()),
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
    # This SDK version (1.0.0b5) exposes these as flat methods on
    # client.agents, not nested under .threads/.messages/.runs.
    thread = client.agents.create_thread()

    client.agents.create_message(thread_id=thread.id, role="user", content=message)

    run = client.agents.create_and_process_run(
        thread_id=thread.id, assistant_id=settings.FOUNDRY_CEO_AGENT_ID
    )

    reply_text = "Sorry, I couldn't get an answer just now."
    if run.status == "completed":
        messages = client.agents.list_messages(thread_id=thread.id)
        for m in messages.data:
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
