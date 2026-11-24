/* Aerrand Developers portal. Plain JavaScript, no build step.
 *
 * Everything here talks to the real API:
 *   /dashboard/...  signed-in session + CSRF token (keys, wallet, notifications, webhooks)
 *   /v1/...         the public API, called with the API key chosen on this page (quotes, errands, tracking)
 * Nothing on screen is made up: numbers, lists and charts all come from those responses.
 */
"use strict";
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const el = h => { const t = document.createElement("template"); t.innerHTML = h.trim(); return t.content.firstChild; };
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const ic = (n, c = "") => `<svg class="i ${c}" aria-hidden="true"><use href="#i-${n}"/></svg>`;
const money = v => "$" + Number(v).toLocaleString("en-CA", {minimumFractionDigits: 2, maximumFractionDigits: 2});
const when = s => s ? new Date(s).toLocaleString([], {month:"short", day:"numeric", hour:"2-digit", minute:"2-digit"}) : "";
const reduced = () => matchMedia("(prefers-reduced-motion:reduce)").matches;
const empty = (icon, title, body, extra = "") => `<div class="empty"><span class="glyph">${ic(icon, "lg")}</span><b>${title}</b><span>${body}</span>${extra}</div>`;

const SCOPES = {"quotes:write":"Price routes","errands:read":"Read deliveries","errands:write":"Book deliveries","errands:cancel":"Cancel deliveries","wallet:read":"Read wallet"};
const PLACES = [
  {label:"Warehouse A, 3040 Deziel Dr, Windsor, ON", lat:42.3149, lng:-83.0364},
  {label:"1823 Wyandotte St E, Windsor, ON", lat:42.3201, lng:-83.0187},
  {label:"3100 Howard Ave, Windsor, ON", lat:42.2789, lng:-82.9912},
  {label:"401 Sunset Ave (University), Windsor, ON", lat:42.3047, lng:-83.0655},
  {label:"1 Riverside Dr W (Waterfront), Windsor, ON", lat:42.3164, lng:-83.0430},
  {label:"2000 Talbot Rd W (College), Windsor, ON", lat:42.2580, lng:-83.0620},
  {label:"Somewhere in Toronto (outside our service area)", lat:43.6532, lng:-79.3832},
];
const PHASES = [["broadcasted","Finding driver"],["accepted","Driver assigned"],["arrived","At pickup"],["picked_up","Picked up"],["in_transit","On the way"],["arrived_dropoff","At drop-off"],["delivered","Delivered"]];
const PROGRESS = {broadcasted:0, accepted:.08, arrived:.16, picked_up:.28, in_transit:.55, arrived_dropoff:.92, delivered:1};
const PAGES = {overview:"Overview", book:"New delivery", track:"Track", keys:"API keys", hooks:"Webhooks", wallet:"Wallet", notes:"Notifications"};
const ENV_HELP = {live:"Live keys book real deliveries and spend wallet money.", test:"Test keys follow every step but never move money."};
const TX = {funds_added:["Funds added","in","in"], errand_charge:["Delivery payment","up",""], errand_refund:["Cancellation refund","undo","back"]};
const NOTE = {errand_created:["box","brand"], errand_delivered:["check","ok"], errand_cancelled:["ban","err"]};
const TIMELINE = {AERRANDER_ASSIGNED:"Driver assigned", AT_PICKUP_LOADING:"At pickup", ITEMS_COLLECTED:"Parcels collected", ROUTE_IN_PROGRESS:"On the way", AT_DROPOFF:"At drop-off", DELIVERED:"Delivered", CANCELLED:"Cancelled"};
const store = {
  get(k){ try { return sessionStorage.getItem(k) } catch { return null } },
  set(k,v){ try { v == null ? sessionStorage.removeItem(k) : sessionStorage.setItem(k,v) } catch {} },
  pget(k){ try { return localStorage.getItem(k) } catch { return null } },
  pset(k,v){ try { localStorage.setItem(k,v) } catch {} }
};
let apiKey = store.get("ak") || "", recent = JSON.parse(store.get("recent") || "[]");
let bookMap = null, trackMap = null, lastFull = null, lastAt = 0, playing = false, scaffoldId = null;
let wallet = null, lastQuote = null, quoteTimer = null, pollTimer = null, noteTimer = null, currentErrand = null, page = "overview", booked = JSON.parse(store.get("nbooked") || "0");
let txs = [], txFilter = "all", keysData = [], keyFilter = "all", notesData = [], noteFilter = "all", hooksCount = null, stopSeq = 0;

/* ---------- theme, sidebar, account menu ---------- */
const root = document.documentElement;
const curTheme = () => root.getAttribute("data-theme") === "light" ? "light" : "dark";
function applyTheme(t) {
  root.setAttribute("data-theme", t);
  const toLight = t === "dark", name = toLight ? "sun" : "moon", label = toLight ? "Light theme" : "Dark theme";
  $("#theme").innerHTML = ic(name) + `<span>${label}</span>`;
  const q = $("#themeQuick"); q.innerHTML = ic(name, "lg"); q.setAttribute("aria-label", "Switch to " + label.toLowerCase());
}
function toggleTheme() {
  const n = curTheme() === "dark" ? "light" : "dark"; store.pset("theme", n); applyTheme(n);
  if (page === "book" && bookMap) renderSlip();                      // redraw map lines in the new colours
  if (lastFull && trackMap) paintTrack(lastFull, currentErrand);
}
applyTheme(curTheme());
$("#theme").onclick = () => { toggleTheme(); closeMenu(); };
$("#themeQuick").onclick = toggleTheme;

