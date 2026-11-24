const $ = id => document.getElementById(id);
let state = "STOPPED", dragging = false;
const api = async (path, body) => {
  const r = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
};
const toast = m => { const t = $("toast"); t.textContent = m; t.style.display = "block";
  clearTimeout(toast.t); toast.t = setTimeout(() => t.style.display = "none", 4000); };
const fmt = s => { s = Math.floor(s); const h = Math.floor(s/3600), m = Math.floor(s%3600/60), x = s%60;
  return (h ? h + ":" + String(m).padStart(2,"0") : m) + ":" + String(x).padStart(2,"0"); };
const dev = () => $("device").value;
const wrap = fn => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message); } };

async function loadDevices(scan) {
  $("devmsg").textContent = "Scanning…";
  const list = await api("/api/devices" + (scan ? "?scan=1" : ""));
  const cur = dev();
  $("device").innerHTML = list.map(d => `<option value="${d.id}">${d.name} (${d.ip})</option>`).join("");
  if (cur) $("device").value = cur;
  $("devmsg").textContent = list.length ? "" : "No TV found. Make sure TV is on and on the same Wi-Fi.";
  $("player").hidden = !list.length;
}
async function loadLib() {
  const list = await api("/api/library");
  $("lib").innerHTML = list.length ? "" : '<li class="muted">No videos yet — upload one above.</li>';
  for (const f of list) {
    const li = document.createElement("li");
    li.innerHTML = `<span></span><button>Cast</button>`;
    li.firstChild.textContent = f.name;
    li.lastChild.onclick = wrap(() => cast({path: f.path}));
    $("lib").append(li);
  }
}
async function cast(src) {
  if (!dev()) throw new Error("Select a TV first");
  toast("Sending to TV…");
  await api("/api/cast", {device: dev(), ...src});
  $("now").textContent = src.path || src.url; toast("Casting ✓");
}
const ctl = (action, value) => api("/api/control", {device: dev(), action, value});

$("scan").onclick = wrap(() => loadDevices(true));
$("addManual").onclick = wrap(async () => { await api("/api/devices/add", {target: $("manual").value}); await loadDevices(); });
$("castUrl").onclick = wrap(() => cast({url: $("url").value.trim()}));
$("pp").onclick = wrap(() => ctl(state === "PLAYING" ? "pause" : "play"));
$("stop").onclick = wrap(() => ctl("stop"));
$("back").onclick = wrap(() => ctl("seek", Math.max(0, +$("seek").value - 10)));
$("fwd").onclick = wrap(() => ctl("seek", +$("seek").value + 10));
$("seek").oninput = () => { dragging = true; $("pos").textContent = fmt($("seek").value); };
$("seek").onchange = wrap(async () => { await ctl("seek", $("seek").value); dragging = false; });
$("vol").onchange = wrap(() => ctl("volume", $("vol").value));

$("file").onchange = () => {
  const f = $("file").files[0]; if (!f) return;
  const xhr = new XMLHttpRequest(), fd = new FormData(); fd.append("file", f);
  $("prog").hidden = false;
  xhr.upload.onprogress = e => { $("prog").value = e.loaded / e.total * 100; };
  xhr.onload = wrap(async () => {
    $("prog").hidden = true;
    const j = JSON.parse(xhr.responseText);
    if (xhr.status !== 200) throw new Error(j.error || "Upload failed");
    await loadLib(); await cast({path: j.path});
  });
  xhr.onerror = () => { $("prog").hidden = true; toast("Upload failed"); };
  xhr.open("POST", "/api/upload"); xhr.send(fd);
};

setInterval(async () => {
  if (!dev() || $("player").hidden) return;
  try {
    const s = await api("/api/status/" + dev());
    state = s.state; $("pp").textContent = state === "PLAYING" ? "❚❚" : "▶";
    if (!dragging) { $("seek").max = s.duration || 100; $("seek").value = s.position; $("pos").textContent = fmt(s.position); }
    $("dur").textContent = fmt(s.duration);
    if (s.volume !== undefined && document.activeElement !== $("vol")) $("vol").value = s.volume;
  } catch {}
}, 1500);

wrap(async () => { await loadDevices(); await loadLib(); })();
