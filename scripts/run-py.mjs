// Runs a Python entry point from the project venv with the monorepo source paths on PYTHONPATH.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const win = process.platform === "win32";
const venvPy = path.join(root, ".venv", win ? "Scripts/python.exe" : "bin/python");
const python = existsSync(venvPy) ? venvPy : win ? "python" : "python3";
const srcs = [
  "packages/domain/src", "packages/planning_engine/src", "packages/optimization_engine/src",
  "packages/finance_engine/src", "packages/integrations/src", "packages/agent_tools/src", "apps/api/src", "apps/worker/src",
].map((p) => path.join(root, p));

const env = { ...process.env, PYTHONPATH: [...srcs, process.env.PYTHONPATH || ""].join(path.delimiter) };
const target = process.argv[2];
const extra = process.argv.slice(3);
const commands = {
  api: ["-m", "uvicorn", "nodal_api.main:get_app", "--factory", "--host", "127.0.0.1", "--port", "8000"],
  worker: ["-m", "nodal_worker.main"],
  pytest: ["-m", "pytest", "-q"],
  benchmark: [path.join(root, "tests/benchmark/solve_network.py")],
};
if (!commands[target]) {
  console.error(`usage: node scripts/run-py.mjs <${Object.keys(commands).join("|")}> [args]`);
  process.exit(2);
}
const child = spawn(python, [...commands[target], ...extra], { cwd: root, env, stdio: "inherit" });
child.on("exit", (code) => process.exit(code ?? 1));
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => child.kill(sig));
