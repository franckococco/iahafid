# Continuación de la charla (25 ago 2026)

Contexto para seguir el proyecto en otra PC o con otra sesión de Cursor. **No incluye tokens.** El repo es público: los secretos viven solo en `.env` local.

## Qué se logró

1. App de Meta **IAHAFID** (ID `1810396190374656`) con WhatsApp Cloud API.
2. Número de prueba: `+1 555-203-0245` (Phone Number ID `1276343198895660`, WABA `1281373443982245`).
3. Webhook de mensajes conectado al backend FastAPI. Meta llama `POST /webhook` cuando alguien escribe.
4. El bot **recibe y responde** en modo echo: `IAHAF recibió: Hola`.
5. Cuenta WABA suscrita a la app IAHAFID (antes estaba enganchada a una app interna de Meta y el webhook no disparaba).

## Problemas que ya se resolvieron

- Hay que suscribir la WABA a la app (`POST /{WABA_ID}/subscribed_apps`).
- El token del panel es temporal: si vence, el bot lee el mensaje (doble check) y no puede responder (error 190).
- En Argentina, WhatsApp manda `549…` y Meta a veces autoriza el formato con `15`. El código prueba ambos.
- `localtunnel` cambia de URL al reiniciar. Hay que actualizar el callback en Meta.

## Estado actual del código

- `AI_MODE=echo` (todavía no hay modelo de IA).
- Verify token del webhook: `iahaf-verify-cambiar`.
- Campo de webhook suscrito: **messages**.
- Token y datos reales: solo en `.env` de la PC donde se configuró. En la otra PC hay que volver a pegar un token vigente.

## Qué hacer en la próxima sesión

1. Generar **token permanente** de System User (Meta Business / Usuarios del sistema) para no regenerarlo cada día.
2. Subir el servidor a un hosting con HTTPS fijo y dejar el webhook apuntando ahí.
3. Cambiar `AI_MODE=openai` y conectar el modelo.
4. Cuando esté estable, pasar del número de prueba a un número de WhatsApp Business real.

## Cómo retomar en Cursor

Abrí esta carpeta (o el clone de GitHub) y pedí: *seguir IAHAF: token permanente, hosting y conectar la IA*. Leé este archivo y el README antes de tocar Meta.
