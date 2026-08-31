# IAHAF — WhatsApp + IA

Backend que recibe mensajes de WhatsApp (Cloud API de Meta) y responde. Hoy está en modo **echo** (repite el texto). El siguiente paso es enchufar un modelo de IA.

## ¿Hay que regenerar el token y levantar el servidor siempre?

**Hoy sí, porque estamos en modo prueba local.** No es el destino final.

| Qué | Ahora (prueba) | Después (producción) |
|---|---|---|
| Acceso a Meta | Usuario del sistema `iahaf-bot` (credenciales en `.env` local). | El mismo acceso sirve en producción; no uses el del panel de prueba. |
| Servidor | Lo corrés en tu PC. Si apagás la PC, deja de contestar. | Railway Hobby: 24/7, la PC puede estar apagada. |
| URL pública | `localhost.run` / ngrok: cambia y hay que actualizar el webhook en Meta. | `https://….up.railway.app/webhook`, se configura **una sola vez**. |
| Número | Número de prueba de Meta (`+1 555-203-0245`). Solo habla con números autorizados. | Número de WhatsApp Business propio. |

Resumen: el software y el usuario del sistema `iahaf-bot` ya están. En prueba local todavía hay que levantar el servidor y, si cambia el túnel, actualizar el webhook. Cuando haya hosting con URL fija, eso también queda atrás.

## Cómo correrlo en otra PC

1. Clonar:

```bash
git clone https://github.com/franckococco/iahafid.git
cd iahafid
```

2. Python 3.11+, crear entorno e instalar:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

3. Copiar `.env.example` a `.env` y completar:
   - `WHATSAPP_TOKEN` (el vigente, no subas este archivo a GitHub)
   - `WHATSAPP_PHONE_NUMBER_ID=1276343198895660`
   - `WHATSAPP_BUSINESS_ACCOUNT_ID=1281373443982245`
   - `WHATSAPP_VERIFY_TOKEN=iahaf-verify-cambiar`

4. Levantar:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

5. Exponer con un túnel (mientras sea local):

```bash
npx localtunnel --port 8000
```

6. En Meta, webhook:
   - Callback URL: `https://TU-TUNEL/webhook`
   - Verify token: `iahaf-verify-cambiar`
   - Campo suscrito: **messages**

App de Meta: [IAHAFID](https://developers.facebook.com/apps/1810396190374656/dashboard/)

## Estructura

- `app/main.py` — webhook GET (verificación) y POST (mensajes)
- `app/whatsapp.py` — envío a Cloud API (incluye fallback de formato argentino)
- `app/ai.py` — `AI_MODE=echo` o `openai`
- `.env` — secretos (nunca se sube)

## Siguiente paso de producto

1. ~~Usuario del sistema (`iahaf-bot`).~~ Hecho.
2. Poner `AI_MODE=openai` y una API key (OpenAI, Groq, etc.) y definir cómo debe contestar IAHAF.
3. Hosting con URL fija (para no actualizar el webhook cada vez).
4. Pasar de número de prueba a número de producción.
