// Evaluate this function in a browser displaying a fresh analytics_demo report.
// Development verification only; no dependencies or network requests.
() => {
  const get = id => document.getElementById(id);
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const set = (id, value) => { get(id).value = value; get(id).dispatchEvent(new Event("input", {bubbles:true})); };
  const filters = ["nebula-filter","project-filter","kind-filter","maturity-filter","version-filter","search"];
  const original = filters.map(id => [id,get(id)?.value]);
  assert(get("version-filter"), "Versions control is missing");
  try {
    assert(get("version-filter").value === "current", "Fresh report must default to current versions");
    for (const id of filters) set(id, id === "version-filter" ? "current" : "");
    assert(document.querySelectorAll(".lesson").length === 9, "Synthetic report should have nine current lessons");
    assert(![...document.querySelectorAll(".lesson-title small")].some(n => n.textContent.includes("older version")), "Older versions leaked into the default view");
    set("version-filter", "all");
    assert(document.querySelectorAll(".lesson").length === 12, "All versions view should have twelve lessons");
    set("version-filter", "older");
    assert(document.querySelectorAll(".lesson").length === 3, "History should contain three older versions");
    set("version-filter", "current");
    const data = JSON.parse(get("nebula-data").textContent);
    const root = data.nebulas.find(n => n.available && n.analytics_since);
    set("nebula-filter", root.root);
    set("project-filter", root.projects.find(p => p.endsWith("/indexer")));
    const activity = [...document.querySelectorAll(".activity li")];
    assert(activity.filter(n => n.textContent.includes("application-claim")).length === 3, "Project filter lost application claims");
    assert(activity.filter(n => n.textContent.includes("application-finish")).length === 3, "Project filter lost application outcomes");
    return "PASS: current default, version history and project-scoped application activity";
  } finally {
    for (const [id,value] of original) if (get(id)) set(id,value);
  }
}
