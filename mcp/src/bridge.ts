import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const currentFile = fileURLToPath(import.meta.url);
const currentDir = path.dirname(currentFile);
const repoRoot = path.resolve(currentDir, "../..");
const pythonPath = process.env.SKILLROUTE_PYTHON ?? "python3";

export type BridgeOperation = "route" | "search" | "inspect";

export async function callBridge(operation: BridgeOperation, payload: unknown): Promise<unknown> {
  const env = {
    ...process.env,
    PYTHONPATH: process.env.PYTHONPATH
      ? `${path.join(repoRoot, "src")}${path.delimiter}${process.env.PYTHONPATH}`
      : path.join(repoRoot, "src")
  };

  const child = spawn(pythonPath, ["-m", "skillroute", "bridge", operation], {
    cwd: repoRoot,
    env,
    stdio: ["pipe", "pipe", "pipe"]
  });

  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => {
    stdout += chunk;
  });
  child.stderr.on("data", (chunk) => {
    stderr += chunk;
  });

  child.stdin.end(JSON.stringify(payload));

  const exitCode = await new Promise<number | null>((resolve, reject) => {
    child.on("error", reject);
    child.on("close", resolve);
  });

  if (exitCode !== 0) {
    throw new Error(stderr.trim() || stdout.trim() || `SkillRoute bridge exited with ${exitCode}`);
  }

  try {
    return JSON.parse(stdout);
  } catch (error) {
    throw new Error(`SkillRoute bridge returned invalid JSON: ${(error as Error).message}`);
  }
}

