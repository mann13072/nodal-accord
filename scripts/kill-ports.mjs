// Frees the given TCP ports by terminating whatever process is listening on them (stale dev servers).
import { execSync } from "node:child_process";

const ports = process.argv.slice(2).map(Number).filter(Boolean);
for (const port of ports) {
  try {
    if (process.platform === "win32") {
      const out = execSync(`netstat -ano -p tcp`, { encoding: "utf8" });
      const pids = new Set(
        out.split(/\r?\n/)
          .filter((l) => /LISTENING/.test(l) && new RegExp(`[:.]${port}\\s`).test(l))
          .map((l) => l.trim().split(/\s+/).pop())
          .filter((pid) => pid && pid !== "0"),
      );
      for (const pid of pids) {
        execSync(`taskkill /PID ${pid} /T /F`, { stdio: "ignore" });
        console.log(`[kill-ports] freed :${port} (pid ${pid})`);
      }
    } else {
      const pids = execSync(`lsof -ti tcp:${port} -sTCP:LISTEN || true`, { encoding: "utf8" }).split(/\s+/).filter(Boolean);
      for (const pid of pids) {
        process.kill(Number(pid), "SIGTERM");
        console.log(`[kill-ports] freed :${port} (pid ${pid})`);
      }
    }
  } catch {
    // nothing listening, or not permitted: leave it to the server to report a bind error
  }
}
