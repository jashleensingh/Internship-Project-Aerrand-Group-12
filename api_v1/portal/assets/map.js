/* Shared live map for the portal and the customer tracking page.
 *
 * Uses the bundled Leaflet and OpenStreetMap tiles. If Leaflet cannot load, it falls back to a plain drawing
 * (grid, route line, pins) so the page never shows an empty box. Routes are straight lines between points: the real
 * Aerrander app would supply road geometry.
 *
 *   const m = KPMap.create(element, {compact: false});
 *   m.setRoute([{lat, lng, kind: "pickup" | "stop", label: "A", title: "text"}, ...]);
 *   m.setDriver({lat, lng} | null, {wait: false, trail: true});
 *   m.refresh();     // call after the container becomes visible or resizes
 *   KPMap.eta(...)   // rough minutes left, from straight-line distance at city speed
 */
(function (global) {
  "use strict";
  const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
  const ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors';
  const VAN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M3 16V7h11v9M14 10h4l3 3v3h-7M3 16h2m10 0h-1"/><circle cx="7" cy="17" r="2"/><circle cx="17" cy="17" r="2"/></svg>';
  const css = n => (getComputedStyle(document.documentElement).getPropertyValue(n) || "").trim();
  const rad = d => d * Math.PI / 180;

  function km(a, b) {
    const dLat = rad(b.lat - a.lat), dLng = rad(b.lng - a.lng);
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
    return 12742 * Math.asin(Math.sqrt(h));
  }
  /* Rough distance and minutes left. Before pickup the driver still has to reach the pickup first. */
  function eta(driver, status, pickup, drop, kmh) {
    if (!driver || !pickup || !drop || status === "delivered" || status === "cancelled") return null;
    const beforePickup = ["broadcasted", "pending", "accepted", "arrived"].includes(status);
    const left = beforePickup ? km(driver, pickup) + km(pickup, drop) : km(driver, drop);
    return {km: left, min: Math.max(1, Math.round(left / (kmh || 30) * 60))};
  }
  /* classes are prefixed (kp-stop, kp-van...) so they can never collide with a host page's own .stop, .van, .wait */
  const pin = (kind, label) => `<div class="kp-pin ${kind.split(" ").map(c => "kp-" + c).join(" ")}">${kind.startsWith("van") ? VAN : String(label ?? "")}</div>`;
  const key = stops => stops.map(s => s.lat + "," + s.lng).join("|");
  const ease = t => t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;

  /* ---------------- Leaflet ---------------- */
  function leafletMap(el, o) {
    el.classList.add("kp-map");
    const map = L.map(el, {zoomControl: !o.compact, scrollWheelZoom: false, zoomSnap: .25, attributionControl: true}).setView([42.3149, -83.0364], 12);
    const tiles = L.tileLayer(TILES, {maxZoom: 19, attribution: ATTR}).addTo(map);
    const note = document.createElement("div"); note.className = "kp-note"; note.hidden = true;
    note.textContent = "Map tiles can't load right now. The route and pins still show."; el.appendChild(note);
    let bad = 0; tiles.on("tileerror", () => { if (++bad > 3) note.hidden = false; }); tiles.on("tileload", () => { bad = 0; note.hidden = true; });
    let markers = [], line = null, trail = null, drv = null, last = null, fitKey = "", stops = [], anim = 0, pos = null;

    function fit(withDriver, animate) {   // animate only when following the driver, never on first draw
      const pts = stops.map(s => [s.lat, s.lng]); if (withDriver && pos) pts.push([pos.lat, pos.lng]);
      if (pts.length === 1) map.setView(pts[0], 14, {animate: !!animate}); else if (pts.length) map.fitBounds(pts, {padding: [56, 56], maxZoom: 15, animate: !!animate});
    }
    function setRoute(list) {
      stops = list || []; markers.forEach(m => m.remove()); markers = []; if (line) { line.remove(); line = null; }
      stops.forEach(s => markers.push(L.marker([s.lat, s.lng], {icon: L.divIcon({className: "", html: pin(s.kind, s.label), iconSize: [34, 34], iconAnchor: [17, 17]}), title: s.title || "", keyboard: false}).addTo(map)));
      if (stops.length > 1) line = L.polyline(stops.map(s => [s.lat, s.lng]), {color: css("--text") || "#101A2E", weight: 4, opacity: .45, dashArray: "1 9", lineCap: "round"}).addTo(map);
      const k = key(stops); if (k !== fitKey) { fitKey = k; fit(false); }
    }
    function setDriver(p, opts) {
      opts = opts || {};
      if (!p) { if (drv) { drv.remove(); drv = null; } if (trail) { trail.remove(); trail = null; } pos = null; return; }
      const from = last || p; last = p; pos = p;
      const icon = L.divIcon({className: "", html: pin("van" + (opts.wait ? " wait" : "")), iconSize: [40, 40], iconAnchor: [20, 20]});
      if (!drv) drv = L.marker([p.lat, p.lng], {icon, zIndexOffset: 1000, title: "Driver", keyboard: false}).addTo(map); else drv.setIcon(icon);
      cancelAnimationFrame(anim); const t0 = performance.now(), dur = 900;
      const step = now => {
        const t = Math.min(1, (now - t0) / dur), e = ease(t), lat = from.lat + (p.lat - from.lat) * e, lng = from.lng + (p.lng - from.lng) * e;
        drv.setLatLng([lat, lng]); if (trail) trail.setLatLngs([[stops[0].lat, stops[0].lng], [lat, lng]]);
        if (t < 1) anim = requestAnimationFrame(step);
      };
      if (opts.trail && stops.length) {
        if (!trail) trail = L.polyline([[stops[0].lat, stops[0].lng], [from.lat, from.lng]], {color: css("--brand") || "#FF7926", weight: 5, lineCap: "round"}).addTo(map);
      } else if (trail) { trail.remove(); trail = null; }
      anim = requestAnimationFrame(step);
      if (!map.getBounds().pad(-.08).contains([p.lat, p.lng])) fit(true, true);
    }
    map.on("resize", () => fit(true));   // keep the route in view when the window or phone orientation changes
    return {setRoute, setDriver, refresh() { map.invalidateSize(); fit(true); }, destroy() { map.remove(); }, kind: "leaflet"};
  }

  /* ---------------- plain fallback ---------------- */
  function plainMap(el, o) {
    el.classList.add("kp-map", "kp-plain"); el.innerHTML = '<svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><polyline class="r" vector-effect="non-scaling-stroke"/><polyline class="t" vector-effect="non-scaling-stroke"/></svg>';
    const svg = el.querySelector("svg"), r = svg.querySelector(".r"), t = svg.querySelector(".t");
    let stops = [], pos = null, nodes = [], van = null, trailOn = false, wait = false;
    function layout() {
      const pts = stops.concat(pos ? [pos] : []); if (!pts.length) return;
      const lats = pts.map(p => p.lat), lngs = pts.map(p => p.lng), cl = Math.cos(rad((Math.min(...lats) + Math.max(...lats)) / 2));
      let w = (Math.max(...lngs) - Math.min(...lngs)) * cl, h = Math.max(...lats) - Math.min(...lats);
      const pad = Math.max(w, h, .004) * .22; w = Math.max(w, .004) + pad * 2; h = Math.max(h, .004) + pad * 2;
      const box = el.getBoundingClientRect(), s = Math.min((box.width || 400) / w, (box.height || 300) / h);
      const cx = (Math.min(...lngs) + Math.max(...lngs)) / 2, cy = (Math.min(...lats) + Math.max(...lats)) / 2;
      const proj = p => ({x: 50 + ((p.lng - cx) * cl) * s / (box.width || 400) * 100, y: 50 - (p.lat - cy) * s / (box.height || 300) * 100});
      nodes.forEach((n, i) => { const q = proj(stops[i]); n.style.left = q.x + "%"; n.style.top = q.y + "%"; });
      r.setAttribute("points", stops.map(p => { const q = proj(p); return q.x + "," + q.y; }).join(" "));
      if (van) { const q = proj(pos); van.style.left = q.x + "%"; van.style.top = q.y + "%"; }
      t.setAttribute("points", trailOn && pos && stops.length ? [proj(stops[0]), proj(pos)].map(q => q.x + "," + q.y).join(" ") : "");
    }
    return {
      setRoute(list) { stops = list || []; nodes.forEach(n => n.remove()); nodes = stops.map(s => { const d = document.createElement("div"); d.innerHTML = pin(s.kind, s.label); const n = d.firstChild; n.title = s.title || ""; el.appendChild(n); return n; }); layout(); },
      setDriver(p, opts) { opts = opts || {}; pos = p; trailOn = !!opts.trail;
        if (!p) { if (van) { van.remove(); van = null; } layout(); return; }
        if (!van) { const d = document.createElement("div"); d.innerHTML = pin("van"); van = d.firstChild; el.appendChild(van); }
        van.classList.toggle("kp-wait", !!opts.wait); layout(); },
      refresh: layout, destroy() { el.innerHTML = ""; }, kind: "plain"
    };
  }

  global.KPMap = {
    create(el, o) { o = o || {}; try { return global.L ? leafletMap(el, o) : plainMap(el, o); } catch (e) { el.innerHTML = ""; return plainMap(el, o); } },
    km, eta
  };
})(window);
