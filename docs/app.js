(() => {
  const PAGE = 50;
  const state = { deals: [], sectors: {}, coverage: { weeks: {}, runs: [] }, filtered: [], sort: "date", asc: false, page: 0, open: null };
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtUsd = (m) => m == null ? "" : m >= 1000 ? `$${(m / 1000).toFixed(2)}B` : m >= 1 ? `$${m.toFixed(m >= 10 ? 0 : 1)}M` : `$${(m * 1000).toFixed(0)}K`;
  const fmtDate = (d) => new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  const siteName = { viestories: "VIE Stories", yourstory: "YourStory" };

  async function load(name, fallback) {
    try { const r = await fetch(`data/${name}?v=${Date.now()}`); return r.ok ? await r.json() : fallback; }
    catch { return fallback; }
  }

  function isoWeekStart(dateStr) {
    const d = new Date(dateStr + "T00:00:00Z");
    const day = (d.getUTCDay() + 6) % 7;
    d.setUTCDate(d.getUTCDate() - day);
    return d.toISOString().slice(0, 10);
  }

  function renderKpis() {
    const deals = state.filtered;
    const disclosed = deals.filter((d) => d.amount_usd_mn != null);
    const total = disclosed.reduce((a, d) => a + d.amount_usd_mn, 0);
    const sorted = disclosed.map((d) => d.amount_usd_mn).sort((a, b) => a - b);
    const median = sorted.length ? sorted[Math.floor(sorted.length / 2)] : null;
    const bySector = {};
    deals.forEach((d) => (bySector[d.sector] = (bySector[d.sector] || 0) + 1));
    const top = Object.entries(bySector).sort((a, b) => b[1] - a[1])[0];
    const latestWeek = deals.length ? isoWeekStart(deals.reduce((a, d) => (d.date > a ? d.date : a), "")) : null;
    const thisWeek = deals.filter((d) => isoWeekStart(d.date) === latestWeek).length;
    const k = [
      ["Deals", deals.length.toLocaleString("en-IN"), `${disclosed.length} with disclosed amounts`],
      ["Disclosed capital", fmtUsd(total) || "$0", "Sum of disclosed cheques"],
      ["Median cheque", fmtUsd(median) || "n/a", "Across disclosed rounds"],
      ["Top sector", top ? esc(top[0]) : "n/a", top ? `${top[1]} deals` : ""],
      ["Latest week", thisWeek, latestWeek ? `Week of ${fmtDate(latestWeek)}` : ""],
    ];
    $("#kpis").innerHTML = k.map(([l, v, h]) => `<div class="kpi"><div class="label">${l}</div><div class="value">${v}</div><div class="hint">${h}</div></div>`).join("");
  }

  function renderChart() {
    const counts = {};
    state.filtered.forEach((d) => { const w = isoWeekStart(d.date); counts[w] = (counts[w] || 0) + 1; });
    const weeks = Object.keys(counts).sort();
    if (!weeks.length) { $("#chart").innerHTML = `<div class="empty">No deals yet</div>`; return; }
    // fill gaps so missing weeks show as zero
    const all = [];
    for (let d = new Date(weeks[0] + "T00:00:00Z"); d <= new Date(weeks[weeks.length - 1] + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + 7)) all.push(d.toISOString().slice(0, 10));
    const max = Math.max(...all.map((w) => counts[w] || 0));
    const W = 1000, H = 160, pad = 18, bw = (W - 10) / all.length;
    const bars = all.map((w, i) => {
      const v = counts[w] || 0, h = max ? ((H - pad * 2) * v) / max : 0;
      const x = 5 + i * bw, y = H - pad - h;
      const label = i % Math.ceil(all.length / 12) === 0 ? `<text x="${x + bw / 2}" y="${H - 4}" text-anchor="middle">${esc(fmtDate(w).replace(/ \d{4}$/, ""))}</text>` : "";
      return `<g><title>Week of ${esc(fmtDate(w))}: ${v} deals</title><rect x="${x + 2}" y="${y}" width="${Math.max(bw - 4, 1)}" height="${h}" rx="2"></rect>${v ? `<text x="${x + bw / 2}" y="${y - 3}" text-anchor="middle">${v}</text>` : ""}${label}</g>`;
    }).join("");
    $("#chart").innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Deals per week">${bars}</svg>`;
    $("#chart-note").textContent = `${all.length} weeks`;
  }

  function applyFilters() {
    const q = $("#q").value.trim().toLowerCase();
    const sector = $("#f-sector").value, round = $("#f-round").value, source = $("#f-source").value;
    const from = $("#f-from").value, to = $("#f-to").value, size = $("#f-size").value;
    state.filtered = state.deals.filter((d) => {
      if (sector && d.sector !== sector) return false;
      if (round && d.round !== round) return false;
      if (source && !d.sources.some((s) => s.site === source)) return false;
      if (from && d.date < from) return false;
      if (to && d.date > to) return false;
      if (size === "undisclosed" && d.amount_usd_mn != null) return false;
      if (size && size !== "undisclosed") {
        const [lo, hi] = size.split("-").map(Number);
        if (d.amount_usd_mn == null || d.amount_usd_mn < lo || d.amount_usd_mn >= hi) return false;
      }
      if (q) {
        const hay = [d.company, d.company_brief, d.sub_sector, d.city, d.headline, ...(d.lead_investors || []), ...(d.investors || [])].join(" ").toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    const k = state.sort, dir = state.asc ? 1 : -1;
    state.filtered.sort((a, b) => {
      let x = a[k], y = b[k];
      if (k === "amount_usd_mn") { x = x ?? -1; y = y ?? -1; }
      return (x > y ? 1 : x < y ? -1 : 0) * dir || (a.date < b.date ? 1 : -1);
    });
    state.page = 0;
    state.open = null;
    renderKpis(); renderChart(); renderTable();
  }

  function sectorSnippet(name) {
    const s = state.sectors[name];
    if (!s) return "";
    const list = (xs) => (xs || []).slice(0, 3).map((x) => `<li>${esc(x)}</li>`).join("");
    return `<div><h4>${esc(name)} tailwinds</h4><ul>${list(s.tailwinds)}</ul></div><div><h4>${esc(name)} headwinds</h4><ul>${list(s.headwinds)}</ul></div>`;
  }

  function renderTable() {
    const rows = state.filtered.slice(state.page * PAGE, (state.page + 1) * PAGE);
    $("#count").textContent = `${state.filtered.length.toLocaleString("en-IN")} deals`;
    document.querySelectorAll("th.sortable").forEach((th) => {
      th.classList.toggle("sorted", th.dataset.sort === state.sort);
      th.classList.toggle("asc", th.dataset.sort === state.sort && state.asc);
    });
    const body = rows.map((d) => {
      const inv = [...(d.lead_investors || []).map((i) => `<strong>${esc(i)}</strong>`), ...(d.investors || []).map(esc)].join(", ");
      const links = d.sources.map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${esc(siteName[s.site] || s.site)}</a>`).join(" · ");
      const amount = d.amount_usd_mn != null ? `${fmtUsd(d.amount_usd_mn)}<div class="subtle">${esc(d.amount_text)}</div>` : `<span class="subtle">${esc(d.amount_text || "Undisclosed")}</span>`;
      let html = `<tr class="deal" data-id="${esc(d.id)}">
        <td class="date">${esc(fmtDate(d.date))}</td>
        <td><div class="company">${esc(d.company)}</div><div class="subtle">${esc([d.sub_sector, d.city].filter(Boolean).join(" · "))}</div></td>
        <td>${esc(d.sector)}</td>
        <td><span class="pill">${esc(d.round)}</span></td>
        <td class="num">${amount}</td>
        <td class="investors">${inv || '<span class="subtle">Not disclosed</span>'}</td>
        <td>${links}</td></tr>`;
      if (state.open === d.id) {
        html += `<tr class="detail"><td colspan="7"><div class="detail-grid">
          <div><h4>About ${esc(d.company)}</h4><p>${esc(d.company_brief || "No description in the article.")}</p>
          ${d.use_of_funds ? `<h4>Use of funds</h4><p>${esc(d.use_of_funds)}</p>` : ""}
          <p class="subtle">${esc(d.headline)}</p></div>
          ${sectorSnippet(d.sector)}</div></td></tr>`;
      }
      return html;
    }).join("");
    $("#deals tbody").innerHTML = body || `<tr><td colspan="7" class="empty">No deals match these filters.</td></tr>`;
    const pages = Math.max(1, Math.ceil(state.filtered.length / PAGE));
    $("#page").textContent = `Page ${state.page + 1} of ${pages}`;
    $("#prev").disabled = state.page === 0;
    $("#next").disabled = state.page >= pages - 1;
  }

  function renderSectors() {
    const counts = {};
    state.deals.forEach((d) => { const c = (counts[d.sector] ||= { n: 0, usd: 0 }); c.n++; c.usd += d.amount_usd_mn || 0; });
    const names = Object.keys(state.sectors).filter((n) => n !== "Other" || counts[n]).sort((a, b) => (counts[b]?.n || 0) - (counts[a]?.n || 0));
    $("#sector-grid").innerHTML = names.map((n) => {
      const s = state.sectors[n], c = counts[n] || { n: 0, usd: 0 };
      const list = (xs) => (xs || []).map((x) => `<li>${esc(x)}</li>`).join("");
      const investors = (s.top_investors || []).slice(0, 5).map(([i]) => esc(i)).join(", ");
      return `<article class="sector">
        <h3>${esc(n)}</h3>
        <div class="stats">${c.n} deals tracked · ${fmtUsd(c.usd) || "$0"} disclosed${investors ? ` · Active: ${investors}` : ""}</div>
        <p>${esc(s.brief)}</p>
        <div class="winds"><div class="tail"><h4>Tailwinds</h4><ul>${list(s.tailwinds)}</ul></div>
        <div class="head"><h4>Headwinds</h4><ul>${list(s.headwinds)}</ul></div></div>
        ${s.funding_pulse ? `<div class="pulse"><strong>Funding pulse:</strong> ${esc(s.funding_pulse)}</div>` : ""}
        <div class="subtle" style="margin-top:8px">Note ${s.source === "ai-pipeline" ? "written by Claude from the tracked deals" : "written by Claude"} · ${esc((s.generated_at || "").slice(0, 10))}
        ${c.n ? ` · <a href="#" data-sector="${esc(n)}">See deals</a>` : ""}</div>
      </article>`;
    }).join("");
  }

  function renderCoverage() {
    const weeks = Object.entries(state.coverage.weeks || {}).sort((a, b) => (a[0] < b[0] ? 1 : -1));
    const cell = (w, s) => { const x = w[s] || { articles: 0, deals: 0, rejected: 0 }; return `<td class="num">${x.articles}</td><td class="num">${x.deals}</td><td class="num">${x.rejected}</td>`; };
    $("#coverage-weeks").innerHTML = `<thead><tr><th>ISO week</th><th class="num">VIE articles</th><th class="num">VIE deals</th><th class="num">VIE rejected</th><th class="num">YS articles</th><th class="num">YS deals</th><th class="num">YS rejected</th></tr></thead>
      <tbody>${weeks.map(([wk, w]) => `<tr><td>${esc(wk)}</td>${cell(w, "viestories")}${cell(w, "yourstory")}</tr>`).join("") || '<tr><td colspan="7" class="empty">No runs yet</td></tr>'}</tbody>`;
    const runs = [...(state.coverage.runs || [])].reverse();
    const fr = runs[0]?.fill_rates;
    $("#fill-rates").innerHTML = fr ? `<thead><tr>${Object.keys(fr).map((k) => `<th class="num">${esc(k.replace(/_/g, " "))}</th>`).join("")}</tr></thead>
      <tbody><tr>${Object.values(fr).map((v) => `<td class="num">${Math.round(v * 100)}%</td>`).join("")}</tr></tbody>` : "";
    $("#coverage-runs").innerHTML = `<thead><tr><th>Run</th><th>Window</th><th>Mode</th><th>Source</th><th class="num">Candidates</th><th class="num">New URLs</th><th class="num">Deals</th><th>Channels</th><th class="num">Fetch errors</th></tr></thead>
      <tbody>${runs.flatMap((r) => Object.entries(r.sources || {}).map(([s, x]) => `<tr><td>${esc((r.started || "").slice(0, 16).replace("T", " "))}</td><td>${esc((r.window || []).join(" → "))}</td><td>${esc(r.extraction)}</td><td>${esc(siteName[s] || s)}</td><td class="num">${x.candidates || 0}</td><td class="num">${x.new_urls || 0}</td><td class="num">${x.deals || 0}</td><td class="subtle">${esc(Object.entries(x.channels || {}).map(([k, v]) => `${k}: ${v}`).join(", "))}</td><td class="num">${x.fetch_failed || 0}</td></tr>`)).join("") || '<tr><td colspan="9" class="empty">No runs yet</td></tr>'}</tbody>`;
  }

  function exportCsv() {
    const cols = ["date", "company", "company_brief", "sector", "sub_sector", "round", "amount_text", "amount_usd_mn", "amount_inr_cr", "lead_investors", "investors", "city", "use_of_funds", "sector_brief", "sector_tailwinds", "sector_headwinds", "source_urls"];
    const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = [cols.join(",")].concat(state.filtered.map((d) => {
      const s = state.sectors[d.sector] || {};
      const row = { ...d, lead_investors: (d.lead_investors || []).join("; "), investors: (d.investors || []).join("; "),
        sector_brief: s.brief, sector_tailwinds: (s.tailwinds || []).join("; "), sector_headwinds: (s.headwinds || []).join("; "),
        source_urls: d.sources.map((x) => x.url).join(" ") };
      return cols.map((c) => q(row[c])).join(",");
    }));
    const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `india-funding-${new Date().toISOString().slice(0, 10)}.csv` });
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ---- Refresh tab: dispatch the GitHub Actions workflow for a custom date range ----
  const REPO = "agarayush/Funding-Tracker", WORKFLOW = "weekly-update.yml", MAX_DAYS = 365, TOKEN_KEY = "ft_github_token";
  const isoDay = (d) => d.toISOString().slice(0, 10);
  const daysAgo = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return isoDay(d); };
  const store = { get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
                  set: (k, v) => { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k); } catch {} } };

  function rangeError(from, to) {
    if (!from || !to) return "Pick both dates.";
    if (from > to) return "The From date must be on or before the To date.";
    if (to > daysAgo(0)) return "The To date can't be in the future.";
    if (from < daysAgo(MAX_DAYS)) return `Only the last 12 months can be refreshed, so the earliest From date is ${fmtDate(daysAgo(MAX_DAYS))}.`;
    return "";
  }

  function setMsg(text, kind) { const m = $("#r-msg"); m.textContent = text; m.className = `msg ${kind || ""}`; }

  async function loadRuns() {
    try {
      const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/runs?per_page=8`);
      const data = await r.json();
      const rows = (data.workflow_runs || []).map((run) => {
        const status = run.status === "completed" ? (run.conclusion === "success" ? "Done" : run.conclusion || "Done") : run.status === "queued" ? "Queued" : "Running";
        const mins = run.status === "completed" ? Math.max(1, Math.round((new Date(run.updated_at) - new Date(run.run_started_at || run.created_at)) / 60000)) + " min" : "";
        return `<tr><td>${esc(new Date(run.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }))}</td>
          <td>${run.event === "schedule" ? "Weekly (automatic)" : "Manual"}</td><td>${esc(status)}</td><td class="num">${mins}</td>
          <td><a href="${esc(run.html_url)}" target="_blank" rel="noopener">Details</a></td></tr>`;
      }).join("");
      $("#r-runs").innerHTML = `<thead><tr><th>Started</th><th>Type</th><th>Status</th><th class="num">Took</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="5" class="empty">No runs yet</td></tr>'}</tbody>`;
      return data.workflow_runs || [];
    } catch {
      $("#r-runs").innerHTML = `<tbody><tr><td class="empty">Couldn't load run history from GitHub.</td></tr></tbody>`;
      return [];
    }
  }

  function initRefresh() {
    const from = $("#r-from"), to = $("#r-to");
    from.min = to.min = daysAgo(MAX_DAYS);
    from.max = to.max = daysAgo(0);
    from.value = daysAgo(7); to.value = daysAgo(0);
    $("#range-limit").textContent = `Earliest allowed: ${fmtDate(daysAgo(MAX_DAYS))}`;
    $("#r-open").href = `https://github.com/${REPO}/actions/workflows/${WORKFLOW}`;
    const saved = store.get(TOKEN_KEY);
    if (saved) { $("#r-token").value = saved; $("#r-remember").checked = true; }
    document.querySelectorAll(".presets button").forEach((b) => (b.onclick = () => {
      from.value = daysAgo(Number(b.dataset.days)); to.value = daysAgo(0); setMsg("");
    }));
    [from, to].forEach((i) => i.addEventListener("input", () => setMsg(rangeError(from.value, to.value), "error")));
    $("#r-reload").onclick = loadRuns;
    $("#refresh-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const err = rangeError(from.value, to.value);
      if (err) return setMsg(err, "error");
      const token = $("#r-token").value.trim();
      if (!token) return setMsg("Add a GitHub token (see the steps below), or use “Or start it on GitHub instead” and enter these dates there.", "error");
      store.set(TOKEN_KEY, $("#r-remember").checked ? token : null);
      setMsg("Starting the refresh…");
      try {
        const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
          method: "POST",
          headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${token}`, "X-GitHub-Api-Version": "2022-11-28" },
          body: JSON.stringify({ ref: "main", inputs: { from_date: from.value, to_date: to.value, reprocess: $("#r-reprocess").checked } }),
        });
        if (r.status === 204) {
          setMsg(`Refresh started for ${fmtDate(from.value)} to ${fmtDate(to.value)}. The site will update a few minutes after the run shows “Done” below.`, "ok");
          setTimeout(loadRuns, 4000);
        } else if (r.status === 401 || r.status === 403 || r.status === 404) {
          setMsg("GitHub rejected the token. Check that it covers the Funding-Tracker repo, has Actions set to Read and write, and hasn't expired.", "error");
        } else {
          const body = await r.json().catch(() => ({}));
          setMsg(`GitHub returned ${r.status}: ${body.message || "unknown error"}`, "error");
        }
      } catch {
        setMsg("Couldn't reach GitHub. Check your connection and try again.", "error");
      }
    });
    loadRuns();
  }

  function showTab(name) {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.id !== `tab-${name}`));
    $("#kpis").hidden = name === "coverage" || name === "refresh";
  }

  function fillSelect(sel, values) {
    sel.insertAdjacentHTML("beforeend", values.map((v) => `<option>${esc(v)}</option>`).join(""));
  }

  async function init() {
    const [deals, sectors, coverage, st] = await Promise.all([load("deals.json", []), load("sectors.json", {}), load("coverage.json", { weeks: {}, runs: [] }), load("state.json", {})]);
    Object.assign(state, { deals, sectors, coverage });
    if (st.updated) $("#updated").textContent = `Last updated ${new Date(st.updated).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}.`;
    fillSelect($("#f-sector"), [...new Set(deals.map((d) => d.sector))].sort());
    const order = ["Pre-Seed", "Seed", "Pre-Series A", "Series A", "Pre-Series B", "Series B", "Pre-Series C", "Series C", "Series D", "Series E+", "Bridge", "Debt", "Grant", "Strategic", "Undisclosed"];
    fillSelect($("#f-round"), order.filter((r) => deals.some((d) => d.round === r)));

    ["#q", "#f-sector", "#f-round", "#f-source", "#f-from", "#f-to", "#f-size"].forEach((s) => $(s).addEventListener("input", applyFilters));
    $("#reset").onclick = () => { document.querySelectorAll(".filters input, .filters select").forEach((e) => (e.value = "")); applyFilters(); };
    $("#csv").onclick = exportCsv;
    $("#prev").onclick = () => { state.page--; renderTable(); };
    $("#next").onclick = () => { state.page++; renderTable(); };
    document.querySelectorAll("th.sortable").forEach((th) => th.addEventListener("click", () => {
      state.asc = state.sort === th.dataset.sort ? !state.asc : th.dataset.sort === "company";
      state.sort = th.dataset.sort; applyFilters();
    }));
    $("#deals tbody").addEventListener("click", (e) => {
      const tr = e.target.closest("tr.deal"); if (!tr) return;
      state.open = state.open === tr.dataset.id ? null : tr.dataset.id; renderTable();
    });
    document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => showTab(t.dataset.tab)));
    $("#sector-grid").addEventListener("click", (e) => {
      const a = e.target.closest("a[data-sector]"); if (!a) return;
      e.preventDefault(); $("#f-sector").value = a.dataset.sector; showTab("deals"); applyFilters();
    });
    applyFilters(); renderSectors(); renderCoverage(); initRefresh();
  }
  init();
})();
