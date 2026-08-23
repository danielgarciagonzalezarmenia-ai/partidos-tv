const STATE = { data: null, filter: "all" };

async function load() {
  try {
    const res = await fetch("matches.json", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    STATE.data = await res.json();
  } catch (e) {
    document.getElementById("schedule").innerHTML =
      '<div class="empty">No se pudo cargar matches.json<br><small>' + e.message + "</small></div>";
    return;
  }
  render();
}

function fmtDay(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" });
}
function fmtTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
}
function isLive(iso) {
  const t = new Date(iso).getTime();
  const now = Date.now();
  return now >= t && now < t + 3 * 3600 * 1000;
}

function competitions() {
  const set = new Set();
  (STATE.data.matches || []).forEach(m => set.add(m.competition || "Otros"));
  return ["all", ...Array.from(set)];
}

function renderFilters() {
  const el = document.getElementById("filters");
  el.innerHTML = "";
  competitions().forEach(c => {
    const b = document.createElement("button");
    b.className = "chip" + (STATE.filter === c ? " active" : "");
    b.textContent = c === "all" ? "Todos" : c;
    b.onclick = () => { STATE.filter = c; render(); };
    el.appendChild(b);
  });
}

function render() {
  const data = STATE.data || { matches: [] };
  document.getElementById("updated").textContent =
    "Actualizado: " + new Date(data.updated || Date.now()).toLocaleString("es-ES");

  renderFilters();

  const matches = (data.matches || [])
    .filter(m => STATE.filter === "all" || (m.competition || "Otros") === STATE.filter)
    .sort((a, b) => new Date(a.startTime) - new Date(b.startTime));

  const sched = document.getElementById("schedule");
  if (!matches.length) {
    sched.innerHTML = '<div class="empty">No hay partidos disponibles.</div>';
    return;
  }

  const groups = {};
  matches.forEach(m => {
    const day = (m.startTime || "").slice(0, 10);
    (groups[day] = groups[day] || []).push(m);
  });

  sched.innerHTML = "";
  Object.keys(groups).sort().forEach(day => {
    const g = document.createElement("div");
    g.className = "day-group";
    g.innerHTML = '<h2 class="day-title">' + fmtDay(groups[day][0].startTime) + "</h2>";
    const grid = document.createElement("div");
    grid.className = "grid";
    groups[day].forEach(m => grid.appendChild(card(m)));
    g.appendChild(grid);
    sched.appendChild(g);
  });
}

function card(m) {
  const el = document.createElement("div");
  el.className = "match";
  const live = isLive(m.startTime);
  el.innerHTML =
    (live ? '<span class="live-badge">EN VIVO</span>' : "") +
    '<div class="comp">' + (m.competition || "Otros") + "</div>" +
    '<div class="teams">' + m.home + " vs " + m.away + "</div>" +
    '<div class="row"><span class="time">' + fmtTime(m.startTime) + "</span>" +
    '<span class="src">' + (m.source || "") + "</span></div>";
  el.onclick = () => openModal(m);
  return el;
}

function openModal(m) {
  document.getElementById("modal-title").textContent = m.home + " vs " + m.away;
  document.getElementById("modal-iframe").src = m.iframe || "";
  document.getElementById("modal").classList.remove("hidden");
}
function closeModal() {
  document.getElementById("modal").classList.add("hidden");
  document.getElementById("modal-iframe").src = "";
}
document.querySelectorAll("[data-close]").forEach(e => e.onclick = closeModal);
document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });

load();
setInterval(load, 5 * 60 * 1000);
