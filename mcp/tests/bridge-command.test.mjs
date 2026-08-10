import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, test } from "node:test";

import { resolveBridgeCommand } from "../build/bridge.js";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
// A directory tree with no src/skillroute, mimicking an npx/global install layout.
const installedDir = path.join(mkdtempSync(path.join(os.tmpdir(), "skillroute-mcp-")), "build");

const ENV_KEYS = ["SKILLROUTE_REPO_ROOT", "SKILLROUTE_PYTHON", "PYTHONPATH"];
let savedEnv;

beforeEach(() => {
  savedEnv = Object.fromEntries(ENV_KEYS.map((key) => [key, process.env[key]]));
  for (const key of ENV_KEYS) {
    delete process.env[key];
  }
});

afterEach(() => {
  for (const key of ENV_KEYS) {
    if (savedEnv[key] === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = savedEnv[key];
    }
  }
});

test("checkout mode: runs python -m skillroute from the repo root with PYTHONPATH", () => {
  // build/bridge.js sits inside the checkout, so autodetection finds src/skillroute.
  const resolved = resolveBridgeCommand("route");
  assert.equal(resolved.command, "python3");
  assert.deepEqual(resolved.args, ["-m", "skillroute", "bridge", "route"]);
  assert.equal(resolved.cwd, repoRoot);
  assert.equal(resolved.env.PYTHONPATH, path.join(repoRoot, "src"));
});

test("checkout mode: SKILLROUTE_REPO_ROOT override and PYTHONPATH prepend", () => {
  process.env.SKILLROUTE_REPO_ROOT = repoRoot;
  process.env.PYTHONPATH = "/existing";
  const resolved = resolveBridgeCommand("search", { moduleDir: installedDir });
  assert.equal(resolved.cwd, repoRoot);
  assert.equal(
    resolved.env.PYTHONPATH,
    `${path.join(repoRoot, "src")}${path.delimiter}/existing`
  );
});

test("checkout mode: SKILLROUTE_PYTHON selects the interpreter", () => {
  process.env.SKILLROUTE_PYTHON = "/opt/py/bin/python";
  const resolved = resolveBridgeCommand("inspect");
  assert.equal(resolved.command, "/opt/py/bin/python");
  assert.deepEqual(resolved.args, ["-m", "skillroute", "bridge", "inspect"]);
});

test("installed mode: falls back to the skillroute console script", () => {
  const resolved = resolveBridgeCommand("route", { moduleDir: installedDir });
  assert.equal(resolved.command, "skillroute");
  assert.deepEqual(resolved.args, ["bridge", "route"]);
  assert.equal(resolved.cwd, undefined);
  assert.equal(resolved.env.PYTHONPATH, undefined);
});

test("installed mode: SKILLROUTE_PYTHON forces python -m skillroute without PYTHONPATH", () => {
  process.env.SKILLROUTE_PYTHON = "python3.13";
  const resolved = resolveBridgeCommand("route", { moduleDir: installedDir });
  assert.equal(resolved.command, "python3.13");
  assert.deepEqual(resolved.args, ["-m", "skillroute", "bridge", "route"]);
  assert.equal(resolved.env.PYTHONPATH, undefined);
});
