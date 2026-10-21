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
    FOUNDRY_PROJECT_ENDPOINT: str = ""   # e.g. https://<your-foundry-resource>.services.ai.azure.com/api/projects/<project-name>
    FOUNDRY_CEO_AGENT_ID: str = ""       # set after creating the CEO agent in the portal

    # --- Azure AI Vision (Lens feature) ---
    VISION_ENDPOINT: str = ""            # e.g. https://<your-vision-resource>.cognitiveservices.azure.com
    VISION_KEY: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
