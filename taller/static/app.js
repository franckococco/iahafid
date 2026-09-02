const form = document.getElementById("form");
const piezasBox = document.getElementById("piezas");
const lista = document.getElementById("lista");
const log = document.getElementById("log");
const ask = document.getElementById("ask");
const pregunta = document.getElementById("pregunta");
let history = [];

function piezaRow(data = {}) {
  const wrap = document.createElement("div");
  wrap.className = "pieza";
  wrap.innerHTML = `
    <input placeholder="Nombre (cazoleta)" value="${esc(data.nombre || "")}">
    <input placeholder="Marca (Sachs)" value="${esc(data.marca || "")}">
    <input placeholder="Lado / par" value="${esc(data.lado || "")}">
    <input placeholder="Código" value="${esc(data.codigo || "")}">
    <input placeholder="Nota" value="${esc(data.nota || "")}">
    <button type="button" class="tiny ghost" aria-label="Quitar">×</button>
  `;
  wrap.querySelector("button").onclick = () => wrap.remove();
  return wrap;
}

function esc(text) {
  return String(text).replace(/[&<>"']/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch])
  );
}

function leerForm() {
  const data = Object.fromEntries(new FormData(form).entries());
  data.piezas = [...piezasBox.querySelectorAll(".pieza")].map((row) => {
    const [nombre, marca, lado, codigo, nota] = row.querySelectorAll("input");
    return {
      nombre: nombre.value.trim(),
      marca: marca.value.trim(),
      lado: lado.value.trim(),
      codigo: codigo.value.trim(),
      nota: nota.value.trim(),
    };
  });
  return data;
}

function pintarForm(ficha) {
  form.reset();
  form.fid.value = ficha.id || "";
  form.marca.value = ficha.marca || "";
  form.modelo.value = ficha.modelo || "";
  form.motor.value = ficha.motor || "";
  form.anio.value = ficha.anio || "";
  form.conjunto.value = ficha.conjunto || "";
  form.notas.value = ficha.notas || "";
  form.venta.value = ficha.venta || "";
  piezasBox.innerHTML = "";
  const piezas = ficha.piezas && ficha.piezas.length ? ficha.piezas : [{}];
  piezas.forEach((p) => piezasBox.appendChild(piezaRow(p)));
}

async function cargarLista() {
  const res = await fetch("/api/fichas");
  const data = await res.json();
  lista.innerHTML = "";
  for (const item of data.fichas || []) {
    const li = document.createElement("li");
    const titulo = [item.marca, item.modelo, item.motor, item.anio].filter(Boolean).join(" ");
    li.innerHTML = `<span>${esc(titulo || "sin auto")}<br><small>${esc(item.conjunto || "")}</small></span>
      <button type="button" class="tiny ghost">Borrar</button>`;
    li.querySelector("span").onclick = () => pintarForm(item);
    li.querySelector("button").onclick = async (ev) => {
      ev.stopPropagation();
      if (!confirm("¿Borrar esta ficha?")) return;
      await fetch("/api/fichas/" + encodeURIComponent(item.id), { method: "DELETE" });
      cargarLista();
    };
    lista.appendChild(li);
  }
}

function bubble(who, text, facts) {
  const div = document.createElement("div");
  div.className = "msg " + who;
  div.innerHTML = `<div class="who">${who === "user" ? "Cliente" : "Mostrador"}</div><p></p>`;
  div.querySelector("p").textContent = text;
  if (facts) {
    const pre = document.createElement("pre");
    pre.className = "facts";
    pre.textContent = facts;
    div.appendChild(pre);
  }
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

document.getElementById("add-pieza").onclick = () => piezasBox.appendChild(piezaRow());
document.getElementById("nueva").onclick = () => {
  pintarForm({ piezas: [{}] });
};

form.onsubmit = async (ev) => {
  ev.preventDefault();
  const body = leerForm();
  const res = await fetch("/api/fichas", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    alert("No se pudo guardar. Completá modelo o conjunto.");
    return;
  }
  const data = await res.json();
  pintarForm(data.ficha);
  cargarLista();
};

const excelInput = document.getElementById("excel");
const bulkMsg = document.getElementById("bulk-msg");
excelInput.onchange = async () => {
  const file = excelInput.files && excelInput.files[0];
  excelInput.value = "";
  if (!file) return;
  bulkMsg.hidden = false;
  bulkMsg.classList.remove("err");
  bulkMsg.textContent = "Cargando…";
  const body = new FormData();
  body.append("file", file);
  const res = await fetch("/api/fichas/excel", { method: "POST", body });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    bulkMsg.classList.add("err");
    bulkMsg.textContent = data.detail || "No se pudo leer el Excel.";
    return;
  }
  const bits = [];
  if (data.creadas) bits.push(data.creadas + " ficha(s) nueva(s)");
  if (data.actualizadas) bits.push(data.actualizadas + " actualizada(s)");
  bits.push(data.piezas + " pieza(s)");
  let text = "Listo: " + bits.join(", ") + ".";
  if (data.errores && data.errores.length) {
    text += " Salté " + data.errores.length + " fila(s).";
  }
  bulkMsg.textContent = text;
  await cargarLista();
};

ask.onsubmit = async (ev) => {
  ev.preventDefault();
  const message = pregunta.value.trim();
  if (!message) return;
  pregunta.value = "";
  bubble("user", message);
  history.push({ role: "user", text: message });
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history: history.slice(0, -1) }),
  });
  const data = await res.json();
  const answer = data.answer || "No pude contestar.";
  bubble("bot", answer, data.ficha ? data.hechos : "");
  history.push({ role: "assistant", text: answer });
};

pintarForm({ piezas: [{}] });
cargarLista();
bubble(
  "bot",
  "Cargá fichas a mano o subí un Excel. Si me piden una sola pieza, ofrezco el resto. No invento marcas."
);
