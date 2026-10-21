"""
Central config. Everything is read from environment variables so no secrets
ever live in the repo. Set these in Azure App Service -> Configuration ->
Application settings (portal UI, no code/CLI needed).
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Core app ---
    SECRET_KEY: str = "change-me-in-azure-app-settings"
    ENV: str = "production"

    # --- Database (Azure Database for PostgreSQL Flexible Server) ---
    DATABASE_URL: str = "sqlite:///./loomwell_dev.db"  # local fallback only

    # --- Azure AI Foundry (CEO chatbot / RAG) ---
    # The azure-ai-projects 1.0.0b5 SDK's AIProjectClient does NOT take an
    # endpoint URL - it builds the connection from these three IDs instead.
    AZURE_SUBSCRIPTION_ID: str = ""       # your Azure subscription GUID
    AZURE_RESOURCE_GROUP: str = ""        # resource group that holds the Foundry project (e.g. proj-uaenorth's RG)
    FOUNDRY_PROJECT_NAME: str = ""        # the Foundry project name (e.g. proj-uaenorth)
    FOUNDRY_CEO_AGENT_ID: str = ""        # set after creating the CEO agent in the portal

    # --- Azure AI Vision (Lens feature) ---
    VISION_ENDPOINT: str = ""            # e.g. https://<your-vision-resource>.cognitiveservices.azure.com
    VISION_KEY: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
