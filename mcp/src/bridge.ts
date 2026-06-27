import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const currentFile = fileURLToPath(import.meta.url);
const currentDir = path.dirname(currentFile);
const repoRoot = process.env.SKILLROUTE_REPO_ROOT
  ? path.resolve(process.env.SKILLROUTE_REPO_ROOT)
  : path.resolve(currentDir, "../..");
const pythonPath = process.env.SKILLROUTE_PYTHON ?? "python3";
const timeoutMs = Number.parseInt(process.env.SKILLROUTE_BRIDGE_TIMEOUT_MS ?? "30000", 10);

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
  let timedOut = false;
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => {
    stdout += chunk;
  });
  child.stderr.on("data", (chunk) => {
    stderr += chunk;
  });

  // The child may exit before stdin is fully written; swallow the resulting EPIPE
  // so it does not crash the MCP server with an unhandled error event.
  child.stdin.on("error", () => {});
  child.stdin.end(JSON.stringify(payload));

  const timer =
    Number.isFinite(timeoutMs) && timeoutMs > 0
      ? setTimeout(() => {
          timedOut = true;
          child.kill("SIGKILL");
        }, timeoutMs)
      : undefined;

  try {
    const exitCode = await new Promise<number | null>((resolve, reject) => {
      child.on("error", reject);
      child.on("close", resolve);
    });

    if (timedOut) {
      throw new Error(`SkillRoute bridge timed out after ${timeoutMs}ms`);
    }

    if (exitCode !== 0) {
      throw new Error(bridgeErrorMessage(stdout, stderr, exitCode));
    }

    try {
      return JSON.parse(stdout);
    } catch (error) {
      throw new Error(`SkillRoute bridge returned invalid JSON: ${(error as Error).message}`);
    }
  } finally {
    if (timer) {
      clearTimeout(timer);
    }
  }
}

function bridgeErrorMessage(stdout: string, stderr: string, exitCode: number | null): string {
  // The Python bridge prints {"error": {"type", "message"}} to stdout on failure.
  try {
    const parsed = JSON.parse(stdout) as { error?: { message?: string } };
    if (parsed.error?.message) {
      return parsed.error.message;
    }
  } catch {
    // fall through to raw output
  }
  return stderr.trim() || stdout.trim() || `SkillRoute bridge exited with ${exitCode}`;
}
