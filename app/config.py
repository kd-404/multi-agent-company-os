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
    # This SDK version (azure-ai-projects 1.0.0b5) needs ALL four of these
    # together to build the client: endpoint + subscription/RG/project-name.
    FOUNDRY_PROJECT_ENDPOINT: str = ""    # e.g. https://proj-uaenorth-resource.services.ai.azure.com/api/projects/proj-uaenorth
    AZURE_SUBSCRIPTION_ID: str = ""       # your Azure subscription GUID
    AZURE_RESOURCE_GROUP: str = ""        # resource group that holds the Foundry project (e.g. proj-uaenorth's RG)
    FOUNDRY_PROJECT_NAME: str = ""        # the Foundry project name (e.g. proj-uaenorth)
    FOUNDRY_CEO_AGENT_ID: str = ""        # legacy (classic asst_... IDs); unused for New Foundry agents
    FOUNDRY_CEO_AGENT_NAME: str = "ceo-assistant"  # New Foundry agents are called by NAME

    # --- Azure AI Vision (Lens feature) ---
    VISION_ENDPOINT: str = ""            # e.g. https://<your-vision-resource>.cognitiveservices.azure.com
    VISION_KEY: str = ""

    # --- Design agent: trend research (Tavily) + image generation (Foundry) ---
    TAVILY_API_KEY: str = ""             # from tavily.com dashboard, free tier
    FOUNDRY_IMAGE_DEPLOYMENT: str = "gpt-image-1.5"  # deployment name from Foundry > Models

    # --- Razorpay (checkout) ---
    # From the Razorpay dashboard (Settings -> API Keys), once KYC is
    # approved. Leaving these blank keeps checkout in simulated mode - see
    # app/routes/payment_routes.py's razorpay_configured(). RAZORPAY_KEY_ID
    # is not secret (it's sent to the browser to open the checkout widget);
    # RAZORPAY_KEY_SECRET must never leave the server.
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""

    # --- Instagram Graph API (marketing auto-post) ---
    # From a Meta developer app connected to an Instagram Business/Creator
    # account linked to a Facebook Page. Leaving these blank keeps
    # "Schedule post" in simulated mode - see app/routes/marketing_routes.py.
    INSTAGRAM_ACCESS_TOKEN: str = ""
    INSTAGRAM_BUSINESS_ACCOUNT_ID: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
