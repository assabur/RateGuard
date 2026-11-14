"use strict";
const $ = (id) => document.getElementById(id);
const fmt = (value, digits = 2) => Number.isFinite(value)
  ? value.toLocaleString("fr-FR", {maximumFractionDigits: digits, minimumFractionDigits: digits}) : "—";
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const badge = (status) => `<span class="badge ${["OK", "WARNING", "CRITICAL"].includes(status) ? status.toLowerCase() : ""}">${escape(status)}</span>`;
const name = (provider) => provider === "treasury" ? "Treasury" : provider === "fred" ? "FRED" : provider;
let request;

async function getJSON(path, signal) {
  const response = await fetch(path, {signal, headers: {Accept: "application/json"}});
  if (!response.ok) {
    if (response.status === 404) throw new Error("Aucune collecte pour ce mode et cette date. Lancez rateguard demo pour la démonstration, ou rateguard ingest pour les données réelles.");
    throw new Error(`La requête a échoué (HTTP ${response.status}). Vérifiez la disponibilité de l’API et les filtres.`);
  }
  return response.json();
}

function curveChart(report) {
  const points = report.points.filter(p => p.status !== "CRITICAL" && Number.isFinite(p.yield_pct));
  if (!points.length) return '<p>Aucun point valide à afficher.</p>';
  const values = points.map(p => p.yield_pct);
  const min = Math.min(...values) - 0.1, max = Math.max(...values) + 0.1;
  const x = tenor => 52 + (tenor - 2) / 28 * 520;
  const y = value => 230 - (value - min) / (max - min) * 200;
  let svg = '<svg viewBox="0 0 610 280" role="img" aria-label="Courbes Treasury et FRED par maturité, taux en pourcentage"><title>Courbes de rendement — valeurs détaillées dans le tableau de réconciliation</title>';
  for (let i = 0; i <= 4; i++) {
    const value = min + (max - min) * i / 4;
    svg += `<line x1="52" x2="572" y1="${y(value)}" y2="${y(value)}" stroke="#e4ebed"/><text x="4" y="${y(value) + 4}">${fmt(value)}</text>`;
  }
  for (const tenor of [2, 5, 10, 30]) svg += `<text x="${x(tenor)}" y="260" text-anchor="middle">${tenor}Y</text>`;
  for (const [provider, color] of [["treasury", "#087f75"], ["fred", "#5265c9"]]) {
    // A missing or invalid maturity breaks the line rather than implying a complete curve.
    let previous = null;
    for (const tenor of [2, 5, 10, 30]) {
      const point = points.find(p => p.provider === provider && p.tenor_years === tenor);
      if (!point) { previous = null; continue; }
      if (previous) svg += `<line x1="${x(previous.tenor_years)}" y1="${y(previous.yield_pct)}" x2="${x(tenor)}" y2="${y(point.yield_pct)}" stroke="${color}" stroke-width="2.5" ${provider === "fred" ? 'stroke-dasharray="6 4"' : ""}/>`;
      svg += `<circle cx="${x(tenor)}" cy="${y(point.yield_pct)}" r="4" fill="${color}"><title>${name(provider)} ${tenor}Y : ${fmt(point.yield_pct)} %</title></circle>`;
      previous = point;
    }
  }
  return svg + "</svg>";
}

