# Continuación de la charla (25 ago 2026)

Contexto para seguir el proyecto en otra PC o con otra sesión de Cursor. **No incluye tokens.** El repo es público: los secretos viven solo en `.env` local.

Repo: https://github.com/franckococco/iahafid

## Qué se logró

1. App de Meta **IAHAFID** (ID `1810396190374656`, Business ID `2133555070823660`) con WhatsApp Cloud API.
2. Número de prueba: `+1 555-203-0245` (Phone Number ID `1276343198895660`, WABA `1281373443982245`).
3. Webhook de mensajes conectado al backend FastAPI. Meta llama `POST /webhook` cuando alguien escribe.
4. El bot **recibe y responde** en modo echo: `IAHAF recibió: Hola`.
5. Cuenta WABA suscrita a la app IAHAFID (antes estaba enganchada a una app interna de Meta y el webhook no disparaba).
6. Usuario del sistema **iahaf-bot** (ID `61593880496805`, Admin) con la app y WhatsApp asignados. Las credenciales quedan solo en `.env` local, no en GitHub.

## Problemas que ya se resolvieron

- Hay que suscribir la WABA a la app (`POST /{WABA-ID}/subscribed_apps`).
- El acceso del panel de desarrollador vence; si pasa, el bot lee el mensaje y no puede responder (error 190). Por eso se usa el usuario del sistema `iahaf-bot`.
- En Argentina, WhatsApp manda `549…` y Meta a veces autoriza el formato con `15`. El código prueba ambos (`app/whatsapp.py`).
- `localtunnel` cambia de URL al reiniciar. Hay que actualizar el callback en Meta. La última URL usada fue `https://fast-fireant-6.loca.lt/webhook` (puede haber cambiado).
- Verify token del webhook: `iahaf-verify-cambiar`.
- Campo suscrito: **messages**.

## Cómo se armó Meta (para no repetirlo)

1. Developers: app IAHAFID → WhatsApp → webhook (callback + verify token) → suscribir `messages`.
2. Destinatario de prueba: el celular del dueño, autorizado en API Setup / Prueba la API.
3. Business Settings → Usuarios del sistema → crear `iahaf-bot` Admin → asignar app y WhatsApp → Generar token (Nunca).
4. Las credenciales van en `.env` como `WHATSAPP_TOKEN` (nunca en el chat ni en GitHub).

Enlaces útiles:

- App: https://developers.facebook.com/apps/1810396190374656/dashboard/
- Webhook: https://developers.facebook.com/apps/1810396190374656/use_cases/customize/wa-configurations-v2/?product_route=whatsapp-business
- System users: https://business.facebook.com/settings/system-users?business_id=2133555070823660

## Estado actual del código

- Seguimos en **modo prueba** (número de prueba de Meta, no producción).
- `AI_MODE=echo` (todavía no hay modelo de IA).
- Servidor local: `uvicorn app.main:app --host 127.0.0.1 --port 8000`.
- Túnel: `npx localtunnel --port 8000`.
- Token y secretos: solo `.env` local.

## Qué hacer en la próxima sesión

1. Confirmar que el eco sigue contestando (mandar Hola al número de prueba).
2. Enfocarse en el **producto**: conectar la IA (`AI_MODE=openai` u otro modelo), prompts, y lógica del negocio.
3. Más adelante: hosting 24/7 con URL fija (así el webhook no cambia más).
4. Cuando esté estable: número de WhatsApp Business real (dejar el de prueba).

## Cómo retomar en Cursor

Abrí esta carpeta (o el clone de GitHub) y pedí: *seguir IAHAF en modo prueba: Meta ya está, conectar la IA*. Leé este archivo y el README antes de tocar Meta. No regeneres el acceso del panel; usá el de `iahaf-bot`.
