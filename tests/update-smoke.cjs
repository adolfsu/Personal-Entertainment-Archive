// Run with PEA_PLAYWRIGHT pointing to Playwright and PEA_PYTHON to Python.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const net = require("node:net");
const cp = require("node:child_process");
const { chromium } = require(process.env.PEA_PLAYWRIGHT || "playwright");
const source = path.resolve(__dirname, "..");
const python = process.env.PEA_PYTHON || "python";
const names = ["web", "server.py", "update_release.py", "VERSION", "启动.bat", "README.md", "使用说明.md", "CHANGELOG.md", "发布说明.md"];
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function idlePort() {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  await new Promise(resolve => server.close(resolve));
  return port;
}
async function until(fn) {
  const deadline = Date.now() + 35000;
  while (Date.now() < deadline) {
    try { const value = await fn(); if (value) return value; } catch {}
    await pause(150);
  }
  throw Error("Timed out waiting for update");
}
function copyApp(target) {
  fs.mkdirSync(target);
  for (const name of names) fs.cpSync(path.join(source, name), path.join(target, name), { recursive: true });
}
function instrument(target, fail = false) {
  const filename = path.join(target, "server.py");
  const code = fs.readFileSync(filename, "utf8");
  const init = [
    'if __name__ == "__main__":',
    '    if os.environ.get("PEA_SMOKE_PID"):',
    '        update_release.Path(os.environ["PEA_SMOKE_PID"]).write_text(str(os.getpid()), encoding="ascii")',
    ...(fail ? ["    raise SystemExit(21)"] : [])
  ].join("\n");
  fs.writeFileSync(filename, code.replace('if __name__ == "__main__":', init));
}
const fixtureServer = [
  "import shutil, json, os, server, update_release as u",
  "from pathlib import Path",
  'Path(os.environ["PEA_SMOKE_PID"]).write_text(str(os.getpid()), encoding="ascii")',
  'u.fetch_release = lambda: json.loads(Path(os.environ["PEA_SMOKE_META"]).read_bytes())',
  'u.download_package = lambda release, path: shutil.copyfile(os.environ["PEA_SMOKE_ZIP"], path)',
  "raise SystemExit(server.main() or 0)"
].join("\n");

(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    for (const scenario of ["success", "tamper", "rollback"]) {
      const root = fs.mkdtempSync(path.join(os.tmpdir(), "pea-update-smoke-"));
      const live = path.join(root, "live"), incoming = path.join(root, "release"), dist = path.join(root, "dist");
      copyApp(live);
      copyApp(incoming);
      instrument(live);
      instrument(incoming, scenario === "rollback");
      fs.writeFileSync(path.join(live, "VERSION"), "1.9.0\n");
      fs.writeFileSync(path.join(incoming, "VERSION"), "1.10.0\n");
      const built = cp.spawnSync(python, ["-B", path.join(incoming, "update_release.py"), "build", "--out", dist], { cwd: incoming, encoding: "utf8" });
      assert.equal(built.status, 0, built.stderr);
      const zip = path.join(dist, "pea-update.zip"), meta = path.join(dist, "pea-update.json");
      if (scenario === "tamper") fs.appendFileSync(zip, Buffer.from([1]));
      const port = await idlePort(), origin = "http://127.0.0.1:" + port;
      const pid = path.join(root, "server.pid");
      const child = cp.spawn(python, ["-B", "-c", fixtureServer], {
        cwd: live, windowsHide: true,
        env: { ...process.env, GRDAG_BASE_DIR: live, GRDAG_PORT: String(port), GRDAG_NO_BROWSER: "1",
          PEA_SMOKE_PID: pid, PEA_SMOKE_ZIP: zip, PEA_SMOKE_META: meta }
      });
      let output = "";
      child.stdout.on("data", x => output += x);
      child.stderr.on("data", x => output += x);
      const mobile = scenario === "success";
      const page = await browser.newPage({ viewport: mobile ? { width: 390, height: 844 } : { width: 1360, height: 900 }, reducedMotion: "reduce" });
      const request = endpoint => fetch(origin + endpoint, { signal: AbortSignal.timeout(1500) }).then(response => response.json());
      page.setDefaultTimeout(10000);
      try {
        await until(async () => (await request("/api/update/health")).version === "1.9.0");
        const archive = path.join(live, "data/library.json");
        const before = fs.readFileSync(archive);
        await page.goto(origin);
        await page.waitForFunction(() => document.getElementById("sidebarArchiveSummary").textContent.trim());
        if (mobile) await page.locator("#sidebarToggle").click();
        await page.locator("#menuBtn").click();
        await page.locator("#updateCheck").click();
        await page.locator("#updateStatus").getByText("可更新到 v1.10.0。").waitFor();
        await page.evaluate(() => { window.confirm = () => false; });
        await page.locator("#updateInstall").click();
        assert.equal((await request("/api/update/status")).job, undefined);
        await page.evaluate(() => { window.confirm = () => true; });
        await page.locator("#updateInstall").click();
        let state;
        const expected = scenario === "success" ? "installed" : scenario === "tamper" ? "failed" : "rolled-back";
        await until(async () => { state = await request("/api/update/status"); return state.phase === expected; });
        assert.equal((await request("/api/update/health")).version, mobile ? "1.10.0" : "1.9.0");
        assert.deepEqual(fs.readFileSync(archive), before);
        if (mobile) assert.ok(fs.existsSync(path.join(live, ".pea-updates", state.job, "previous", "server.py")));
        if (scenario === "tamper") await page.locator("#updateStatus").getByText(/校验|大小/).waitFor();
        console.log("Edge: " + scenario + " passed, archive unchanged.");
      } catch (error) {
        const stateFile = path.join(live, ".pea-updates/state.json");
        if (fs.existsSync(stateFile)) {
          const state = JSON.parse(fs.readFileSync(stateFile, "utf8"));
          console.error(state);
          const log = path.join(live, ".pea-updates", state.job, "update.log");
          if (fs.existsSync(log)) console.error(fs.readFileSync(log, "utf8"));
        }
        console.error(output);
        throw error;
      } finally {
        await page.close();
        try { process.kill(Number(fs.readFileSync(pid, "ascii"))); } catch {}
        if (child.exitCode === null) child.kill();
      }
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
