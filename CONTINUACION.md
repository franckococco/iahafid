# Continuación de la charla (28 ago 2026)

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
- Dockerfile listo para hosting (Railway) con URL fija. Hasta que no esté online, el túnel (`localhost.run`) cambia y hay que actualizar el webhook.
- PartsLink24 (Playwright): con chasis busca la pieza en el catálogo OEM. La foto es la **lámina del despiece**, no la lista de resultados. "nuevo pedido" reinicia el chat.
- Pieza ambigua: pregunta el tipo (bomba, filtro) o eje/lado. "bomba de agua" busca "bomba para liquido refrigerante" y solo lista el artículo que ES la bomba (no tubo/sensor/radiador).
- VW VIN de 17 abre el auto. Peugeot last-8: `data/peugeot-chasis.json` y entra por logo Peugeot (Acceso directo no indexa esos 8).
- Pedido chasis / listas OEM: plantillas (Gemini no; cortaba y filtraba el prompt).
- Túnel: `arrancar.ps1` o `scripts/keep_tunnel.py`. uvicorn **sin** `--reload`.
- Estado: 28 ago 2026, 2ª prueba WhatsApp (Bora 2010 `3VWSW49M5AM001581`) filtró mal el circuito; corregido por sujeto del nombre.

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
python -m playwright install chromium
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
ssh -o ServerAliveInterval=30 -R 80:127.0.0.1:8000 nokey@localhost.run
```

En Meta pegar siempre:

- Dónde ir: https://developers.facebook.com/apps/1810396190374656/use_cases/customize/wa-configurations-v2/?product_route=whatsapp-business
- Callback (cambia): `https://EL-TUNEL.lhr.life/webhook`
- Servidor local: `http://127.0.0.1:8000`
- Token: `iahaf-verify-cambiar`

Ahora (28 ago 2026, vence si se cae): `https://60809fc999d428.lhr.life/webhook`

El `.env` se copia de la otra PC (nunca de GitHub). `AI_MODE=openai`, modelo `gemini-3.6-flash`.

## Qué sigue

1. Railway ya está: `https://iahafid-production.up.railway.app/webhook`. Hobby, proyecto courteous-celebration, servicio iahafid. Push a main actualiza solo. No tocar Meta.
2. Cargar el Excel real con columna `tipo` (rapido/complejo).
3. Precios del proveedor (scrape, no inventar).
4. Aviso al vendedor cuando derive.
5. Manuales: buscar el párrafo útil.
6. Número de WhatsApp Business propio.
