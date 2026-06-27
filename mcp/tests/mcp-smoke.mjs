import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const testFile = fileURLToPath(import.meta.url);
const mcpRoot = path.resolve(path.dirname(testFile), "..");
const repoRoot = path.resolve(mcpRoot, "..");
const tempDir = mkdtempSync(path.join(tmpdir(), "skillroute-mcp-"));
const catalog = path.join(tempDir, "catalog.db");
const python = process.env.SKILLROUTE_PYTHON ?? "python3";
const pythonEnv = {
  ...process.env,
  PYTHONPATH: process.env.PYTHONPATH
    ? `${path.join(repoRoot, "src")}${path.delimiter}${process.env.PYTHONPATH}`
    : path.join(repoRoot, "src")
};

try {
  const indexResult = spawnSync(
    python,
    [
      "-m",
      "skillroute",
      "--catalog",
      catalog,
      "index",
      "--root",
      path.join(repoRoot, "tests", "fixtures", "skills")
    ],
    { cwd: repoRoot, env: pythonEnv, encoding: "utf8" }
  );
  if (indexResult.status !== 0) {
    throw new Error(indexResult.stderr || indexResult.stdout || "failed to index fixture catalog");
  }

  const transport = new StdioClientTransport({
    command: "node",
    args: [path.join(mcpRoot, "build", "index.js")],
    env: { ...pythonEnv, SKILLROUTE_CATALOG_PATH: catalog }
  });
  const client = new Client({ name: "skillroute-smoke", version: "0.1.0" });
  await client.connect(transport);

  try {
    const route = await client.callTool({
      name: "skillroute.route",
      arguments: { request: "Build a TypeScript MCP stdio server with tools", catalog }
    });
    const routePayload = JSON.parse(route.content[0].text);
    assert(routePayload.candidates[0].name === "mcp-server-patterns", "route returned MCP skill first");

    const search = await client.callTool({
      name: "skillroute.search",
      arguments: { query: "Astra vector LangChain backend", catalog }
    });
    const searchPayload = JSON.parse(search.content[0].text);
    assert(searchPayload[0].name === "astra-vector-backend", "search returned Astra backend first");

    const inspect = await client.callTool({
      name: "skillroute.inspect_skill",
      arguments: { skill_id: "mcp-server-patterns", catalog }
    });
    const inspectPayload = JSON.parse(inspect.content[0].text);
    assert(inspectPayload.name === "mcp-server-patterns", "inspect returned requested skill");
  } finally {
    // Always tear down the spawned server process, even if an assertion throws.
    await client.close();
  }
} finally {
  rmSync(tempDir, { recursive: true, force: true });
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

