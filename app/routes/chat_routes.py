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
        # This SDK version (azure-ai-projects 1.0.0b5) needs ALL of these
        # together: endpoint AND subscription/resource-group/project-name.
        # credential_scopes is forced explicitly because, even with every
        # relevant RBAC role assigned (Foundry User, Cognitive Services
        # OpenAI User, Cognitive Services User, Azure AI Developer), the
        # Managed Identity token the SDK requested by default had the wrong
        # audience - the server kept rejecting it with "audience is
        # incorrect (https://ai.azure.com)". Requesting the token for that
        # exact audience ourselves works around it.
        _client = AIProjectClient(
            endpoint=settings.FOUNDRY_PROJECT_ENDPOINT,
            credential=DefaultAzureCredential(),
            subscription_id=settings.AZURE_SUBSCRIPTION_ID,
            resource_group_name=settings.AZURE_RESOURCE_GROUP,
            project_name=settings.FOUNDRY_PROJECT_NAME,
            credential_scopes=["https://ai.azure.com/.default"],
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
