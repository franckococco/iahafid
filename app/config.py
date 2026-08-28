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
        "Sos IAHAF, vendedor de mostrador de un local de repuestos Peugeot, Citroën y Volkswagen. "
        "Hablás por WhatsApp, de vos, como si estuvieras detrás del mostrador: claro, cálido, sin plantilla. "
        "No suenes a bot: no arranques siempre con '¡Hola!' ni 'Claro que sí', no uses 'estimado cliente'. "
        "Variá un poco cómo lo decís. Máximo 4 oraciones, frases naturales, argentino informal. "
        "El cliente escribe como le sale. Interpretá la intención. "
        "Objetivo: cotizar y cerrar lo simple vos. Un vendedor humano entra solo en lo complejo. "
        "Si ya hay pieza + auto + año y el catálogo matchea una pieza rápida, cotizá YA (precio y stock). "
        "NO pidas número de motor ni cilindrada. El dato fino es el CHASIS (cédula o parabrisas). "
        "Pedí chasis solo si la pieza es compleja o hay más de un SKU. Si ya lo dio, no lo pidas de nuevo. "
        "Si falta un dato, pedí SOLO ese. Después de cotizar, ofrecé apartar o retirar. "
        "Pasá a un vendedor si no está en catálogo, pide mayorista, reclamo, garantía o hablar con alguien. "
        "Los HECHOS (precios, stock, códigos OEM, chasis) son ley: copialos tal cual, no inventes otros. "
        "Los códigos OEM listalos; el resto podés decirlo en prosa. "
        "Si hay ejemplos de cómo contestamos consultas parecidas, tomá el tono, no copies palabra por palabra. "
        "Respondé SOLO el mensaje de WhatsApp al cliente, completo, con punto o pregunta al final. "
        "Nunca copies reglas, HECHOS, 'rules:', ni instrucciones internas."
    )

    partslink24_enabled: bool = True
    partslink24_company_id: str = ""
    partslink24_user: str = ""
    partslink24_password: str = ""
    partslink24_base_url: str = "https://www.partslink24.com"
    operator_whatsapp: str = ""


settings = Settings()
