"use strict";
const report = JSON.parse(document.getElementById("nebula-data").textContent);
const byId = id => document.getElementById(id);
const metricNames = ["suggestions","accepted","rejected","exceptions","corrected","withdrawn","disabled","claims","successful","failed","unknown"];
const labels = {suggestions:"Suggestions",accepted:"Accepted",rejected:"Rejected",exceptions:"Exceptions",corrected:"Corrected",withdrawn:"Withdrawn",disabled:"Disabled",claims:"Claims",successful:"Successful applications",failed:"Failed",unknown:"Unknown outcome"};
function node(tag, text, className) { const el = document.createElement(tag); if (text !== undefined) el.textContent = String(text); if (className) el.className = className; return el; }
function option(select, value, text) { const el = node("option", text); el.value = value; select.append(el); }
function notice(text, warning=false) { return node("p", text, "notice" + (warning ? " warning" : "")); }
function bars(metrics) {
  const box = node("div", undefined, "feedback-bars");
  for (const key of ["accepted","rejected","exceptions","successful","failed","unknown"]) {
    const count = metrics[key] || 0, total = Math.max(1, ...Object.values(metrics));
    const bar = node("div", labels[key], "bar"); bar.append(node("strong", count));
    const track = node("div", undefined, "track"), fill = node("div", undefined, "fill");
    fill.style.width = (count / total * 100) + "%"; track.append(fill); bar.append(track); box.append(bar);
  } return box;
}
function sumRows(rows) { const totals = Object.fromEntries(metricNames.map(k => [k,0])); for (const row of rows) for (const k of metricNames) totals[k] += row[k] || 0; return totals; }
function detailsField(grid, name, value) { const item = node("div"); item.append(node("dt",name),node("dd",value || "None recorded")); grid.append(item); }
function lessonCard(record, nebula, project) {
  const value = record.lesson, details = node("details",undefined,"lesson"), summary = node("summary");
  const title = node("div",undefined,"lesson-title"); title.append(node("strong",value.action),node("small",`${value.kind} · ${value.lesson_id} · v${value.version}${record.is_current ? " · current" : " · older version"}`));
  summary.append(title,node("span",record.score.mature ? "MATURE" : "LEARNING","badge" + (record.score.mature ? "" : " learning")),node("span",Math.round(record.score.confidence*100)+"%","subtle")); details.append(summary);
  const body = node("div",undefined,"lesson-details"), grid = node("dl",undefined,"detail-grid");
  detailsField(grid,"Scenario / trigger",value.trigger); detailsField(grid,"Context",value.context_tags.join(", "));
  detailsField(grid,"Exceptions",value.exceptions.join("\n")); detailsField(grid,"Rationale",`${value.rationale || "None recorded"} (${value.rationale_source})`);
  detailsField(grid,"Scope",value.scope_projects.length ? value.scope_projects.join("\n") : "All selected projects in this Nebula");
  detailsField(grid,"Qualification",`${record.confirmed ? "Explicitly confirmed" : "Not explicitly confirmed"}; observational maturity ${record.score.observational_mature}; observational confidence ${Math.round(record.score.observational_confidence*100)}%`);
  detailsField(grid,"Application guards",`${value.disabled ? "Disabled" : "Enabled lesson"}; ${record.suspended ? "suspended after failure" : "not suspended"}. Context, refusal, scope, and host permissions still apply.`);
  if (!project) detailsField(grid,"Unfinished applications",String(record.unfinished_applications));
  const feedback = record.feedback.filter(f => !project || f.project === project);
  detailsField(grid,"Recent retained feedback",feedback.map(f => `${f.feedback_verdict}${f.reason ? ": " + f.reason : ""} · ${f.project}`).join("\n"));
  body.append(grid);
  if (record.tracked_metrics) {
    const metrics = project ? sumRows(nebula.metric_rows.filter(r => r.lesson_id===value.lesson_id && r.version===value.version && r.project===project)) : record.tracked_metrics;
    body.append(bars(metrics));
    body.append(node("p",metricNames.map(k=>`${labels[k]}: ${metrics[k]}`).join(" · "),"coverage"));
  } else body.append(notice("Analytics not initialized. These are retained records, not lifetime counts."));
  details.append(body); return details;
}
const rootOptions = report.nebulas;
for (const n of rootOptions) option(byId("nebula-filter"), n.root, n.root.split(/[\\/]/).pop());
const allProjects = [...new Set(report.nebulas.filter(n=>n.available).flatMap(n=>n.projects))].sort();
for (const p of allProjects) option(byId("project-filter"),p,p);
byId("snapshot").textContent = `Snapshot ${new Date(report.generated_at).toLocaleString()} · ${report.scan_root}`;
const summaryMetrics = [["Nebulas available",report.summary.available_nebulas],["Selected projects",report.summary.selected_projects],["Current lessons",report.summary.current_lessons],["Mature lessons",report.summary.mature_lessons],["Successful applications",report.summary.tracked_metrics.successful]];
for (const [label,value] of summaryMetrics) { const card = node("div",undefined,"metric"); card.append(node("span",value,"number"),node("span",label,"label")); byId("summary").append(card); }
byId("notices").append(notice(`Overview covers ${report.summary.available_nebulas} of ${report.summary.discovered_nebulas} discovered Nebulas. Application counters cover ${report.summary.tracked_nebulas} with analytics tracking. Filters below affect detail views; overview remains global.`));
if (!report.discovery.complete) byId("notices").append(notice("Discovery is incomplete. Some Nebulas may be absent.",true));
for (const warning of [...report.discovery.warnings,...report.warnings]) byId("notices").append(notice(warning,true));
function render() {
  const selected = byId("nebula-filter").value, project = byId("project-filter").value, kind = byId("kind-filter").value, maturity = byId("maturity-filter").value, search = byId("search").value.trim().toLowerCase();
  byId("nebulas").replaceChildren(); let visibleLessons=0, visibleNebulas=0;
  for (const n of report.nebulas) {
    if (selected && n.root!==selected) continue;
    if (project && (!n.available || !n.projects.includes(project))) continue;
    const card = node("article",undefined,"nebula"), head = node("div",undefined,"nebula-head"), row = node("div",undefined,"head-row");
    row.append(node("h3",n.root.split(/[\\/]/).pop()),node("span",n.available ? (n.enabled ? "ON" : "OFF") : "UNAVAILABLE","badge"+(n.available && n.enabled ? "" : " off"))); head.append(row,node("div",n.root,"path")); card.append(head);
    if (!n.available) { card.append(notice(n.diagnostic,true)); byId("nebulas").append(card); visibleNebulas++; continue; }
    head.append(node("p",`${n.coverage.label}${n.analytics_since ? " · Since " + new Date(n.analytics_since).toLocaleString() : ""} · Schema ${n.schema} · ${(n.storage_bytes/1024).toFixed(1)} KiB`,"coverage"));
    if (!n.coverage.details_complete) card.append(notice("Details are truncated. Global counters remain complete; filtered counts may be incomplete.",true));
    for (const warning of n.warnings) card.append(notice(warning,true));
    if (n.tracked_metrics) card.append(bars(project ? sumRows(n.metric_rows.filter(r=>r.project===project)) : n.tracked_metrics));
    const lessons = n.lessons.filter(r => (!kind || r.lesson.kind===kind) && (!maturity || String(r.score.mature)===maturity) && (!project || !r.lesson.scope_projects.length || r.lesson.scope_projects.includes(project)) && (!search || [r.lesson.action,r.lesson.trigger,r.lesson.rationale,...r.lesson.context_tags,...r.lesson.exceptions].join(" ").toLowerCase().includes(search)));
    for (const record of lessons) card.append(lessonCard(record,n,project));
    visibleLessons += lessons.length;
    if (!lessons.length) card.append(node("p","No lesson details match these filters.","empty"));
    if (!project && !n.analytics_since) card.append(notice("Retained suggestion states: " + JSON.stringify(n.retained_suggestion_states)));
    const activity = node("details",undefined,"activity"); activity.append(node("summary","Recent activity · retained records only"));
    const list=node("ul");
    for (const item of n.activity.filter(a=>!project || a.project===project)) list.append(node("li",`${new Date(item.timestamp).toLocaleString()} · ${item.kind} · ${JSON.stringify(item.data)}`));
    if (!list.children.length) list.append(node("li","No retained activity for this view."));
    activity.append(list); card.append(activity); byId("nebulas").append(card); visibleNebulas++;
  }
  if (!visibleNebulas) byId("nebulas").append(node("p","No Nebulas found in this view. Enable a Nebula in related child projects, then generate a fresh report.","empty"));
  byId("result-count").textContent=`${visibleNebulas} Nebulas · ${visibleLessons} lesson versions shown`;
}
for (const id of ["nebula-filter","project-filter","kind-filter","maturity-filter","search"]) byId(id).addEventListener("input",render);
render();
