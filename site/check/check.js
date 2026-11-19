// The page around the checker: input, type detection, samples, and the plain-English reading of the reference tools'
// output. The verdict and the findings always come from the tools themselves (engine.js, runner.py); nothing here decides
// whether a file passes. Nothing here stores the file, puts it in the address bar or sends it anywhere.
import { runCheck } from "./engine.js";

const $ = (id) => document.getElementById(id);
const els = {
  kind: $("kind"), input: $("input"), drop: $("drop"), file: $("file"), run: $("run"), clear: $("clear"), status: $("status"),
  result: $("result"), kicker: $("result-kicker"), title: $("result-title"), summary: $("result-summary"), verdict: $("verdict"),
  findings: $("findings"), notes: $("notes"), reportText: $("report-text"), reportJson: $("report-json"),
  copyText: $("copy-text"), copyJson: $("copy-json"), saveJson: $("save-json"), copyStatus: $("copy-status"),
};
let DATA = null;
let fileBytes = null;      // the exact bytes of a chosen or dropped file, until the text is edited
let fileName = null;
let busy = false;
const dataReady = fetch(new URL("checker-data.json", import.meta.url), { credentials: "omit" })
  .then((r) => { if (!r.ok) throw new Error("could not load checker-data.json"); return r.json(); })
  .then((d) => (DATA = d));

// ---------- small helpers ----------
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") n.className = v; else if (k === "text") n.textContent = v; else n.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null) n.append(k.nodeType ? k : document.createTextNode(String(k)));
  return n;
};
const link = (href, text) => el("a", { href }, text);
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const setStatus = (t) => { els.status.textContent = t; };

// ---------- input ----------
els.input.addEventListener("input", () => { fileBytes = null; fileName = null; });
els.clear.addEventListener("click", () => {
  els.input.value = ""; fileBytes = null; fileName = null; els.file.value = ""; els.kind.value = "auto";
  els.result.hidden = true; setStatus(""); els.input.focus();
});

async function takeFile(f) {
  if (!f) return;
  if (f.size > 25e6) { setStatus("That file is over 25 MB, which is more than this page will check."); return; }
  const bytes = new Uint8Array(await f.arrayBuffer());
  const text = new TextDecoder("utf-8").decode(bytes);
  els.input.value = text.length > 400000 ? text.slice(0, 400000) + "\n… (only the start is shown; the whole file is checked)" : text;
  fileBytes = bytes; fileName = f.name;
  setStatus(`Loaded ${f.name} (${plural(bytes.length, "byte", "bytes")}). Press Check.`);
}
els.file.addEventListener("change", () => takeFile(els.file.files[0]));
for (const ev of ["dragenter", "dragover"]) els.drop.addEventListener(ev, (e) => { e.preventDefault(); els.drop.classList.add("over"); });
for (const ev of ["dragleave", "drop"]) els.drop.addEventListener(ev, () => els.drop.classList.remove("over"));
els.drop.addEventListener("drop", (e) => { e.preventDefault(); if (e.dataTransfer.files.length) takeFile(e.dataTransfer.files[0]); });

document.querySelectorAll("button.sample").forEach((b) => b.addEventListener("click", async () => {
  await dataReady;
  const s = DATA.samples[Number(b.dataset.sample)];
  els.input.value = s.text; fileBytes = null; fileName = null; els.kind.value = s.kind;
  check({ sample: s });
}));
els.run.addEventListener("click", () => check({}));

// ---------- type detection (a convenience only; the verdict always names the type it was checked as) ----------
function detect(obj) {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return null;
  if ("organisations" in obj || "comparisonAsOfDate" in obj || ("benchmarks" in obj && "crosswalks" in obj)) return { kind: "bundle" };
  const keys = Object.keys(obj);
  let best = null, tie = false;
  for (const [name, e] of Object.entries(DATA.entities)) {
    const props = new Set(e.properties);
    const known = keys.filter((k) => props.has(k)).length;
    const unknown = keys.length - known;
    const req = e.required.length ? e.required.filter((k) => k in obj).length / e.required.length : 0;
    const score = known - 2 * unknown + 4 * req;
    if (!best || score > best.score) { best = { kind: name, score, known }; tie = false; } else if (score === best.score) tie = true;
  }
  return best && best.known > 0 && !tie ? best : null;
}

