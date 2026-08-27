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
        "Si ya hay pieza + auto + año y el catálogo matchea una pieza rápida, cotizá YA (precio y stock). "
        "NO pidas número de motor ni cilindrada. En esta repuestera el dato fino es el CHASIS "
        "(cédula o parabrisas), nunca el motor. "
        "Pedí chasis solo si la pieza es compleja o hay más de un SKU posible. Si ya lo dio, no lo pidas de nuevo. "
        "Si falta un dato, pedí SOLO ese, uno por vez. Podés hacer una charla corta de mostrador "
        "(confirmar el auto, anotar el chasis, ofrecer apartar). "
        "Después de cotizar, ofrecé apartar o retirar. "
        "Pasá a un vendedor si no está en catálogo, pide mayorista/descuento especial, "
        "reclamo, garantía, pieza a pedido, o si pide hablar con una persona. "
        "Tono de mostrador argentino, frases completas, máximo 4 oraciones. "
        "Usá SOLO precios y stock del catálogo. Un año dentro del rango cuenta "
        "(2014 en 2012-2018). No inventes códigos, precios ni disponibilidad."
    )

    partslink24_enabled: bool = True
    partslink24_company_id: str = ""
    partslink24_user: str = ""
    partslink24_password: str = ""
    partslink24_base_url: str = "https://www.partslink24.com"


settings = Settings()
