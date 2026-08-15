import { spawn } from "node:child_process";
import { accessSync, constants, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const currentFile = fileURLToPath(import.meta.url);
const currentDir = path.dirname(currentFile);

export type BridgeOperation = "route" | "search" | "inspect";

export interface BridgeCommand {
  command: string;
  args: string[];
  cwd: string | undefined;
  env: NodeJS.ProcessEnv;
}

/**
 * Decide how to invoke the SkillRoute Python bridge.
 *
 * In a repo checkout (or with SKILLROUTE_REPO_ROOT set) the bridge runs
 * `python -m skillroute` against the checkout's src tree. Outside a checkout
 * (npx / global install) it prefers an installed `skillroute` console script
 * (pipx / pip / uv tool), falls back to `uvx --from skillroute` (zero-install,
 * requires uv) when that script is missing, or `$SKILLROUTE_PYTHON -m skillroute`
 * when set.
 */
export function resolveBridgeCommand(
  operation: BridgeOperation,
  options: { moduleDir?: string } = {}
): BridgeCommand {
  const bridgeArgs = ["bridge", operation];
  const repoRoot = resolveRepoRoot(options.moduleDir ?? currentDir);
  if (repoRoot) {
    const srcPath = path.join(repoRoot, "src");
    return {
      command: process.env.SKILLROUTE_PYTHON ?? "python3",
      args: ["-m", "skillroute", ...bridgeArgs],
      cwd: repoRoot,
      env: {
        ...process.env,
        PYTHONPATH: process.env.PYTHONPATH
          ? `${srcPath}${path.delimiter}${process.env.PYTHONPATH}`
          : srcPath
      }
    };
  }
  if (process.env.SKILLROUTE_PYTHON) {
    return {
      command: process.env.SKILLROUTE_PYTHON,
      args: ["-m", "skillroute", ...bridgeArgs],
      cwd: undefined,
      env: { ...process.env }
    };
  }
  // Prefer an installed `skillroute` console script (pipx / pip / uv tool), and
  // fall back to `uvx --from skillroute` so a bare `npx @skillroute/mcp-server`
  // (or the dsh bundle) needs no separate Python install. When neither is on
  // PATH, keep the canonical command so callBridge's ENOENT handler still
  // surfaces the install hint.
  if (isOnPath("skillroute")) {
    return { command: "skillroute", args: bridgeArgs, cwd: undefined, env: { ...process.env } };
  }
  if (isOnPath("uvx")) {
    return {
      command: "uvx",
      args: ["--from", "skillroute", "skillroute", ...bridgeArgs],
      cwd: undefined,
      env: { ...process.env }
    };
  }
  return { command: "skillroute", args: bridgeArgs, cwd: undefined, env: { ...process.env } };
}

function resolveRepoRoot(moduleDir: string): string | undefined {
  const override = process.env.SKILLROUTE_REPO_ROOT;
  if (override) {
    return path.resolve(override);
  }
  const candidate = path.resolve(moduleDir, "../..");
  return existsSync(path.join(candidate, "src", "skillroute")) ? candidate : undefined;
}

/**
 * Whether `command` names an executable on PATH. Used to pick the zero-install
 * `uvx` fallback only when a real `skillroute` console script is not already
 * installed; a PATH miss falls through to the canonical command so the caller's
 * ENOENT handling still produces the install-hint error.
 */
function isOnPath(command: string): boolean {
  const extensions =
    process.platform === "win32"
      ? (process.env.PATHEXT ?? ".EXE;.CMD;.BAT;.COM").toLowerCase().split(";")
      : [""];
  for (const dir of (process.env.PATH ?? "").split(path.delimiter)) {
    const trimmed = dir.trim();
    if (!trimmed) continue;
    for (const ext of extensions) {
      try {
        accessSync(path.join(trimmed, command + ext), constants.X_OK);
        return true;
      } catch {
        // keep looking
      }
    }
  }
  return false;
}

function bridgeTimeoutMs(): number {
  return Number.parseInt(process.env.SKILLROUTE_BRIDGE_TIMEOUT_MS ?? "30000", 10);
}

export async function callBridge(operation: BridgeOperation, payload: unknown): Promise<unknown> {
  const { command, args, cwd, env } = resolveBridgeCommand(operation);
  const timeoutMs = bridgeTimeoutMs();

  const child = spawn(command, args, {
    cwd,
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
      child.on("error", (error: NodeJS.ErrnoException) => {
        if (error.code === "ENOENT") {
          reject(
            new Error(
              `SkillRoute bridge command not found: ${command}. Install the Python ` +
                "package (`pipx install skillroute`) or `uv` (`uvx --from skillroute skillroute`), " +
                "or set SKILLROUTE_PYTHON / SKILLROUTE_REPO_ROOT to a working SkillRoute environment."
            )
          );
          return;
        }
        reject(error);
      });
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
