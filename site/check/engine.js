// The checker engine: Python (Pyodide) with jsonschema, and the repository's own tools, loaded from this site the first
// time a check is asked for. Every fetch here is a file of this site; the visitor's file is only ever written into the
// interpreter's in-memory file system and never leaves the page.
const BASE = new URL("./", import.meta.url);
let engine = null;

async function fetchOk(url, as) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`could not load ${new URL(url).pathname} (${r.status})`);
  return as === "json" ? r.json() : r.text();
}

async function start(data, onStage) {
  onStage("Loading Python…");
  const pyodideDir = new URL(data.engine.pyodide_dir, BASE).href;
  const { loadPyodide } = await import(pyodideDir + "pyodide.mjs");
  const py = await loadPyodide({ indexURL: pyodideDir, stdout: () => {}, stderr: () => {} });
  onStage("Loading jsonschema…");
  await py.loadPackage(data.engine.wheels.map((w) => new URL("vendor/" + w, BASE).href), { messageCallback: () => {}, errorCallback: () => {} });
  onStage("Loading the validator…");
  const [files, runner] = await Promise.all([fetchOk(new URL(data.engine.files, BASE).href, "json"), fetchOk(new URL(data.engine.runner, BASE).href, "text")]);
  for (const [path, text] of Object.entries(files.files)) {
    const full = "/owhs/" + path;
    py.FS.mkdirTree(full.slice(0, full.lastIndexOf("/")));
    py.FS.writeFile(full, text);
  }
  py.runPython(runner);
  const call = (name, ...args) => {
    const fn = py.globals.get(name);
    try { return fn(...args); } finally { fn.destroy(); }
  };
  const mismatched = JSON.parse(call("owhs_verify", JSON.stringify(files.sha256)));
  if (mismatched.length) throw new Error("the copies of the tools did not load intact: " + mismatched.join(", "));
  return { py, call, versions: JSON.parse(call("owhs_versions")) };
}

export function loadEngine(data, onStage = () => {}) {
  if (!engine) engine = start(data, onStage).catch((e) => { engine = null; throw e; });
  return engine;
}

// kind is "bundle" or a v0.2 record type; bytes is a Uint8Array of the file exactly as given.
export async function runCheck(data, bytes, kind, onStage) {
  const { py, call, versions } = await loadEngine(data, onStage);
  const path = "/tmp/owhs-input.json";
  py.FS.writeFile(path, bytes);
  try {
    const out = JSON.parse(call("owhs_check", kind, path));
    out.versions = versions;
    return out;
  } finally {
    try { py.FS.unlink(path); } catch (e) { /* already gone */ }
  }
}
