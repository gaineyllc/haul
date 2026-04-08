#!/usr/bin/env node
/**
 * haul CLI / MCP launcher
 * 
 * Usage:
 *   npx haul                    # start MCP server (stdio)
 *   npx haul --http             # start MCP server (HTTP/SSE on :8766)
 *   npx haul "The Boys S05E01"  # hunt directly from CLI
 *   npx haul --install          # run uv sync
 *   npx haul setup              # interactive credential setup
 */
const { spawn } = require("child_process");
const path = require("path");
const fs   = require("fs");
const os   = require("os");

const ROOT    = path.resolve(__dirname, "..");
const IS_WIN  = process.platform === "win32";
const args    = process.argv.slice(2);

function findPython() {
  const venv = IS_WIN
    ? path.join(ROOT, ".venv", "Scripts", "python.exe")
    : path.join(ROOT, ".venv", "bin", "python");
  return fs.existsSync(venv) ? venv : (IS_WIN ? "python" : "python3");
}

function run(cmd, cmdArgs) {
  const proc = spawn(cmd, cmdArgs, { cwd: ROOT, stdio: "inherit",
    env: { ...process.env } });
  proc.on("exit", code => process.exit(code ?? 0));
  proc.on("error", err => {
    console.error(`[haul] Error: ${err.message}`);
    process.exit(1);
  });
}

if (args.includes("--install")) {
  const uv = fs.existsSync(path.join(os.homedir(), ".local", "bin",
    IS_WIN ? "uv.exe" : "uv"))
    ? path.join(os.homedir(), ".local", "bin", IS_WIN ? "uv.exe" : "uv")
    : "uv";
  run(uv, ["sync"]);
} else if (args.includes("setup")) {
  run(findPython(), ["-m", "src.haul.setup"]);
} else if (args.length > 0 && !args[0].startsWith("--")) {
  // Direct query: haul "The Boys S05E01"
  run(findPython(), ["-m", "src.haul.cli", ...args]);
} else {
  // MCP server
  run(findPython(), ["-m", "src.mcp_server", ...args]);
}
