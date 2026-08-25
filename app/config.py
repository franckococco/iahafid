from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ROOT / ".env", extra="ignore")

    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_business_account_id: str = ""
    whatsapp_display_number: str = ""
    whatsapp_verify_token: str = "iahaf-verify-cambiar"
    whatsapp_app_secret: str = ""
    graph_api_version: str = "v21.0"

    ai_mode: str = "echo"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    ai_system_prompt: str = (
        "Sos el asistente de IAHAF. Respondé en español, de forma breve y clara, por WhatsApp."
    )


settings = Settings()