function render(report) {
  $("report").hidden = false;
  $("notice").textContent = report.mode === "demo"
    ? "DÉMONSTRATION — Données synthétiques, jamais éligibles pour la recherche."
    : "DONNÉES RÉELLES — Réconciliation à la date d’observation sélectionnée.";
  $("metrics").innerHTML = [
    ["Date d’observation", escape(report.as_of)],
    ["Statut global", badge(report.status)],
    ["Fraîcheur actuelle", report.freshness.is_current ? "À jour" : "Non actuelle"],
    ["Utilisable aujourd’hui", report.usable_today ? "Oui" : "Non"],
  ].map(([label, value]) => `<div class="metric"><p>${label}</p><strong>${value}</strong></div>`).join("");
  $("curve-chart").innerHTML = curveChart(report);
  const scale = Math.max(report.thresholds.warning_bps, ...report.reconciliation.map(r => r.absolute_difference_bps ?? 0), 1);
  $("differences").innerHTML = report.reconciliation.map(r => `<div class="difference"><strong>${escape(r.tenor_years)}Y</strong><div class="track"><div class="bar ${["WARNING", "CRITICAL"].includes(r.difference_status) ? r.difference_status.toLowerCase() : ""}" style="width:${Number.isFinite(r.absolute_difference_bps) ? r.absolute_difference_bps / scale * 100 : 0}%"></div></div><span>${fmt(r.absolute_difference_bps)} bps</span></div>`).join("");
  $("thresholds").textContent = `OK ≤ ${fmt(report.thresholds.ok_bps)} bps · WARNING ≤ ${fmt(report.thresholds.warning_bps)} bps · CRITICAL au-delà ou si données invalides. — : écart indisponible.`;
  $("reconciliation").innerHTML = report.reconciliation.map(r => `<tr><td>${escape(r.tenor_years)}Y</td><td>${fmt(r.treasury_pct)}</td><td>${fmt(r.fred_pct)}</td><td>${fmt(r.absolute_difference_bps)}</td><td>${badge(r.status)}</td></tr>`).join("");
  const shapes = {NORMAL: "Normale", FLAT: "Plate", INVERTED: "Inversée", INCOMPLETE: "Incomplète"};
  $("spreads").innerHTML = report.curves.map(c => `<div><h3>${escape(name(c.provider))} · ${escape(shapes[c.shape] ?? c.shape)}</h3><p class="hint">Classification selon le spread 10Y−2Y</p>${Object.entries(c.spreads_bps).map(([key, value]) => `<p>${escape(key)} : <strong>${fmt(value)} bps</strong></p>`).join("") || "<p>Spreads indisponibles : courbe incomplète.</p>"}</div>`).join("");
  const issues = [];
  const seen = new Set();
  for (const point of [...report.points, ...report.quality]) {
    for (const issue of point.issues) {
      const key = JSON.stringify([point.provider, point.tenor_years, point.observation_date, issue]);
      if (seen.has(key)) continue;
      seen.add(key);
      issues.push(`${badge(issue.status)} ${escape(name(point.provider))} ${escape(point.tenor_years)}Y · ${escape(point.observation_date)} · ${escape(issue.code)} — ${escape(issue.detail)}`);
    }
  }
  for (const r of report.reconciliation.filter(r => r.status !== "OK")) issues.push(`${badge(r.status)} Réconciliation ${escape(r.tenor_years)}Y · écart ${fmt(r.absolute_difference_bps)} bps. ${r.investigation.map(escape).join(" ")}`);
  for (const e of report.ingestion_errors) issues.push(`${badge("CRITICAL")} ${escape(name(e.provider))} · ${escape(e.source)} — ${escape(e.detail)}`);
  $("issues").innerHTML = issues.length ? issues.map(i => `<li>${i}</li>`).join("") : "<li>Aucune anomalie détectée sur la fenêtre d’observation.</li>";
  $("run-info").textContent = `Exécution ${report.run_id} · Collectée le ${new Date(report.created_at).toLocaleString("fr-FR")} · Fraîcheur vérifiée au ${report.freshness.checked_on} : ${report.freshness.calendar_age_days} jour(s), maximum ${report.freshness.max_age_days}.`;
}

async function load(runId = null) {
  request?.abort();
  const controller = new AbortController();
  request = controller;
  const mode = $("mode").value;
  const query = new URLSearchParams({mode});
  if ($("as-of").value) query.set("as_of", $("as-of").value);
  $("report").hidden = true;
  $("history").replaceChildren();
  $("message").textContent = "Chargement des observations…";
  $("filters").setAttribute("aria-busy", "true");
  const results = await Promise.allSettled([
    getJSON(runId ? `/runs/${encodeURIComponent(runId)}` : `/report?${query}`, controller.signal),
    getJSON(`/runs?${new URLSearchParams({mode, limit: "30"})}`, controller.signal),
  ]);
  if (controller.signal.aborted) return;
  const [report, history] = results;
  const messages = [];
  if (report.status === "fulfilled") {
    render(report.value);
    if (runId) $("as-of").value = report.value.as_of;
  } else messages.push(report.reason.message);
  if (history.status === "fulfilled") {
    $("history").innerHTML = history.value.length ? history.value.map(r => `<tr><td>${escape(r.as_of)}</td><td>${escape(new Date(r.created_at).toLocaleString("fr-FR"))}</td><td>${badge(r.status)}</td><td><button type="button" data-run="${escape(r.run_id)}" aria-label="Voir la collecte du ${escape(r.as_of)} à ${escape(r.created_at)}">Consulter</button></td></tr>`).join("") : '<tr><td colspan="4">Aucune collecte dans ce mode.</td></tr>';
  } else messages.push(`Historique indisponible : ${history.reason.message}`);
  $("message").textContent = messages.join(" ") || "Rapport chargé.";
  $("filters").setAttribute("aria-busy", "false");
}

$("filters").addEventListener("submit", event => { event.preventDefault(); load(); });
$("mode").addEventListener("change", () => { $("as-of").value = ""; load(); });
$("history").addEventListener("click", event => {
  const button = event.target.closest("button[data-run]");
  if (button) load(button.dataset.run);
});
load();