function sideLabel() { $("#sideToggle span").textContent = root.getAttribute("data-side") === "mini" ? "Expand sidebar" : "Collapse sidebar"; }
$("#sideToggle").onclick = () => {
  const mini = root.getAttribute("data-side") === "mini";
  if (mini) root.removeAttribute("data-side"); else root.setAttribute("data-side", "mini");
  store.pset("side", mini ? "full" : "mini"); sideLabel(); closeMenu();
  setTimeout(() => { if (bookMap && page === "book") bookMap.refresh(); if (trackMap && page === "track") trackMap.refresh(); drawCharts(); }, 260);
};
sideLabel();
const closeNav = () => document.body.classList.remove("nav-open");
$("#menuBtn").onclick = () => { document.body.classList.add("nav-open"); const b = $('#tabs button[aria-current="page"]'); if (b) b.focus(); };
$("#scrim").onclick = closeNav;
const menu = $("#acctMenu"), acctBtn = $("#acctBtn");
function closeMenu(focus) { if (menu.hidden) return; menu.hidden = true; acctBtn.setAttribute("aria-expanded", "false"); if (focus) acctBtn.focus(); }
acctBtn.onclick = () => { const open = menu.hidden; menu.hidden = !open; acctBtn.setAttribute("aria-expanded", String(open)); if (open) menu.querySelector("button").focus(); };
document.addEventListener("click", e => { if (!e.target.closest("#acctMenu") && !e.target.closest("#acctBtn")) closeMenu(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") { closeMenu(true); closeNav(); } });
menu.addEventListener("keydown", e => {
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return; e.preventDefault();
  const items = [...menu.querySelectorAll("button")].filter(b => b.offsetParent), i = items.indexOf(document.activeElement);
  items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
});

/* ---------- http ---------- */
const csrf = () => (document.cookie.split("; ").find(c => c.startsWith("csrftoken=")) || "").split("=")[1] || "";
async function call(url, {method="GET", body, key, idem} = {}) {
  const h = {"Accept":"application/json"};
  if (body !== undefined) h["Content-Type"] = "application/json";
  if (key) h["Authorization"] = "Bearer " + key; else if (method !== "GET") h["X-CSRFToken"] = csrf();
  if (idem) h["Idempotency-Key"] = idem;
  let r; try { r = await fetch(url, {method, headers:h, credentials:"same-origin", body: body !== undefined ? JSON.stringify(body) : undefined}); }
  catch { const e = new Error("Can't reach the server. Check that it is still running."); e.code = "offline"; throw e; }
  let data = null; try { data = await r.json(); } catch {}
  if (!r.ok) { const e = new Error((data && data.error && data.error.message) || r.statusText); e.code = data && data.error && data.error.code; e.status = r.status; e.data = data; throw e; }
  return data;
}
const dash = async (p, o) => { try { return await call("/dashboard/" + p, o); } catch (e) { if (e.status === 401 && p !== "login") { endSession("Your session ended. Sign in again."); } throw e; } };
const v1 = async (p, o={}) => {
  if (!apiKey) { const e = new Error("Choose an API key first."); e.code = "no_key"; throw e; }
  try { return await call("/v1/" + p, {...o, key: apiKey}); }
  catch (e) { if (e.code === "invalid_api_key") { dropKey(); } throw e; }
};
/* the test-mode driver tools: only exist when the server runs with DEBUG on */
const simulate = async (id, body) => {
  try { return await call("/portal/simulate/" + id, {method:"POST", body}); }
  catch (e) { if (e.status === 404 && e.code === "not_found") e.message = "Test tools are switched off on this server."; throw e; }
};
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());

/* ---------- small ui helpers ---------- */
function toast(msg, kind="ok", action) {
  const t = el(`<div class="toast ${kind === "bad" ? "bad" : ""}">${ic(kind === "bad" ? "alert" : "check")}<div class="grow">${esc(msg)}</div></div>`);
  if (action) { const b = el(`<button class="btn sm act">${esc(action.label)}</button>`); b.onclick = () => { action.fn(); t.remove(); }; t.appendChild(b); }
  const x = el(`<button class="btn ghost icon sm x" aria-label="Dismiss">${ic("x")}</button>`); x.onclick = () => t.remove(); t.appendChild(x);
  const box = $("#toasts"); box.appendChild(t); while (box.children.length > 3) box.firstChild.remove(); setTimeout(() => t.remove(), kind === "bad" ? 7000 : 4000);
}
const fail = e => {
  if (e.code === "no_key" || e.code === "invalid_api_key") return toast(e.code === "no_key" ? "Choose an API key first." : "That key is no longer valid. Create or choose another.", "bad", {label:"API keys", fn:() => go("keys")});
  if (e.status === 401) return;
  const det = e.data && e.data.error && e.data.error.details;
  const first = det && Object.entries(det).map(([k, v]) => [k, [].concat(v)[0]]).find(([, v]) => typeof v === "string");   // only plain-text hints
  toast((e.message || "Something went wrong.") + (first ? ` ${first[0].replace(/_/g, " ")}: ${first[1]}` : ""), "bad");
};
const guard = fn => async (...a) => { try { return await fn(...a); } catch (e) { fail(e); } };
const busy = async (btn, fn) => { if (!btn) return fn(); btn.classList.add("busy"); btn.setAttribute("aria-busy", "true"); try { return await fn(); } finally { btn.classList.remove("busy"); btn.removeAttribute("aria-busy"); } };
async function copy(text, label="Copied.") {
  try { await navigator.clipboard.writeText(text); toast(label); return true; }
  catch {
    const ta = el('<textarea style="position:fixed;opacity:0"></textarea>'); ta.value = text; document.body.appendChild(ta); ta.select();
    let ok = false; try { ok = document.execCommand("copy"); } catch {} ta.remove();
    toast(ok ? label : "Select the text and copy it yourself.", ok ? "ok" : "bad"); return ok;
  }
}
/* a secret that is shown once: masked until the user asks to see it, with copy feedback on the button */
function secretBox(host, value, title, note, lead, extra = "") {
  const masked = value.slice(0, lead) + "•".repeat(Math.max(8, Math.min(28, value.length - lead)));
  host.innerHTML = `<div class="secret"><b>${esc(title)}</b><div class="sm muted" style="margin-top:2px">${esc(note)}</div>
    <span class="val" style="user-select:none">${esc(masked)}</span>
    <div class="row" style="gap:8px"><button type="button" class="btn sm" data-a="copy">${ic("copy")}<span>Copy</span></button><button type="button" class="btn sm ghost" data-a="show" aria-pressed="false">${ic("eye")}<span>Show</span></button>${extra}</div></div>`;
  const val = host.querySelector(".val"), show = host.querySelector('[data-a="show"]'), cp = host.querySelector('[data-a="copy"]');
  show.onclick = () => { const on = show.getAttribute("aria-pressed") !== "true"; show.setAttribute("aria-pressed", String(on));
    val.textContent = on ? value : masked; val.style.userSelect = on ? "all" : "none"; show.innerHTML = ic(on ? "eye-off" : "eye") + `<span>${on ? "Hide" : "Show"}</span>`; };
  cp.onclick = async () => { if (await copy(value, title.includes("secret") ? "Secret copied." : "Key copied.")) { cp.querySelector("span").textContent = "Copied"; setTimeout(() => { const s = cp.querySelector("span"); if (s) s.textContent = "Copy"; }, 1600); } };
}
function setFilter(group, value) { $$(`#${group} button`).forEach(b => b.setAttribute("aria-pressed", String(b.dataset.f === value))); }
const dlg = $("#dlg");
function ask({title, body="", ok="OK", danger=false, input=null}) {
  return new Promise(res => {
    $("#dlgT").textContent = title; $("#dlgB").textContent = body;
    const y = $("#dlgYes"); y.textContent = ok; y.className = "btn " + (danger ? "danger solid" : "primary");
    const box = $("#dlgI"); box.classList.toggle("hide", !input);
    if (input) { $("#dlgL").textContent = input.label; $("#dlgIn").value = ""; $("#dlgIn").placeholder = input.placeholder || ""; }
    const done = v => { dlg.close(); res(v); };
    $("#dlgNo").onclick = () => done(null);
    $("#dlgForm").onsubmit = ev => { ev.preventDefault(); done(input ? $("#dlgIn").value.trim() || null : true); };
    dlg.oncancel = () => res(null);
    dlg.showModal(); if (input) $("#dlgIn").focus(); else $("#dlgNo").focus();
  });
}

/* ---------- the API key this page uses ---------- */
const keyKind = () => apiKey.startsWith("ak_test_") ? "test" : "live";
function renderKeyChip() {
  $("#keyChip").innerHTML = apiKey ? `<span class="dot ${keyKind()}"></span><span>${keyKind() === "live" ? "Live" : "Test"} key</span><code>${esc(apiKey.slice(0, 15))}…</code>`
                                   : `<span class="dot"></span><span>No API key selected</span>`;
}
function useKey(k) { apiKey = k; store.set("ak", k); renderKeyChip(); setConn(); }
function dropKey() { apiKey = ""; store.set("ak", null); renderKeyChip(); setConn(); }
$("#keyChip").onclick = guard(async () => { await pasteKey(); });
async function pasteKey() { const k = await ask({title:"Use an API key", body:"Paste a key you have saved. It stays in this browser tab only.", ok:"Use key", input:{label:"API key", placeholder:"ak_live_…"}}); if (k) { useKey(k); toast("Key set for this tab."); testKey(true); renderKeys(); } }
function setConn(state, msg) {
  const c = $("#conn"); if (!c) return; let cls = "alert", icon = "info", html = "Key selected. Test the connection to be sure it works.";
  if (!apiKey) html = "No key selected yet. Create one, or paste a key you saved.";
  else if (state === "ok") { cls += " ok"; icon = "check"; html = msg; }
  else if (state === "bad") { cls += " err"; icon = "alert"; html = msg; }
  c.className = cls; c.innerHTML = ic(icon) + `<div>${html}</div>`; updateSteps();
}
const testKey = guard(async (quiet) => {
  if (!apiKey) return quiet || toast("Choose an API key first.", "bad");
  try { const m = await call("/v1/me", {key: apiKey});
    setConn("ok", `Connected as <b>${esc(m.business.name)}</b> with a ${esc(m.key.environment)} key.<div class="xs" style="margin-top:3px">Can: ${esc(m.key.scopes.map(s => SCOPES[s] || s).join(", "))}</div>`); if (!quiet) toast("Connected."); }
  catch (e) { if (e.code === "invalid_api_key") { dropKey(); setConn(); if (!quiet) fail(e); else toast("The saved key was revoked, so we cleared it.", "bad", {label:"API keys", fn:() => go("keys")}); } else if (!quiet) throw e; }
});
/* "Get started" ticks itself off from real state: keys on the account, the key in this tab, bookings, endpoints */
function updateSteps() {
  const list = $("#steps"); if (!list) return;
  const done = {key: keysData.some(k => k.status === "active"), use: !!apiKey, book: booked > 0, hook: hooksCount > 0};
  let n = 0; $$("#steps li").forEach(li => { const d = !!done[li.dataset.step]; li.classList.toggle("done", d); if (d) n++; });
  $("#stepsDone").textContent = `${n} of 4 done`;
}

/* ---------- sign in / out ---------- */
function loginError(msg) { const b = $("#loginErr"); b.querySelector("div").textContent = msg || ""; b.classList.toggle("hide", !msg); $("#u").setAttribute("aria-invalid", String(!!msg)); $("#p").setAttribute("aria-invalid", String(!!msg)); }
function showLogin(msg) {
  stopPoll(); clearInterval(noteTimer); closeNav(); closeMenu(); $("#app").classList.add("hide"); $("#login").classList.remove("hide");
  document.title = "Sign in · Aerrand Developers"; loginError(msg); setTimeout(() => $("#u").focus(), 30);
}
function endSession(msg) { store.set("biz", null); showLogin(msg); }
async function enter(biz) {
  $("#login").classList.add("hide"); $("#app").classList.remove("hide");
  const hr = new Date().getHours();
  $("#bizName").textContent = biz.name; $("#greet").textContent = (hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening") + ", " + biz.name;
  $("#avatar").textContent = (biz.name || "A").trim().charAt(0).toUpperCase();
  $("#bizStatus").textContent = biz.approval_status === "approved" ? "Approved account" : "Awaiting approval";
  renderKeyChip(); setConn();
  await Promise.all([loadWallet(), loadKeys(), loadNotes(true), loadHooks().catch(() => {})]);
  clearInterval(noteTimer); noteTimer = setInterval(() => loadNotes(true), 20000);
  const t = (location.hash || "").slice(1); go(PAGES[t] ? t : "overview", true);
  if (apiKey) testKey(true);
  loadActive();
}
$("#showPw").onclick = () => { const p = $("#p"), s = p.type === "password", b = $("#showPw"); p.type = s ? "text" : "password"; b.innerHTML = ic(s ? "eye-off" : "eye"); b.setAttribute("aria-pressed", String(s)); b.setAttribute("aria-label", s ? "Hide password" : "Show password"); };
$("#loginForm").addEventListener("submit", async ev => {
  ev.preventDefault(); loginError("");
  if (!$("#u").value.trim() || !$("#p").value) return loginError("Enter your username and password.");
  await busy($("#loginBtn"), async () => {
    try { const r = await call("/dashboard/login", {method:"POST", body:{username:$("#u").value.trim(), password:$("#p").value}}); $("#p").value = "";
      store.set("biz", JSON.stringify(r.business)); await enter(r.business); }
    catch (e) { loginError(e.code === "invalid_credentials" ? "That username or password is wrong. Check both and try again." : e.message); }
  });
});
$("#demoFill").onclick = () => { $("#u").value = "acme"; $("#p").value = "Welcome123!"; $("#loginBtn").click(); };
$("#logout").onclick = guard(async () => { closeMenu(); await call("/dashboard/logout", {method:"POST", body:{}}); dropKey(); store.set("biz", null); store.set("recent", null); recent = []; history.replaceState(null, "", location.pathname); showLogin(); });
if (reduced()) { const s = $("#artSvg"); if (s && s.pauseAnimations) s.pauseAnimations(); }

/* ---------- navigation ---------- */
function go(t, quiet) {
  page = t; closeNav();
  $$("#tabs button").forEach(b => b.dataset.t === t ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current"));
  $$("#main > section").forEach(s => s.hidden = s.id !== "t-" + t);
  document.title = PAGES[t] + " · Aerrand Developers"; $("#pageTitle").textContent = PAGES[t];
  if (!quiet && location.hash !== "#" + t) history.replaceState(null, "", "#" + t);
  if (t !== "track") stopPoll();
  if (t === "book") { $("#noKey").classList.toggle("hide", !!apiKey); if (!bookMap) bookMap = KPMap.create($("#bmap"), {compact:true}); if (!$("#stops").children.length || !$("#bookDone").classList.contains("hide")) { initBook(); } renderSlip(); bookMap.refresh(); }
  if (t === "track") { renderRecent(); if (currentErrand) { loadTrack(true); if (trackMap) setTimeout(() => trackMap.refresh(), 50); } else if (!$("#trackOut").children.length) loadTrack(true); }
  if (t === "notes") loadNotes();
  if (t === "hooks") loadHooks().catch(fail);
  if (t === "keys") loadKeys().catch(fail);
  if (t === "wallet") loadWallet().catch(fail);
  if (t === "overview") { loadWallet().catch(fail); loadKeys().catch(fail); loadActive(); }
  scrollTo({top:0});
  const sec = $("#t-" + t); if (sec && !quiet) { sec.classList.remove("page-in"); void sec.offsetWidth; sec.classList.add("page-in"); }
  drawCharts();
  const h = $("#t-" + t + " h1"); if (h && !quiet) { h.tabIndex = -1; h.focus({preventScroll:true}); }
}
$("#tabs").onclick = e => { const b = e.target.closest("button[data-t]"); if (b) go(b.dataset.t); };
document.addEventListener("click", e => {
  const g = e.target.closest("[data-go]"); if (g) go(g.dataset.go);
  const a = e.target.closest('a[href^="#"]'); if (a && PAGES[a.getAttribute("href").slice(1)]) { e.preventDefault(); go(a.getAttribute("href").slice(1)); }
  const tp = e.target.closest("[data-topup]"); if (tp) topup(+tp.dataset.topup, tp);
  const c = e.target.closest("[data-copy]"); if (c) copy(c.dataset.copy, c.dataset.copied || "Copied.");
  const t = e.target.closest("[data-track]"); if (t) openTrack(t.dataset.track);
});
addEventListener("hashchange", () => { const t = location.hash.slice(1); if (PAGES[t] && !$("#app").classList.contains("hide") && t !== page) go(t, true); });

/* ---------- wallet (overview cards, wallet page) ---------- */
function txRow(t, short) {
  const n = Number(t.amount), k = TX[t.type] || [t.type.replace(/_/g, " "), "wallet", ""];
  return `<tr><td><span class="txkind"><span class="dot ${k[2]}">${ic(k[1])}</span>${esc(k[0])}</span></td><td class="muted ${short ? "hide-sm" : ""}">${esc(when(t.created_at))}</td>
    <td class="r num ${n >= 0 ? "plus" : "minus"}">${n >= 0 ? "+" : "−"}${money(Math.abs(n))}</td><td class="r num muted ${short ? "hide-sm" : ""}">${money(t.balance_after)}</td></tr>`;
}
const txEmpty = (title, body) => `<tr><td colspan="4">${empty("wallet", title, body)}</td></tr>`;
function renderTx() {
  const list = txFilter === "all" ? txs : txs.filter(t => t.type === txFilter);
  $("#txAll").innerHTML = list.length ? list.map(t => txRow(t, false)).join("")
    : txEmpty(txs.length ? "Nothing of this type" : "No wallet activity yet", txs.length ? "Choose another filter to see the rest." : "Add funds or book a delivery and it shows here.");
}
async function loadWallet() {
  const w = await dash("wallet"); wallet = Number(w.balance); txs = w.transactions || [];
  const fig = `${money(w.balance)}<small>${esc(w.currency)}</small>`; $("#walletBig").innerHTML = fig; $("#walletBig2").innerHTML = fig;
  $("#stDel").textContent = booked;
  $("#txRows").innerHTML = txs.length ? txs.slice(0, 5).map(t => txRow(t, true)).join("") : txEmpty("No wallet activity yet", "Add funds or book a delivery and it shows here.");
  renderTx(); drawCharts(); updateSteps();
  if (page === "book") renderSlip();
}
const topup = guard(async (amt, btn) => busy(btn, async () => { await dash("wallet", {method:"POST", body:{amount:amt}}); await loadWallet(); toast(`Added ${money(amt)} to your wallet.`); }));
$("#txFilter").onclick = e => { const b = e.target.closest("button[data-f]"); if (!b) return; txFilter = b.dataset.f; setFilter("txFilter", txFilter); renderTx(); };
$("#testKey").onclick = () => testKey();
$("#setKey").onclick = guard(pasteKey);

/* Balance chart. One point per transaction (the balance after it), oldest on the left. Stepped, because the balance
   only changes when a transaction happens. Drawn from the same list as the table, so the two always agree. */
function drawChart(box, hint) {
  if (!box || !box.offsetParent) return;
  const pts = txs.slice().reverse().map(t => ({v: Number(t.balance_after), at: t.created_at})).filter(p => isFinite(p.v));
  if (pts.length < 2) { box.innerHTML = hint ? `<p class="sm muted" style="padding:20px">The chart appears once there are two or more transactions.</p>` : ""; return; }
  const W = Math.max(260, box.clientWidth - 40), H = 150, top = 12, bot = 24, lo0 = Math.min(...pts.map(p => p.v)), hi0 = Math.max(...pts.map(p => p.v));
  const pad = (hi0 - lo0) * .12 || 1, lo = Math.max(0, lo0 - pad), hi = hi0 + pad;
  const L = 62, x = i => L + i / (pts.length - 1) * (W - L), y = v => top + (1 - (v - lo) / (hi - lo)) * (H - top - bot);
  let d = `M${L} ${y(pts[0].v).toFixed(1)}`; pts.forEach((p, i) => { if (i) d += ` H${x(i).toFixed(1)} V${y(p.v).toFixed(1)}`; });
  const ticks = [hi0, (hi0 + lo0) / 2, lo0].filter((v, i, a) => a.indexOf(v) === i);
  box.innerHTML = `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Wallet balance after each of the last ${pts.length} transactions, from ${money(pts[0].v)} to ${money(pts[pts.length - 1].v)}">
      ${ticks.map(v => `<line class="grid" x1="${L}" x2="${W}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/><text class="ax" x="${L - 8}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${money(v)}</text>`).join("")}
      <path class="ar" d="${d} V${H - bot} H${L} Z"/><path class="ln" d="${d}"/>
      <text class="ax" x="${L}" y="${H - 6}">${esc(when(pts[0].at))}</text><text class="ax" x="${W}" y="${H - 6}" text-anchor="end">${esc(when(pts[pts.length - 1].at))}</text>
      <line class="cur" y1="${top}" y2="${H - bot}" hidden/><circle class="pt" r="4" hidden/>
    </svg><div class="tipbox" hidden></div></div>`;
  const svg = box.querySelector("svg"), cur = svg.querySelector(".cur"), pt = svg.querySelector(".pt"), tip = box.querySelector(".tipbox");
  const showAt = i => { const px = x(i), py = y(pts[i].v), r = svg.getBoundingClientRect(), k = r.width / W;
    cur.setAttribute("x1", px); cur.setAttribute("x2", px); pt.setAttribute("cx", px); pt.setAttribute("cy", py); cur.removeAttribute("hidden"); pt.removeAttribute("hidden");
    tip.hidden = false; tip.innerHTML = `<b>${money(pts[i].v)}</b>${esc(when(pts[i].at))}`;
    tip.style.left = Math.min(Math.max(px * k + 20, 70), r.width - 30) + "px"; tip.style.top = (py * (r.height / H) + 6) + "px"; };
  svg.addEventListener("pointermove", e => { const r = svg.getBoundingClientRect(); showAt(Math.max(0, Math.min(pts.length - 1, Math.round(((e.clientX - r.left) / r.width * W - L) / (W - L) * (pts.length - 1))))); });
  svg.addEventListener("pointerleave", () => { cur.setAttribute("hidden", ""); pt.setAttribute("hidden", ""); tip.hidden = true; });
}
function drawCharts() { drawChart($("#ovChart"), false); drawChart($("#wChart"), true); }
let rz; addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(drawCharts, 150); });

/* ---------- recent deliveries (overview) ---------- */
async function loadActive() {
  const p = $("#activePanel"); if (!p) return;
  if (!apiKey || !recent.length) { p.hidden = true; return; }
  const rs = await Promise.allSettled(recent.slice(0, 6).map(r => call("/v1/errands/" + encodeURIComponent(r.id), {key: apiKey})));
  const rows = rs.map((x, i) => x.status === "fulfilled" ? {r: recent[i], f: x.value} : null).filter(Boolean);
  if (!rows.length) { p.hidden = true; return; }
  const term = f => f.status === "delivered" || f.status === "cancelled";
  rows.sort((a, b) => term(a.f) - term(b.f));
  $("#activeRows").innerHTML = rows.map(({r, f}) => { const pct = Math.round((PROGRESS[f.status] ?? 0) * 100), c = f.status === "delivered" ? "ok" : f.status === "cancelled" ? "err" : "brand";
    return `<div class="item"><span class="glyph ${c}">${ic(f.status === "delivered" ? "check" : f.status === "cancelled" ? "ban" : "truck")}</span>
      <div class="grow"><div class="title"><b>${esc(r.name || "Delivery")}</b><span class="badge ${c}">${esc(f.status.replace(/_/g, " "))}</span></div><div class="sm muted">${esc(r.label)}</div>
      ${term(f) ? "" : `<div class="mini" style="max-width:220px;margin-top:8px" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}" aria-label="Delivery progress"><i style="width:${pct}%"></i></div>`}</div>
      <div class="acts"><button class="btn sm" data-track="${esc(r.id)}">Track</button></div></div>`; }).join("");
  p.hidden = false;
}

/* ---------- keys ---------- */
$("#kScopes").innerHTML = Object.entries(SCOPES).map(([k, v]) => `<label class="check" title="${k}"><input type="checkbox" value="${k}" checked><span>${v}</span></label>`).join("");
$$('input[name="kenv"]').forEach(r => r.onchange = () => $("#envHelp").textContent = ENV_HELP[r.value]);
function renderKeys() {
  const list = keysData.filter(k => keyFilter === "all" || (keyFilter === "active") === (k.status === "active"));
  $("#keyRows").innerHTML = list.length ? list.map(k => {
    const on = k.status === "active", inUse = on && apiKey && apiKey.slice(0, 15) === k.prefix;
    return `<div class="item ${on ? "" : "off"}"><span class="glyph ${on ? "brand" : ""}">${ic("key")}</span>
      <div class="grow"><div class="title"><b>${esc(k.name)}</b><span class="badge ${k.environment === "live" ? "ok" : "info"}">${esc(k.environment)}</span>${on ? "" : '<span class="badge err">Revoked</span>'}${inUse ? '<span class="badge brand">In use on this page</span>' : ""}</div>
        <div class="mono muted" style="margin-top:2px">${esc(k.prefix)}${"•".repeat(12)}</div><div class="xs faint" style="margin-top:2px">Created ${esc(when(k.created_at))}${k.revoked_at ? ", revoked " + esc(when(k.revoked_at)) : ""}</div></div>
      <div class="acts">${on ? `<button class="btn sm danger" data-revoke="${esc(k.id)}" data-name="${esc(k.name)}">Revoke</button>` : ""}</div></div>`;
  }).join("") : keysData.length ? empty("key", "No keys match this filter", "Choose another filter to see the rest.")
              : empty("key", "No keys yet", "Create your first key to start calling the API.");
}
async function loadKeys() {
  const r = await dash("api-keys"); keysData = r.data; const act = keysData.filter(k => k.status === "active").length;
  $("#stKeys").textContent = act; $("#stKeysSub").textContent = keysData.length ? `${keysData.length - act} revoked` : "None created yet";
  renderKeys(); updateSteps();
}
$("#keyFilter").onclick = e => { const b = e.target.closest("button[data-f]"); if (!b) return; keyFilter = b.dataset.f; setFilter("keyFilter", keyFilter); renderKeys(); };
$("#keyRows").onclick = guard(async e => {
  const b = e.target.closest("[data-revoke]"); if (!b) return;
  if (!await ask({title:`Revoke “${b.dataset.name}”?`, body:"Anything using this key stops working on its very next request. This can't be undone.", ok:"Revoke key", danger:true})) return;
  await busy(b, async () => { await dash("api-keys/" + b.dataset.revoke, {method:"DELETE"}); toast("Key revoked."); await loadKeys(); });
});
$("#keyForm").addEventListener("submit", guard(async ev => {
  ev.preventDefault(); const name = $("#kName").value.trim();
  if (!name) { $("#kName").classList.add("err"); $("#kName").focus(); return toast("Give the key a name so you can recognise it later.", "bad"); }
  $("#kName").classList.remove("err");
  const scopes = $$("#kScopes input:checked").map(i => i.value);
  if (!scopes.length) return toast("Pick at least one permission for this key.", "bad");
  await busy($("#keyBtn"), async () => {
    const k = await dash("api-keys", {method:"POST", body:{name, environment:$('input[name="kenv"]:checked').value, scopes}});
    secretBox($("#newKey"), k.key, "Copy your key now", k.notice || "It is shown once and can't be recovered.", 15, `<button type="button" class="btn sm primary" id="useNew">Use on this page</button>`);
    $("#useNew").onclick = async () => { useKey(k.key); toast("This page now uses the new key."); testKey(true); renderKeys(); };
    $("#kName").value = ""; toast("Key created."); await loadKeys();
  });
}));

/* ---------- new delivery ---------- */
const MAX_STOPS = 5;
function setBookStep(n) { $$("#bookSteps li").forEach(li => { const s = +li.dataset.s; li.className = s < n ? "done" : s === n ? "on" : ""; if (s === n) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current"); }); }
function initBook() {
  $("#pickup").innerHTML = PLACES.slice(0, 6).map((p, i) => `<option value="${i}">${esc(p.label)}</option>`).join("");
  $("#bookDone").classList.add("hide"); $("#bookForm").classList.remove("hide"); $("#stops").innerHTML = ""; addStop(); resetQuote();
}
const placeOpts = () => PLACES.slice(1).map((p, i) => `<option value="${i + 1}">${esc(p.label)}</option>`).join("");
function addStop() {
  const n = $("#stops").children.length; if (n >= MAX_STOPS) return toast("A route holds at most 5 drop-offs.", "bad");
  const i = n + 1, u = "s" + (++stopSeq);
  const qty = (c, v, lbl) => `<div class="w2 q"><label class="label" for="${u}-${c}">${lbl}</label><div class="qty"><button type="button" data-q="-1" aria-label="Fewer ${lbl.toLowerCase()} parcels">−</button><input id="${u}-${c}" class="s-${c}" type="number" min="0" max="30" value="${v}" inputmode="numeric"><button type="button" data-q="1" aria-label="More ${lbl.toLowerCase()} parcels">+</button></div></div>`;
  const d = el(`<div class="card stop"><span class="node">${i}</span><div class="card-b"><div class="stop-h"><h3>Drop-off ${i}</h3>${i > 1 ? `<button type="button" class="btn sm ghost rm">${ic("trash")}Remove</button>` : ""}</div>
    <div class="fgrid"><div class="w6"><label class="label" for="${u}-place">Address</label><select id="${u}-place" class="s-place">${placeOpts()}</select></div>
      <div class="w3"><label class="label" for="${u}-name">Receiver</label><input id="${u}-name" class="s-name" value="Customer ${i}" autocomplete="off"></div>
      <div class="w3"><label class="label" for="${u}-phone">Phone</label><input id="${u}-phone" class="s-phone" value="+1519555018${i}" inputmode="tel" autocomplete="off"></div>
      ${qty("small", i === 1 ? 2 : 1, "Small")}${qty("medium", i === 1 ? 1 : 0, "Medium")}${qty("large", 0, "Large")}</div></div></div>`);
  d.querySelector(".s-place").value = String(Math.min(i, PLACES.length - 2));
  const rm = d.querySelector(".rm"); if (rm) rm.onclick = () => { d.remove(); relabel(); resetQuote(); };
  $("#stops").appendChild(d); relabel(); resetQuote();
}
function relabel() {
  $$("#stops .stop").forEach((s, i) => { s.querySelector(".node").textContent = i + 1; s.querySelector("h3").textContent = "Drop-off " + (i + 1); });
  const n = $("#stops").children.length; $("#stopCount").textContent = `${n} of ${MAX_STOPS} drop-offs`; $("#addStop").disabled = n >= MAX_STOPS;
}
$("#addStop").onclick = addStop;
$("#stops").addEventListener("click", e => { const q = e.target.closest("[data-q]"); if (!q) return; const i = q.parentElement.querySelector("input"); i.value = Math.max(0, Math.min(30, (+i.value || 0) + +q.dataset.q)); resetQuote(); });
$("#stops").addEventListener("input", () => resetQuote());
$("#pickup").onchange = () => resetQuote();
function route() {
  const p = PLACES[+$("#pickup").value];
  const stops = $$("#stops .stop").map(s => {
    const pl = PLACES[+s.querySelector(".s-place").value], parcels = {};
    for (const k of ["small","medium","large"]) { const n = Math.max(0, parseInt(s.querySelector(".s-" + k).value, 10) || 0); if (n > 0) parcels[k] = n; }
    return {pl, parcels, name:s.querySelector(".s-name").value.trim() || "Receiver", phone:s.querySelector(".s-phone").value.trim(), node:s};
  });
  return {p, stops};
}
const parcelText = p => Object.entries(p).map(([k, v]) => `${v} ${k}`).join(", ") || "no parcels";
function resetQuote() { lastQuote = null; clearInterval(quoteTimer); if (page === "book") renderSlip(); }
function renderSlip() {
  if (!$("#slipStops") || !$("#pickup").options.length) return; const {p, stops} = route();
  $("#slipStops").innerHTML = `<div class="sumstop"><span class="node a">A</span><div>${esc(p.label)}<small>Pickup</small></div></div>` +
    stops.map((s, i) => `<div class="sumstop"><span class="node">${i + 1}</span><div>${esc(s.pl.label)}<small>${esc(s.name)}, ${esc(parcelText(s.parcels))}</small></div></div>`).join("");
  if (bookMap) bookMap.setRoute([{lat:p.lat, lng:p.lng, kind:"pickup", label:"A", title:"Pickup"}].concat(stops.map((s, i) => ({lat:s.pl.lat, lng:s.pl.lng, kind:"stop", label:String(i + 1), title:s.pl.label}))));
  const box = $("#slipPrice"); const q = lastQuote && lastQuote.q;
  if ($("#bookDone").classList.contains("hide")) setBookStep(q ? 2 : 1);
  if (!q) { box.innerHTML = `<h2>Price</h2><p class="sm muted" style="margin-top:6px">Get a price for this route. Nothing is charged until you book.</p><button class="btn primary lg block" id="slipBtn" style="margin-top:14px">Get price</button>`; $("#slipBtn").onclick = e => getQuote(e.currentTarget); return; }
  const short = wallet !== null && wallet < q.chargeTotal, need = short ? Math.ceil((q.chargeTotal - wallet) / 50) * 50 : 0;
  box.innerHTML = `<div class="row" style="margin-bottom:10px"><h2 class="grow">Price</h2><span class="badge plain" title="This price is held until the timer ends">Held for <b id="qLeft" class="num" style="margin-left:4px"></b></span></div>
    <div class="line muted"><span>${esc(q.routeKm)} km, ${esc(q.totalParcels)} parcels</span><span>${esc(q.recommendedVehicle)}</span></div>
    <div class="line"><span>Route price</span><span>${money(q.routePrice)}</span></div><div class="line"><span>HST (${Math.round(q.hstRate * 100)}%)</span><span>${money(q.hst)}</span></div>
    <div class="line total"><b>Total</b><span>${money(q.chargeTotal)}</span></div>
    <div class="line muted"><span>Wallet balance</span><span>${money(wallet ?? 0)}</span></div>
    ${short ? `<div class="alert warn" style="margin-top:12px">${ic("alert")}<div><b>Your wallet is short by ${money(q.chargeTotal - wallet)}.</b> Add funds before you book.<div style="margin-top:8px"><button class="btn sm" id="slipTop">${ic("plus")}Add $${need}</button></div></div></div>` : ""}
    <button class="btn primary lg block" id="slipBtn" style="margin-top:14px">Book and pay ${money(q.chargeTotal)}</button>
    <p class="xs faint mono" style="margin-top:10px">Quote ${esc(q.quote_id)}</p>`;
  $("#slipBtn").onclick = e => book(e.currentTarget);
  const st = $("#slipTop"); if (st) st.onclick = e => topup(need, e.currentTarget);
  const left = () => { const s = Math.max(0, Math.round((new Date(q.expires_at) - Date.now()) / 1000)); const n = $("#qLeft"); if (n) n.textContent = Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); if (!s) { clearInterval(quoteTimer); resetQuote(); toast("That price expired. Get a new one.", "bad"); } };
  left(); clearInterval(quoteTimer); quoteTimer = setInterval(left, 1000);
}
const getQuote = guard(async (btn) => {
  if (!apiKey) { $("#noKey").classList.remove("hide"); throw Object.assign(new Error("Choose an API key first."), {code:"no_key"}); }
  const {p, stops} = route(); let bad = false;
  stops.forEach(s => { const none = !Object.keys(s.parcels).length; s.node.querySelectorAll(".s-small,.s-medium,.s-large").forEach(i => i.classList.toggle("err", none)); bad = bad || none; });
  if (bad) throw new Error("Each drop-off needs at least one parcel.");
  await busy(btn, async () => {
    const body = {pickup:{lat:p.lat, lng:p.lng}, stops:stops.map(s => ({lat:s.pl.lat, lng:s.pl.lng, parcels:s.parcels}))};
    const q = await v1("quotes", {method:"POST", body}); lastQuote = {q, body}; await loadWallet().catch(() => {}); renderSlip();
  });
});
const book = guard(async (btn) => busy(btn, async () => {
  const {p, stops} = route(); const ref = "WEB-" + Date.now().toString(36).toUpperCase();
  const body = {reference:ref, quote_id:lastQuote.q.quote_id, vehicle_type:lastQuote.q.recommendedVehicle === "motorcycle" ? "car" : lastQuote.q.recommendedVehicle,
    pickup:{label:p.label, lat:String(p.lat), lng:String(p.lng), contact:{name:"Warehouse A", phone_number:"+15195550137", preference:"pickup"}}, payment:{method:"wallet"}};
  // a route of one stop is still a route, so it always goes in dropoffs[]
  body.dropoffs = stops.map((s, i) => ({reference:ref + "-" + (i + 1), label:s.pl.label, lat:String(s.pl.lat), lng:String(s.pl.lng), parcels:s.parcels, contact:{name:s.name, phone_number:s.phone, preference:"leave_at_door"}}));
  const r = await v1("errands", {method:"POST", body, idem:uid()});
  const list = r.stops || [r]; clearInterval(quoteTimer); lastQuote = null;
  list.forEach(s => recent.unshift({id:s.errand_id, label:s.label || (s.dropoff && s.dropoff.label) || "Delivery", name:s.receiver_name || (s.dropoff && s.dropoff.contact && s.dropoff.contact.name) || ""}));
  recent = recent.slice(0, 12); store.set("recent", JSON.stringify(recent)); booked += list.length; store.set("nbooked", JSON.stringify(booked));
  const total = r.pricing ? r.pricing.charge_total : r.charge_total;
  $("#bookForm").classList.add("hide"); const d = $("#bookDone"); d.classList.remove("hide"); setBookStep(4);
  d.innerHTML = `<div class="card"><div class="card-b"><div class="done-head"><div class="ok-mark"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></div>
      <div class="grow"><h2 style="font-size:17px">Delivery booked</h2><p class="muted">${list.length} stop${list.length > 1 ? "s" : ""}. ${money(total)} was paid from your wallet.</p></div>
      <button class="btn" id="again">${ic("plus")}Book another</button></div></div></div>
    <div class="card"><div class="card-h"><h2>Delivery codes</h2><span class="xs muted">Give each receiver their code. The driver asks for it at the door.</span></div><div class="list">
    ${list.map(s => `<div class="item"><span class="glyph brand">${ic("pin")}</span><div class="grow"><div class="title"><b>${esc(s.receiver_name || "Receiver")}</b><span class="badge">${esc(String(s.status).replace(/_/g, " "))}</span></div><div class="sm muted">${esc(s.label || "")}</div>
        <div style="margin-top:10px"><span class="ticket"><span><small>Delivery code</small><span class="c">${esc(s.delivery_code)}</span></span><button class="btn sm icon" data-copy="${esc(s.delivery_code)}" data-copied="Code copied." aria-label="Copy delivery code">${ic("copy")}</button></span></div></div>
      <div class="acts"><button class="btn sm primary" data-track="${esc(s.errand_id)}">Track</button></div></div>`).join("")}</div></div>`;
  $("#again").onclick = () => { initBook(); renderSlip(); if (bookMap) bookMap.refresh(); };
  toast("Delivery booked."); loadWallet(); loadNotes(true); scrollTo({top:0});
}));

/* ---------- track ---------- */
const sleep = ms => new Promise(r => setTimeout(r, ms));
const agoText = ms => ms < 4000 ? "just now" : ms < 60000 ? Math.round(ms / 1000) + " s ago" : Math.round(ms / 60000) + " min ago";
function renderRecent() {
  $("#recentList").innerHTML = recent.length ? recent.map(r => `<button data-pick="${esc(r.id)}" class="${r.id === currentErrand ? "on" : ""}" ${r.id === currentErrand ? 'aria-current="true"' : ""}><span class="glyph">${ic("box")}</span><span class="grow"><b>${esc(r.name || "Delivery")}</b><small>${esc(r.label)}</small></span></button>`).join("")
    : `<p class="sm muted" style="padding:0 20px 20px">Deliveries you book in this browser session are listed here.</p>`;
}
$("#recentList").onclick = e => { const b = e.target.closest("[data-pick]"); if (b) { $("#eid").value = b.dataset.pick; loadTrack(); } };
$("#load").onclick = e => loadTrack(false, e.currentTarget);
$("#eid").addEventListener("keydown", e => { if (e.key === "Enter") loadTrack(); });
function openTrack(id) { go("track"); $("#eid").value = id; loadTrack(); }
function stopPoll() { clearInterval(pollTimer); pollTimer = null; }
function startPoll() { stopPoll(); pollTimer = setInterval(() => loadTrack(true), 3000); }
function clearTrack(html) { scaffoldId = null; lastFull = null; if (trackMap) { trackMap.destroy(); trackMap = null; } $("#trackOut").innerHTML = html; }
function scaffold(id) {
  clearTrack(""); scaffoldId = id;
  $("#trackOut").innerHTML = `<div class="card"><div class="mapwrap"><div id="tmap" class="tmap" role="img" aria-label="Map with the driver's current position"></div><div class="maptag" id="etaChip" hidden></div></div>
    <div class="card-b" id="tInfo"><span class="skel block" style="width:45%;height:22px"></span><span class="skel block" style="width:80%;margin-top:18px"></span><span class="skel block" style="width:60%;margin-top:12px"></span></div></div><div class="card" id="tTl"></div>`;
  trackMap = KPMap.create($("#tmap"));
}
const loadTrack = guard(async (quiet, btn) => busy(btn, async () => {
  const id = ($("#eid").value || currentErrand || "").trim();
  if (!id) { clearTrack(`<div class="card">${empty("route", "No delivery selected", "Pick one from the list, paste a delivery id, or book a new delivery.", `<button class="btn primary" data-go="book">${ic("plus")}New delivery</button>`)}</div>`); return; }
  if (id !== currentErrand) { currentErrand = id; $("#eid").value = id; renderRecent(); playing = false; }
  if (scaffoldId !== id) scaffold(id);
  let full; try { full = await v1("errands/" + encodeURIComponent(id)); }
  catch (e) { if (e.code === "errand_not_found") { stopPoll(); clearTrack(`<div class="card">${empty("search", "We can't find that delivery", "Check the id. A delivery only shows for the account and key type that booked it.")}</div>`); return; }
    if (e.code === "no_key") { stopPoll(); clearTrack(`<div class="card">${empty("key", "Choose an API key first", "Tracking uses the public API, so this page needs a key.", `<button class="btn primary" data-go="keys">Go to API keys</button>`)}</div>`); return; }
    if (!quiet) throw e; return; }
  lastFull = full; lastAt = Date.now(); paintTrack(full, id);
}));
function paintTrack(full, id) {
  if (!trackMap) return;
  const status = full.status, d = full.driver, loc = full.driver_location, cancelled = status === "cancelled";
  const idx = PHASES.findIndex(s => s[0] === status);
  const me = full.batch && full.batch.stops && full.batch.stops.find(x => x.errand_id === full.errand_id);
  const stopPrice = me ? me.price : (full.pricing && full.pricing.charge_total);
  const canCancel = ["pending", "broadcasted", "accepted", "arrived", "picked_up", "in_transit"].includes(status), terminal = status === "delivered" || cancelled;
  const label = cancelled ? "Cancelled" : (PHASES[idx] || [0, status])[1];
  const tagc = status === "delivered" ? "ok" : cancelled ? "err" : "brand", can = full.cancellation;
  const pick = {lat:+full.pickup.lat, lng:+full.pickup.lng}, drop = {lat:+full.dropoff.lat, lng:+full.dropoff.lng}, drv = loc ? {lat:+loc.lat, lng:+loc.lng} : null;
  trackMap.setRoute([{lat:pick.lat, lng:pick.lng, kind:"pickup", label:"A", title:"Pickup: " + (full.pickup.label || "")}, {lat:drop.lat, lng:drop.lng, kind:"stop", label:"B", title:"Drop-off: " + (full.dropoff.label || "")}]);
  trackMap.setDriver(cancelled ? null : drv, {wait: status === "broadcasted", trail: ["picked_up", "in_transit", "arrived_dropoff", "delivered"].includes(status)});
  const chip = $("#etaChip"), e = KPMap.eta(drv, status, pick, drop);
  if (e && !terminal) { chip.hidden = false; chip.innerHTML = `About ${e.min} min away<small>${e.km.toFixed(1)} km to go, estimate</small>`; }
  else if (status === "delivered") { chip.hidden = false; chip.innerHTML = "Delivered"; }
  else if (status === "broadcasted") { chip.hidden = false; chip.innerHTML = `Finding a driver<small>Waiting for a driver to accept</small>`; }
  else chip.hidden = true;
  const canPlay = ["accepted", "arrived", "picked_up", "in_transit", "arrived_dropoff", "broadcasted"].includes(status);
  $("#tInfo").innerHTML = `<div class="row"><h2 style="font-size:19px;letter-spacing:-.015em">${esc(label)}</h2><span class="badge ${tagc}">${esc(status.replace(/_/g, " "))}</span><span class="grow"></span><span class="xs muted">Updated <span id="ago">just now</span></span><button class="btn sm icon" id="refresh" aria-label="Refresh now">${ic("refresh")}</button></div>
    ${cancelled ? "" : `<ol class="phases" aria-label="Delivery progress">${PHASES.map((s, i) => `<li class="${i <= idx ? "done" : ""} ${i === idx ? "now" : ""}" ${i === idx ? 'aria-current="step"' : ""}>${s[1]}</li>`).join("")}</ol>`}
    <dl class="facts"><div><dt>Drop-off</dt><dd>${esc(full.dropoff && full.dropoff.label)}<small>${esc(full.dropoff && full.dropoff.contact && full.dropoff.contact.name || "")}</small></dd></div>
      <div><dt>Driver</dt><dd>${d ? `${esc(d.name)}, ${esc(d.rating)} stars<small>${esc(d.vehicle_type)}, ${esc(d.phone)}</small>` : '<span class="muted" style="font-weight:400">Not assigned yet</span>'}</dd></div>
      <div><dt>This stop</dt><dd class="num">${money(stopPrice)}<small>Payment ${esc(full.payment && full.payment.status || (full.payment_status ? "paid" : "unpaid"))}</small></dd></div>
      ${loc ? `<div><dt>Driver location</dt><dd>Seen <span id="drvAgo" data-ts="${esc(loc.updated_at)}"></span><small class="mono">${Number(loc.lat).toFixed(4)}, ${Number(loc.lng).toFixed(4)}</small></dd></div>` : ""}</dl>
    ${can ? `<div class="alert warn" style="margin-top:16px">${ic("ban")}<div><b>Cancelled.</b> Fee ${money(can.fee ?? 0)}. ${money(can.refund ?? 0)} went back to your wallet.</div></div>` : ""}
    ${full.proof_of_delivery ? `<div class="alert ok" style="margin-top:16px">${ic("check")}<div><b>Proof of delivery saved</b> on ${esc(when(full.proof_of_delivery.uploaded_at))}. <a href="${esc(full.proof_of_delivery.photo_url)}" target="_blank" rel="noopener">View photo</a></div></div>` : ""}
    <div class="row" style="margin-top:20px;gap:12px"><span class="ticket"><span><small>Delivery code</small><span class="c">${esc(full.delivery_code)}</span></span><button class="btn sm icon" data-copy="${esc(full.delivery_code)}" data-copied="Code copied." aria-label="Copy delivery code">${ic("copy")}</button></span>
      <span class="grow"></span><a class="btn" href="/track/${esc(id)}" target="_blank" rel="noopener">${ic("ext")}Customer page</a><button class="btn" id="copyLink">${ic("copy")}Copy customer link</button>
      ${canCancel ? `<button class="btn danger" id="cancel">Cancel delivery</button>` : ""}</div>
    ${!terminal ? `<div class="testbox"><div class="t">${ic("flask")}<span><b>Test tools.</b> These stand in for the Aerrander driver app and write real updates through the API.</span></div>
      <div class="row" style="gap:8px"><button class="btn sm" id="sim">${ic("next")}Next driver step</button>${canPlay ? `<button class="btn sm" id="play">${ic(playing ? "stop" : "play")}<span>${playing ? "Stop" : "Play full journey"}</span></button>` : ""}</div></div>` : ""}`;
  $("#tTl").innerHTML = `<div class="card-h"><h2>Timeline</h2></div><div class="card-b"><ul class="tl">${(full.timeline || []).slice().reverse().map(t => `<li><span>${esc(TIMELINE[t.state] || String(t.state).replace(/_/g, " ").toLowerCase())}</span><span class="muted sm num">${esc(when(t.at))}</span></li>`).join("") || '<li class="muted">Nothing yet. Updates appear as the driver moves.</li>'}</ul></div>`;
  $("#refresh").onclick = ev => loadTrack(false, ev.currentTarget);
  $("#copyLink").onclick = () => copy(location.origin + "/track/" + id, "Customer link copied.");
  const sim = $("#sim"); if (sim) sim.onclick = guard(async () => busy(sim, async () => { await simulate(id, {}); await loadTrack(true); loadNotes(true); }));
  const pl = $("#play"); if (pl) pl.onclick = () => play(id);
  const cn = $("#cancel"); if (cn) cn.onclick = guard(async () => {
    if (!await ask({title:"Cancel this delivery?", body:"A $4.00 fee applies once a driver has accepted. The rest of this stop's price goes back to your wallet.", ok:"Cancel delivery", danger:true})) return;
    playing = false; await busy(cn, async () => { await v1("errands/" + encodeURIComponent(id) + "/cancel", {method:"POST", body:{reason:"Cancelled from the portal"}, idem:uid()}); toast("Delivery cancelled."); await loadTrack(true); loadWallet(); loadNotes(true); });
  });
  tickAgo();
  if (terminal) { stopPoll(); playing = false; } else if (!pollTimer && page === "track") startPoll();
}
function tickAgo() {
  const a = $("#ago"); if (a && lastAt) a.textContent = agoText(Date.now() - lastAt);
  const d = $("#drvAgo"); if (d && d.dataset.ts) { const t = Date.parse(d.dataset.ts); if (t) d.textContent = agoText(Date.now() - t); }
}
setInterval(tickAgo, 1000);
function playLabel() { const b = $("#play"); if (b) b.innerHTML = ic(playing ? "stop" : "play") + `<span>${playing ? "Stop" : "Play full journey"}</span>`; }
async function play(id) {
  if (playing) { playing = false; playLabel(); return; }
  playing = true; playLabel();
  try {
    while (playing && currentErrand === id && page === "track") {
      const f = lastFull; if (!f || ["delivered", "cancelled"].includes(f.status)) break;
      if (f.status === "in_transit" && f.driver_location) {
        const a = {lat:+f.pickup.lat, lng:+f.pickup.lng}, b = {lat:+f.dropoff.lat, lng:+f.dropoff.lng}, d = {lat:+f.driver_location.lat, lng:+f.driver_location.lng};
        const frac = Math.min(1, KPMap.km(a, d) / Math.max(.001, KPMap.km(a, b)));
        if (frac < .97) { await simulate(id, {progress:Math.min(1, frac + .2)}); await loadTrack(true); await sleep(1000); continue; }
      }
      await simulate(id, {}); await loadTrack(true); await sleep(1300);
    }
  } catch (e) { fail(e); }
  finally { playing = false; playLabel(); loadNotes(true); }
}

/* ---------- notifications ---------- */
function renderNotes() {
  const list = noteFilter === "unread" ? notesData.filter(n => !n.read) : notesData;
  $("#noteList").innerHTML = list.length ? list.map(n => { const k = NOTE[n.kind] || ["bell", ""];
    return `<div class="item ${n.read ? "read" : "unread"}"><span class="glyph ${k[1]}">${ic(k[0])}</span>
      <div class="grow"><div class="title"><b>${esc(n.title)}</b>${n.read ? "" : '<span class="sr">Unread</span>'}</div><div class="sm muted">${esc(n.body)}</div><div class="xs faint" style="margin-top:3px">${esc(when(n.created_at))}</div></div>
      <div class="acts">${n.errand_id ? `<button class="btn sm" data-open="${esc(n.errand_id)}">Open</button>` : ""}${n.read ? "" : `<button class="btn sm ghost" data-read="${esc(n.id)}">Mark read</button>`}</div></div>`; }).join("")
    : notesData.length ? empty("check", "You're all caught up", "There are no unread notifications.")
    : empty("bell", "No notifications yet", "Book a delivery and its updates appear here.", `<button class="btn primary" data-go="book">${ic("plus")}New delivery</button>`);
}
async function loadNotes(quiet) {
  try {
    const r = await dash("notifications"); notesData = r.data;
    for (const id of ["#unread", "#bellCount"]) { const u = $(id); u.textContent = r.unread > 99 ? "99+" : r.unread; u.classList.toggle("hide", !r.unread); }
    $("#bell").setAttribute("aria-label", r.unread ? `Notifications, ${r.unread} unread` : "Notifications");
    $("#stNotes").textContent = r.unread; $("#stNotesSub").textContent = r.unread ? "Waiting in your inbox" : "All caught up";
    $("#noteUnreadN").textContent = r.unread ? r.unread : ""; $("#readAll").disabled = !r.unread;
    renderNotes();
  } catch (e) { if (!quiet) fail(e); }
}
$("#noteFilter").onclick = e => { const b = e.target.closest("button[data-f]"); if (!b) return; noteFilter = b.dataset.f; setFilter("noteFilter", noteFilter); renderNotes(); };
$("#refreshNotes").onclick = e => busy(e.currentTarget, () => loadNotes());
$("#readAll").onclick = guard(async e => busy(e.currentTarget, async () => { const r = await dash("notifications?unread=1"); await Promise.all(r.data.map(n => dash("notifications/" + n.id + "/read", {method:"POST", body:{}}))); await loadNotes(); toast("All notifications marked as read."); }));
$("#noteList").onclick = guard(async e => {
  const r = e.target.closest("[data-read]"); if (r) { await dash("notifications/" + r.dataset.read + "/read", {method:"POST", body:{}}); await loadNotes(); }
  const o = e.target.closest("[data-open]"); if (o) openTrack(o.dataset.open);
});

/* ---------- webhooks ---------- */
let eventsDrawn = false;
function drawEvents(types) {
  if (eventsDrawn || !types || !types.length) return; eventsDrawn = true;
  $("#hEvents").innerHTML = `<label class="check"><input type="checkbox" value="*" checked><span>All events</span></label>` + types.map(t => `<label class="check"><input type="checkbox" value="${esc(t)}"><span class="mono">${esc(t)}</span></label>`).join("");
}
$("#hEvents").addEventListener("change", e => {          // "All events" and specific events are either/or
  const all = $('#hEvents input[value="*"]'), rest = $$('#hEvents input:not([value="*"])');
  if (e.target === all && all.checked) rest.forEach(i => i.checked = false);
  else if (rest.some(i => i.checked)) all.checked = false; else all.checked = true;
});
async function loadHooks() {
  const r = await dash("webhook-endpoints"); hooksCount = r.data.length; drawEvents(r.event_types); updateSteps();
  $("#hookCount").textContent = hooksCount ? `${hooksCount} active` : "";
  $("#hookRows").innerHTML = r.data.length ? r.data.map(h => `<div class="item"><span class="glyph brand">${ic("link")}</span>
      <div class="grow"><div class="mono" style="word-break:break-all">${esc(h.url)}</div><div class="title" style="margin-top:6px;font-weight:400"><span class="badge ${h.environment === "live" ? "ok" : "info"}">${esc(h.environment)}</span><span class="xs muted">${esc((h.events && h.events.length && h.events[0] !== "*" ? h.events : ["All events"]).join(", "))}</span></div></div>
      <div class="acts"><button class="btn sm icon" data-copy="${esc(h.url)}" data-copied="Address copied." aria-label="Copy address">${ic("copy")}</button><button class="btn sm icon danger" data-del="${esc(h.id)}" aria-label="Delete endpoint">${ic("trash")}</button></div></div>`).join("")
    : empty("link", "No endpoints yet", "Add an address and we start sending delivery events to it.");
}
$("#hookRows").onclick = guard(async e => { const b = e.target.closest("[data-del]"); if (!b) return;
  if (!await ask({title:"Delete this endpoint?", body:"We stop sending events to it right away.", ok:"Delete endpoint", danger:true})) return;
  await busy(b, async () => { await dash("webhook-endpoints/" + b.dataset.del, {method:"DELETE"}); toast("Endpoint deleted."); await loadHooks(); }); });
$("#hookForm").addEventListener("submit", guard(async ev => {
  ev.preventDefault(); const url = $("#hUrl").value.trim();
  if (!/^https:\/\/.+\..+/.test(url)) { $("#hUrl").classList.add("err"); $("#hUrl").focus(); return toast("Enter a full address that starts with https://", "bad"); }
  $("#hUrl").classList.remove("err");
  const picked = $$("#hEvents input:checked").map(i => i.value), events = picked.includes("*") || !picked.length ? ["*"] : picked;
  await busy($("#hookBtn"), async () => {
    const h = await dash("webhook-endpoints", {method:"POST", body:{url, environment:$('input[name="henv"]:checked').value, events}});
    secretBox($("#newHook"), h.secret || h.signing_secret || "", "Copy your signing secret now", "Use it to check that each message really came from us. It is shown once.", 10);
    $("#hUrl").value = ""; toast("Endpoint added."); await loadHooks();
  });
}));

/* ---------- start ---------- */
(async () => {
  try { await call("/dashboard/wallet"); await enter(JSON.parse(store.get("biz") || "null") || {name:"Your business", approval_status:"approved"}); }
  catch { showLogin(); }
})();
