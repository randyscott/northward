// Start and stop a real `northward serve` for browser tests: a fresh SQLite database seeded with the rules only, and the
// built frontend from dist/.
import { type ChildProcess, execFileSync, spawn } from "node:child_process";
import { cpSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..", "..");
const NORTHWARD = process.env.NORTHWARD_BIN ?? join(REPO, ".venv", "bin", "northward");

export interface Server {
  url: string;
  stop(): Promise<void>;
}

/** A directory holding a new database (the rules seeded, and the example profile if asked) and its run outputs. */
export function freshWorkspace({ example = false } = {}): string {
  const dir = mkdtempSync(join(tmpdir(), "northward-e2e-"));
  cpSync(join(REPO, "data", "rules"), join(dir, "data", "rules"), { recursive: true });
  if (example)
    cpSync(join(REPO, "data", "profiles", "example"), join(dir, "data", "profiles", "example"), { recursive: true });
  const db = ["--db", `sqlite:///${join(dir, "northward.db")}`];
  execFileSync(NORTHWARD, [...db, "db", "init"], { stdio: "pipe" });
  execFileSync(NORTHWARD, [...db, "db", "seed", join(dir, "data")], { stdio: "pipe" });
  return dir;
}

export async function startServer(workspace: string, port = 8799): Promise<Server> {
  const args = ["--db", `sqlite:///${join(workspace, "northward.db")}`, "--runs-dir", join(workspace, "runs")];
  const child: ChildProcess = spawn(
    NORTHWARD,
    [...args, "serve", "--port", String(port), "--workers", "2", "--ui-dir", resolve(HERE, "..", "dist")],
    { stdio: "pipe" },
  );
  let output = "";
  child.stdout?.on("data", (chunk) => (output += chunk));
  child.stderr?.on("data", (chunk) => (output += chunk));
  const url = `http://127.0.0.1:${port}`;
  for (let attempt = 0; attempt < 120; attempt++) {
    try {
      if ((await fetch(`${url}/api/health`)).ok) break;
    } catch {
      // not up yet
    }
    if (child.exitCode !== null) throw new Error(`northward serve exited:\n${output}`);
    await new Promise((r) => setTimeout(r, 250));
  }
  return {
    url,
    stop: () =>
      new Promise((done) => {
        child.once("exit", () => done());
        child.kill("SIGINT");
      }),
  };
}
