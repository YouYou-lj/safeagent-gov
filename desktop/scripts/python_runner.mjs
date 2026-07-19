import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDirectory, "..", "..");
const python = process.platform === "win32"
  ? path.join(projectRoot, ".venv", "Scripts", "python.exe")
  : path.join(projectRoot, ".venv", "bin", "python");

const result = spawnSync(python, process.argv.slice(2), {
  cwd: path.resolve(scriptDirectory, ".."),
  env: process.env,
  stdio: "inherit",
});
if (result.error) {
  console.error(`Unable to start project Python: ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status ?? 1);