// ---------- the check ----------
async function check({ sample }) {
  if (busy) return;
  const text = els.input.value;
  if (!fileBytes && !text.trim()) { setStatus("Paste some JSON, choose a file or pick an example first."); els.input.focus(); return; }
  await dataReady;
  const bytes = fileBytes || new TextEncoder().encode(text);
  let kind = els.kind.value, how = sample ? "sample" : "chosen";
  if (kind === "auto") {
    let obj = null, parsed = true;
    try { obj = JSON.parse(fileBytes ? new TextDecoder("utf-8").decode(fileBytes) : text); } catch (e) { parsed = false; }
    const d = parsed ? detect(obj) : null;
    if (d) { kind = d.kind; how = "detected"; }
    else if (!parsed) { kind = "AbsenceEpisode"; how = "unparsed"; }   // the validator reports unreadable JSON before it reads any schema
    else { setStatus("The record type could not be told from its fields. Choose it from the list."); els.kind.focus(); return; }
  }
  busy = true; els.run.disabled = true;
  const started = new Date();
  try {
    const out = await runCheck(DATA, bytes, kind, setStatus);
    const report = kind === "bundle" ? bundleReport(out, how, started) : recordReport(out, kind, how, started);
    render(report);
    setStatus(`Checked in your browser at ${started.toLocaleTimeString("en-GB")}.`);
  } catch (e) {
    setStatus("");
    render({ verdict: "tool_error", kind, how, checked_at: started.toISOString(), title: "The checker could not run", kicker: "not checked",
             summary: [`${e.message || e}. Nothing was sent anywhere. Reload the page and try again, or run the command-line tool: python tools/validate.py schemas/v0.2/<Type>.json your-file.json`], findings: [], notes: [], raw: null });
  } finally { busy = false; els.run.disabled = false; }
}

