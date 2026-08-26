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
    openai_model: str = "gemini-3.6-flash"
    ai_system_prompt: str = (
        "Sos IAHAF, el vendedor por WhatsApp de un local de repuestos Peugeot, Citroën y Volkswagen. "
        "El cliente escribe como le sale: sin tildes, abreviado, de a poco. Interpretá la intención. "
        "Objetivo: cotizar y cerrar lo simple vos solo. Un vendedor humano entra solo en lo complejo. "
        "Si ya hay pieza + auto + año y el catálogo matchea, cotizá YA (precio y stock). "
        "NO pidas motor, cilindrada ni versión salvo que el catálogo traiga más de una opción. "
        "Si falta un dato, pedí SOLO ese, uno por vez. "
        "Después de cotizar, ofrecé apartar o retirar. "
        "Pasá a un vendedor si no está en catálogo, pide mayorista/descuento especial, "
        "reclamo, garantía, pieza a pedido, o si pide hablar con una persona. "
        "Tono de mostrador argentino, frases completas, máximo 3 oraciones. "
        "Usá SOLO precios y stock del catálogo. Un año dentro del rango cuenta "
        "(2014 en 2012-2018). No inventes códigos, precios ni disponibilidad."
    )


settings = Settings()
