# Plan IAHAF — que se venda solo, sin reiniciar el servidor

WhatsApp de Meta es el tubo. Gemini es el vendedor. Un humano entra solo en lo complejo.

## Cómo tiene que hablar el cliente

No va a escribir “prolijo”. Todo esto es válido:

- `hola tenes filtro para el peugeot 308 2014?`
- `cuanto el de aceite`
- `tenes para un gol`
- `lo quiero` / `lo aparto` / `paso a la tarde`

El bot interpreta, no arma un formulario. Pide **un** dato si falta. Nunca pide motor si el catálogo no distingue por motor.

## Cómo vende (flujo)

```
mensaje informal
        │
        ▼
¿pide persona / reclamo / mayorista / garantía?
        │ sí → "te dejo con un vendedor"
        ▼ no
buscar catálogo (historial + mensaje, años en rango)
        │
        ▼
Gemini arma la respuesta de mostrador
        │ si Gemini se cae
        ▼
cotización automática del mejor match (precio + stock + "¿lo apartás?")
        │
        ▼
cierre simple: apartar / retirar / medio de pago
```

Cotizar y cerrar lo de mostrador. Pasar a vendedor si:

- no hay pieza en catálogo
- mayorista, descuento especial, factura rara
- reclamo, garantía, siniestro, pieza a pedido
- el cliente se enoja o pide una persona

## Por qué hoy hay que reiniciar

El backend corre en esta PC + `localtunnel`. Cada corte:

- cambia la URL (`*.loca.lt`)
- hay que tocar el webhook en Meta
- si apagás la PC, nadie contesta

Eso **no** se arregla con más prompt. Se arregla subiendo el bot a un hosting con HTTPS fijo.

## Fases (en este orden)

### 1. Dejar de depender de esta PC — ahora

- Subir IAHAF a Railway (o Render / VPS).
- URL fija: `https://iahaf-xxxx.up.railway.app/webhook`.
- Pegar esa URL **una vez** en Meta. Verify token: `iahaf-verify-cambiar`.
- Variables de entorno en el hosting (token `iahaf-bot` + Gemini). Nunca en GitHub.

Hasta que esto no esté, vamos a seguir tocando URL.

### 2. Catálogo real

- Excel/CSV: marca, modelo, año desde-hasta, pieza, SKU, precio, stock.
- Búsqueda tolerante (sin tildes, `308 2014` dentro de 2012–2018).
- La IA **solo** cotiza esa lista.

### 3. Cierre de venta

- Memoria por cliente (ya está).
- Después de cotizar: “¿lo aparto?” / “¿pasás a retirarlo?”.
- Más adelante: reserva + texto de pago.

### 4. Aviso al vendedor

- Resumen del chat + pieza al celular del local.
- El cliente no queda colgado: “en un rato te escriben”.

### 5. Después

- PDF de taller (buscar el párrafo útil).
- Número de WhatsApp Business propio (el de prueba solo habla con tu celular).

## Qué no hacemos

- No usamos el asistente automático de Meta.
- No pedimos motor si el catálogo no lo pide.
- No inventamos precios.
- No tratamos `loca.lt` como producción.

## Qué ya quedó en el código

- Gemini con reintentos (otros modelos si uno falla).
- Si Gemini igual se cae y hay match de catálogo, cotiza igual (el caso del 308 2014).
- Si el cliente pide un vendedor, se deriva sin pasar por la IA.

## Próximo paso concreto

Elegir hosting (Railway es el más simple). Cuando lo tengas, se sube el repo, se cargan las variables, se pega la URL en Meta **una vez** y esto deja de romperse cada vez que se mueve la PC.