// ---------- reading the tools' output ----------
const LINE = /^\[([^\]]+)\] (.*?): (.*)$/;
function fieldLabel(where) {
  if (where === "<root>" || where === "") return null;
  return where.replace(/^\//, "").split("/").map((p) => p.replace(/~1/g, "/").replace(/~0/g, "~")).reduce((acc, p) => /^\d+$/.test(p) ? `${acc}[${p}]` : (acc ? `${acc}.${p}` : p), "");
}
function specRow(entity, field) {
  const e = DATA.entities[entity]; if (!e || !field) return null;
  let key = field.replace(/\[\d+\]/g, "[]");
  while (key) {
    if (e.fields[key]) return { key, row: e.fields[key] };
    const cut = Math.max(key.lastIndexOf("."), key.lastIndexOf("[]"));
    if (cut <= 0) break;
    key = key.slice(0, cut);
  }
  return null;
}
const FORMAT_HELP = {
  "date": "A date is written YYYY-MM-DD, for example 2026-03-02, and has to be a real calendar date.",
  "date-time": "A date-time needs a date, a time and a time zone, for example 2026-03-02T09:15:00Z or 2026-03-02T09:15:00+01:00.",
  "uri": "A URI needs a scheme, for example https://example.org/page.",
};
const pyBool = (s) => s === "True" ? "true" : s === "False" ? "false" : s === "None" ? "null" : s;

function explainSchema(kw, where, message, d, entity) {
  const f = fieldLabel(where);
  const field = f ? `${f}` : "The record";
  const cond = d && d.condition ? ` ${d.condition}` : "";
  let m;
  switch (kw) {
    case "required": {
      const name = (d && d.missing) || ((m = message.match(/^'(.+)' is a required property$/)) && m[1]);
      return { field: f ? `${f}.${name}` : name, text: `The required field ${name} is missing${cond}.` };
    }
    case "additionalProperties": {
      const names = ((m = message.match(/\((.*) (?:was|were) unexpected\)/)) && m[1]) || "a field";
      const e = DATA.entities[entity];
      const known = !f && e ? ` The fields an ${entity} can have are: ${e.properties.join(", ")}.` : "";
      const bare = names.replace(/'/g, ""), many = bare.includes(",");
      return { field: f ? `${f}: ${bare}` : bare, text: `The field${many ? "s" : ""} ${bare} ${many ? "are" : "is"} not declared by the schema here. OWHS records are closed: an undeclared field is refused, which is one way identifiers are kept out of a payload.${known}`, link: [DATA.links.privacy, "Privacy profile, P1"] };
    }
    case "type": {
      const t = (m = message.match(/is not of type (.+)$/)) ? m[1].replace(/'/g, "") : "the declared type";
      return { field: f, text: `${field} has the wrong type. It should be ${t.replace(/, /g, " or ")}.` };
    }
    case "format": {
      const fmt = (d && d.format) || ((m = message.match(/is not a '(.+)'$/)) && m[1]);
      return { field: f, text: `${field} is not a valid ${fmt}. ${FORMAT_HELP[fmt] || ""}`.trim() };
    }
    case "pattern": {
      const pat = (m = message.match(/does not match '(.*)'$/)) ? m[1] : "";
      if (pat.startsWith("^owhs:pseudo:")) return { field: f, text: `${field} is not a pseudonym of the OWHS form: owhs:pseudo: followed by 16 to 64 lowercase hexadecimal characters, made with a keyed hash as section 8 describes. A name or a payroll number is never a pseudonym.`, link: [DATA.links.identifiers, "Identifiers and pseudonymisation"] };
      if (pat.startsWith("^owhs-")) return { field: f, text: `An extension namespace inside ext is named owhs- followed by lowercase letters, digits and hyphens, for example owhs-msk.`, link: [DATA.links.profiles, "The profile mechanism"] };
      return { field: f, text: `${field} does not have the form the schema requires (the pattern ${pat}).` };
    }
    case "enum": {
      const allowed = d && d.allowed ? d.allowed.map((v) => JSON.stringify(v)).join(", ") : null;
      return { field: f, text: `${field} is not one of the allowed values${cond}.${allowed ? ` Allowed: ${allowed}.` : ""}` };
    }
    case "const": {
      const want = (m = message.match(/^(.*) was expected$/)) ? pyBool(m[1]) : "a fixed value";
      return { field: f, text: `${field} must be ${want}${cond}.` };
    }
    case "minimum": case "maximum": case "exclusiveMinimum": case "exclusiveMaximum":
      return { field: f, text: `${field} is out of range${cond}: ${message.replace(/^(.*?) is/, "the value $1 is")}.` };
    case "minLength": case "maxLength":
      return { field: f, text: `${field} is too ${kw === "minLength" ? "short" : "long"}.` };
    case "minItems": case "maxItems":
      return { field: f, text: `${field} has ${kw === "minItems" ? "too few" : "too many"} items${cond}.` };
    case "uniqueItems":
      return { field: f, text: `${field} lists the same item more than once.` };
    case "not": {
      if (d && d.banned_keys) {
        const key = (m = message.match(/^'(.+?)' should not be valid/)) ? m[1] : "this key";
        return { field: f, text: `The key ${key} is not allowed inside ${f || "this object"}. Extension objects may not use key names that would carry identifiers or clinical content: ${d.banned_keys.join(", ")}.`, link: [DATA.links.boundary, "Privacy and boundary rules expressed in schema"] };
      }
      if (d && d.forbidden_fields) return { field: f ? f : d.forbidden_fields.join(", "), text: `${d.forbidden_fields.join(d.forbidden_fields.length > 2 ? ", " : " and ")} must not be present${cond}.` };
      if (d && d.no_whitespace) return { field: f, text: `${field} contains whitespace. Identifiers may not contain spaces, tabs or line breaks.` };
      return { field: f, text: `${field} has a combination of values the schema forbids${cond}.` };
    }
    case "anyOf": case "oneOf":
      return { field: f, text: `${field} does not fit ${kw === "oneOf" ? "exactly one" : "any"} of the shapes the schema allows here.${d && d.closest ? ` The nearest shape failed because: ${d.closest.message}` : ""}` };
    case "dependentRequired": {
      const mm = message.match(/^'(.+)' is a dependency of '(.+)'$/);
      return { field: f, text: mm ? `When ${mm[2]} is present, ${mm[1]} must be present too.` : `A field that has to come with another is missing.` };
    }
    case "None": case "False schema":
      return { field: f, text: `${field} is not allowed here${cond}.` };
    case "json": return { field: null, text: "The file is not valid JSON, so nothing else could be checked. JSON allows no comments, no trailing commas and no NaN or Infinity." };
    case "number": return { field: f, text: `${field} is not a finite number. NaN and Infinity are not JSON numbers.` };
    default: return { field: f, text: `${field} does not meet the schema's ${kw} rule${cond}.` };
  }
}

function explainRule(id, message) {
  const r = DATA.rules[id];
  const graph = r && r.source === "supplied-entity graph guide";
  const text = !r ? `This breaks rule ${id}.` : graph ? `This breaks relationship check ${id}, one of the checks the entity-graph checker runs across the records of a bundle.`
    : `This breaks named rule ${id}, a within-record rule the reference validator runs on every ${r.entity}. JSON Schema cannot compare one field with another, so these rules are written in the validator.`;
  return { field: null, text, spec: r ? r.statement : null, link: r ? [r.link, graph ? "Entity-graph guide" : "Named within-record rules"] : null };
}

function recordReport(out, entity, how, started) {
  const lines = out.stdout.split("\n").filter((l) => l.startsWith("["));
  const schemaLines = lines.filter((l) => !/^\[(profile|json|number|C\d+)\]/.test(l));
  const details = out.details && out.details.length === schemaLines.length ? out.details : [];
  const findings = [], notes = [];
  let si = 0;
  for (const l of lines) {
    const m = l.match(LINE); if (!m) continue;
    const [, rule, where, message] = m;
    if (rule === "profile") { notes.push(`${where}: profile semantics not checked. The extension's generic shape was checked; what that profile itself requires was not, because no profile was supplied.`); continue; }
    const isRule = /^C\d+$/.test(rule);
    const d = !isRule && !["json", "number"].includes(rule) ? details[si++] : null;
    const x = isRule ? explainRule(rule, message) : explainSchema(rule, where, message, d, entity);
    const fld = x.field || fieldLabel(where);
    const row = specRow(entity, fld);
    findings.push({ rule, where, message, field: fld, explanation: x.text, schema_description: d && d.description || null,
                    spec: row ? { field: row.key, ...row.row } : (isRule && x.spec ? { rule: rule, statement: x.spec } : null),
                    links: [x.link, row || !isRule ? [DATA.entities[entity].spec, `Spec: ${entity} field table`] : null, isRule ? null : [DATA.links.level1, "Level 1"]].filter(Boolean) });
  }
  const e = DATA.entities[entity];
  const named = Object.entries(DATA.rules).filter(([, r]) => r.entity === entity).map(([k]) => k);
  const base = { kind: "record", entity, how, checked_at: started.toISOString(), schema_id: how === "unparsed" ? null : e.schema_id, out, findings, notes };
  if (how === "unparsed" && !(findings.length === 1 && findings[0].rule === "json")) {
    return { ...base, entity: null, verdict: "not_checked", kicker: "not checked", title: "Choose the record type", findings: [], notes: [],
             summary: ["This page could not read the file to guess its type, but Python could. Choose the record type from the list and check again."] };
  }
  const detectedNote = how === "detected" ? ` Checked as ${entity}, which this page guessed from its fields; if that is wrong, choose the type and check again.` : "";
  if (out.exit_code === 0) {
    return { ...base, verdict: "structurally_conformant", kicker: "pass · Level 1", title: "Structurally conformant",
             summary: [`This ${entity} passed every Level 1 check the reference validator runs: the v${DATA.schema_version} schema with every format asserted${named.length ? `, and the named rule${named.length > 1 ? "s" : ""} ${named.join(", ")}` : ""}.${detectedNote}`,
                       "It is not a compliance finding, a certificate or a privacy assessment. Level 2 and Level 3 were not checked; see what this does not check, below."] };
  }
  if (out.exit_code === 1) {
    const unparsed = findings.length === 1 && findings[0].rule === "json";
    return { ...base, entity: unparsed && how === "unparsed" ? null : entity, verdict: "not_conformant", kicker: "fail · Level 1",
             title: unparsed ? "Not valid JSON" : `Not structurally conformant: ${plural(findings.length, "problem", "problems")}`,
             summary: [unparsed ? "The validator could not read the file as JSON, so it checked nothing else." : `The reference validator found ${plural(findings.length, "problem", "problems")} in this ${entity}. Each one below names the field, the rule and what the specification says.${detectedNote}`] };
  }
  return { ...base, verdict: "tool_error", kicker: "not checked", title: "The validator refused to run", summary: [(out.stderr || out.stdout || "no message").trim()] };
}

function bundleReport(out, how, started) {
  let rep = null;
  try { rep = JSON.parse(out.stdout); } catch (e) { /* reported below */ }
  const base = { kind: "bundle", entity: null, how, checked_at: started.toISOString(), schema_id: "https://openworkplacehealth.org/schemas/bundles/EntityGraph-v0.2.json", out, graph: rep, notes: [] };
  if (!rep || rep.state === "tool_error") return { ...base, verdict: "tool_error", kicker: "not checked", title: "The checker could not run", summary: [rep ? rep.error : (out.stderr || "no report").trim()], findings: [] };
  const findings = rep.errors.map((x) => {
    let rule = x.rule, kw = rule.startsWith("schema:") ? rule.slice(7) : null;
    const where = x.pointer === "" ? "<root>" : x.pointer;
    let ex;
    if (kw) ex = explainSchema(kw, where, x.message, null, null);
    else if (/^[CG]\d+$/.test(rule)) ex = explainRule(rule, x.message);
    else if (rule === "input") ex = explainSchema("json", where, x.message, null, null);
    else if (rule === "S07") ex = { text: "A measurement check failed: the records' contexts, windows, scales or scoring declarations do not fit together, as the entity-graph guide describes.", link: [DATA.links.graph, "Entity-graph guide"] };
    else ex = { text: `The ${rule} check failed.` };
    return { rule, where, message: x.message, field: fieldLabel(where), explanation: ex.text, related: x.related || null,
             spec: ex.spec ? { rule, statement: ex.spec } : null, links: [ex.link, kw ? [DATA.links.level1, "Level 1"] : null].filter(Boolean) };
  });
  const reviews = rep.review_items.map((r) => `${r.pointer}: ${r.message}`);
  const counts = Object.entries(rep.entity_counts || {}).filter(([, n]) => n).map(([k, n]) => `${n} ${k}`).join(", ");
  const notDone = rep.checks_not_evaluated && rep.checks_not_evaluated.length ? [`Not evaluated, because an earlier stage failed or had nothing to work on: ${rep.checks_not_evaluated.join("; ")}.`] : [];
  if (rep.state === "checked_with_limits") {
    return { ...base, findings, verdict: "structurally_conformant", kicker: "pass · checked with limits", title: "Structurally conformant, and the relationship checks passed",
             summary: [`The entity-graph checker read ${counts || "the records"} and ran: ${rep.checks_performed.join(", ")}.`, rep.statement], notes: reviews.length ? [`Review items (not errors): ${reviews.join(" · ")}`] : [] };
  }
  if (rep.state === "not_evaluated") return { ...base, findings, verdict: "not_evaluated", kicker: "nothing to check", title: "The bundle holds no records", summary: [rep.statement] };
  return { ...base, findings, verdict: "not_conformant", kicker: "fail", title: `The bundle failed: ${plural(findings.length, "problem", "problems")}`,
           summary: [`The entity-graph checker ran ${rep.checks_performed.join(", ") || "its first stage"} and found ${plural(findings.length, "problem", "problems")}.`, ...notDone], notes: reviews.length ? [`Review items (not errors): ${reviews.join(" · ")}`] : [] };
}

// ---------- the report (text and JSON) ----------
function reportObject(r) {
  const c = DATA.checker, v = (r.out && r.out.versions) || {};
  return {
    report: "OWHS browser check",
    checker: { name: c.name, version: c.version, page: c.page, reference_tools: c.reference_tools,
               runtime: { pyodide: c.runtime.pyodide, python: v.python || c.runtime.python, jsonschema: v.jsonschema || c.runtime.jsonschema } },
    schema_version: DATA.schema_version, schema: r.schema_id || null, checked_at: r.checked_at,
    input: r.kind === "bundle" ? "entity-graph bundle" : r.entity ? `one ${r.entity} record` : "unreadable input",
    record_type_chosen_by: { detected: "detected by this page from the fields", chosen: "chosen by the person checking", sample: "a repository example", unparsed: "none: the input is not JSON" }[r.how],
    verdict: r.verdict, scope: "Level 1 structural conformance only. Level 2 (code-list currency) and Level 3 (privacy obligations) are not checked.",
    findings: r.findings.map((f) => ({ rule: f.rule, where: f.where, message: f.message, explanation: f.explanation, ...(f.spec ? { spec: f.spec } : {}) })),
    notes: r.notes,
    tool: r.out ? { command: r.out.argv ? r.out.argv.join(" ") : null, exit_code: r.out.exit_code, output: r.kind === "bundle" ? undefined : r.out.stdout.split("\n").filter(Boolean) } : null,
    ...(r.graph ? { entity_graph_report: r.graph } : {}),
  };
}

function reportText(o, r) {
  const L = [];
  L.push("OWHS browser check");
  L.push(`Checker: ${o.checker.name} ${o.checker.version} (${o.checker.page})`);
  for (const [p, h] of Object.entries(o.checker.reference_tools)) L.push(`  ${p} sha256 ${h}`);
  L.push(`Runtime: Pyodide ${o.checker.runtime.pyodide}, Python ${o.checker.runtime.python}, jsonschema ${o.checker.runtime.jsonschema}`);
  L.push(`Schema version: ${o.schema_version}${o.schema ? ` (${o.schema})` : ""}`);
  L.push(`Checked: ${o.checked_at}`);
  L.push(`Input: ${o.input}${o.record_type_chosen_by ? `, type ${o.record_type_chosen_by}` : ""}`);
  L.push(`Result: ${r.title}`);
  L.push(`Scope: ${o.scope}`);
  for (const s of r.summary || []) if (s) L.push("", s);
  if (o.findings.length) L.push("", "Findings:");
  o.findings.forEach((f, i) => {
    L.push(`${i + 1}. [${f.rule}] ${f.where}: ${f.message}`);
    L.push(`   ${f.explanation}`);
    if (f.spec && f.spec.statement) L.push(`   Spec: ${f.spec.statement}`);
    else if (f.spec) L.push(`   Spec field table: ${f.spec.field}, ${f.spec.type}, ${f.spec.required ? "required" : "optional"}${f.spec.codelist ? `, ${f.spec.codelist}` : ""}, privacy class ${f.spec.privacy}`);
  });
  for (const n of o.notes) L.push("", `Note: ${n}`);
  if (o.tool) {
    L.push("", `Tool: ${o.tool.command}, exit code ${o.tool.exit_code}`);
    if (o.tool.output) for (const l of o.tool.output) L.push(`  ${l}`);
  }
  return L.join("\n") + "\n";
}

// ---------- rendering ----------
function render(r) {
  const obj = DATA ? reportObject(r) : { verdict: r.verdict, findings: [], notes: [] };
  els.verdict.className = "verdict " + (r.verdict === "structurally_conformant" ? "pass" : r.verdict === "not_conformant" ? "fail" : "neutral");
  els.kicker.textContent = r.kicker;
  els.title.textContent = r.title;
  els.summary.replaceChildren(...(r.summary || []).filter(Boolean).map((s) => el("p", { text: s })));
  els.findings.replaceChildren(...r.findings.map((f, i) => {
    const dl = el("dl", {});
    if (f.spec && f.spec.statement) dl.append(el("dt", { text: "The spec says" }), el("dd", { text: f.spec.statement }));
    else if (f.spec) dl.append(el("dt", { text: "The spec says" }), el("dd", {}, `${f.spec.field}: ${f.spec.type}, ${f.spec.required ? "required" : "optional"}${f.spec.codelist ? `, ${f.spec.codelist}` : ""}; privacy class ${f.spec.privacy}${f.spec.anchor ? `; ${f.spec.anchor}` : ""}.`));
    if (f.schema_description) dl.append(el("dt", { text: "The schema says" }), el("dd", { text: f.schema_description }));
    dl.append(el("dt", { text: "The validator said" }), el("dd", { class: "raw", text: f.message.length > 400 ? f.message.slice(0, 400) + " …" : f.message }));
    if (f.related) dl.append(el("dt", { text: "Related" }), el("dd", { class: "raw", text: f.related.join(", ") }));
    if (f.links && f.links.length) dl.append(el("dt", { text: "Read more" }), el("dd", {}, ...f.links.flatMap(([h, t], j) => j ? [" · ", link(h, t)] : [link(h, t)])));
    return el("li", { class: "finding" },
      el("div", { class: "fh" }, el("span", { class: "rule", text: f.rule }), el("span", { class: "where", text: f.field || (f.where === "<root>" ? "the record as a whole" : f.where) })),
      el("div", { class: "fb" }, el("p", { class: "plain", text: f.explanation }), dl));
  }));
  els.notes.replaceChildren(...(r.notes.length ? [el("ul", {}, ...r.notes.map((n) => el("li", { text: n })))] : []));
  els.reportJson.textContent = JSON.stringify(obj, null, 1);
  els.reportText.textContent = DATA ? reportText(obj, r) : r.title;
  els.copyStatus.textContent = "";
  els.result.hidden = false;
  els.result.focus({ preventScroll: true });
  els.result.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
}

async function copy(text, what) {
  try { await navigator.clipboard.writeText(text); els.copyStatus.textContent = `Copied the report as ${what}.`; }
  catch (e) {
    const t = el("textarea", { readonly: "", "aria-hidden": "true" }); t.value = text; t.style.position = "fixed"; t.style.opacity = "0";
    document.body.append(t); t.select();
    const ok = document.execCommand && document.execCommand("copy"); t.remove();
    els.copyStatus.textContent = ok ? `Copied the report as ${what}.` : "Your browser blocked copying. Open \"Show the report\" and copy it by hand.";
  }
}
els.copyText.addEventListener("click", () => copy(els.reportText.textContent, "text"));
els.copyJson.addEventListener("click", () => copy(els.reportJson.textContent, "JSON"));
els.saveJson.addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([els.reportJson.textContent], { type: "application/json" }));
  const a = el("a", { href: url, download: `owhs-check-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.json` });
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
