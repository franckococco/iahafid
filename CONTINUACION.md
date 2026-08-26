# Continuación de la charla (26 ago 2026)

Contexto para seguir IAHAF en otra PC o con otra sesión de Cursor. **No incluye tokens.** El repo es público: los secretos viven solo en `.env` local (copialo a mano, no está en GitHub).

Repo: https://github.com/franckococco/iahafid

Pegá el archivo `PEGAR-EN-LA-OTRA-PC.txt` en Cursor para retomar.

## Idea del producto (no perderla)

WhatsApp de Meta es el **tubo** (entra y sale el mensaje). La IA de Meta **no se usa**: inventa y no sirve para vender.

El vendedor es **nuestro software + Gemini**, con el catálogo del local.

El cliente escribe como le sale (`hola tenes filtro para el peugeot 308 2014?`). El bot no es un formulario.

- Lo **rápido** (filtro, pastillas, bujías, etc. con SKU claro) lo cierra el bot: cotiza y ofrece apartar.
- Lo **complejo** (kit distribución, motor, caja, computadora, a pedido) pide **número de chasis** (cédula o parabrisas), **nunca motor**, y pasa a un vendedor.
- Esa clasificación va en el catálogo (`tipo`: `rapido` / `complejo`), no la decide Gemini.
- Los productos se graban en `data/products.json`. Cómo los pide la gente se guarda en `data/learned.json` (no se sube). El chasis del cliente va en `data/customers.json` (no se sube).
- Consulta del catálogo: `GET /consulta?q=filtro+308+2014`.

Número de prueba `+1 555-203-0245`: solo habla con hasta **5** celulares autorizados en Meta (API Setup → destinatarios). Un cliente cualquiera no puede escribir todavía. En producción, con número Business propio, sí.

## Qué hay en el código ahora

- Gemini (`gemini-3.6-flash`) arma la respuesta. Si se cae y hay match de catálogo, cotiza igual (el caso del 308 2014, $12.500).
- Catálogo de ejemplo: filtro 308 2012-2018, pastillas C3, kit Gol Trend.
- Búsqueda informal: sin tildes, año dentro del rango cuenta. Nunca pide motor.
- Si la pieza es compleja o hay más de un SKU, pide chasis, lo guarda y deriva.
- Memoria: últimos 16 mensajes por cliente (`data/chats.json`, no se sube).
- Manuales: hoy un `.txt` de prueba; por mensaje manda los 3 mejores, 700 caracteres. Los PDF completos van después (buscar el párrafo útil, no pegar el archivo entero).
- Si pide vendedor / reclamo / garantía, deriva sin pasar por la IA.
- Dockerfile listo para hosting (Railway) con URL fija. Hasta que no esté online, `localtunnel` cambia y hay que actualizar el webhook.

## Meta (ya armado, no repetir)

- App IAHAFID `1810396190374656`, Business `2133555070823660`
- Phone Number ID `1276343198895660`, WABA `1281373443982245`
- System user `iahaf-bot` (ID `61593880496805`). Token en `.env` como `WHATSAPP_TOKEN`
- Verify token: `iahaf-verify-cambiar`
- Campo suscrito: **messages**
- En Argentina a veces hay que probar formato `549…` y el de `15` (`app/whatsapp.py`)

Enlaces:

- App: https://developers.facebook.com/apps/1810396190374656/dashboard/
- Webhook: https://developers.facebook.com/apps/1810396190374656/use_cases/customize/wa-configurations-v2/?product_route=whatsapp-business
- System users: https://business.facebook.com/settings/system-users?business_id=2133555070823660

## Cómo correrlo en local (mientras no haya hosting)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
npx localtunnel --port 8000
```

Webhook en Meta: `https://TU-TUNEL.loca.lt/webhook` + `iahaf-verify-cambiar`.

El `.env` se copia de la otra PC (nunca de GitHub). `AI_MODE=openai`, modelo `gemini-3.6-flash`.

## Qué sigue

1. Subir a Railway (URL fija, dejar de reiniciar túnel).
2. Cargar el Excel real con columna `tipo` (rapido/complejo).
3. Aviso al vendedor cuando derive.
4. Manuales: buscar el párrafo útil.
5. Número de WhatsApp Business propio.
