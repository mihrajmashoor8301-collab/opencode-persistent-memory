import { tool } from "@opencode-ai/plugin"
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { homedir } from "node:os"
import { join, dirname, resolve } from "node:path"
import { readFile } from "node:fs/promises"
import { fileURLToPath } from "node:url"

const execFileAsync = promisify(execFile)
const configPath = join(process.env.XDG_CONFIG_HOME || join(homedir(), ".config"), "opencode", "persistent-memory.json")
const sourceRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..")
const defaults = {
  python: process.env.OPENCODE_MEMORY_PYTHON || join(sourceRoot, ".venv", "bin", "python3"),
  cli: process.env.OPENCODE_MEMORY_CLI || join(sourceRoot, "memory", "memory_cli.py"),
  projectRoot: sourceRoot,
  memoryHome: process.env.OPENCODE_MEMORY_HOME || join(homedir(), "ai-memory"),
  ollamaUrl: process.env.OPENCODE_MEMORY_OLLAMA_URL || process.env.OLLAMA_HOST || "http://localhost:11434",
  embeddingModel: process.env.OPENCODE_MEMORY_EMBEDDING_MODEL || "nomic-embed-text",
}

async function run(args: string[]) {
  try {
    let config = defaults
    try { config = { ...defaults, ...JSON.parse(await readFile(configPath, "utf8")) } } catch { /* use environment defaults */ }
    const { stdout, stderr } = await execFileAsync(config.python, [config.cli, ...args], {
      cwd: config.projectRoot,
      timeout: 60000,
      maxBuffer: 1024 * 1024,
      env: { ...process.env, OPENCODE_MEMORY_HOME: config.memoryHome, OPENCODE_MEMORY_OLLAMA_URL: config.ollamaUrl, OPENCODE_MEMORY_EMBEDDING_MODEL: config.embeddingModel },
    })
    return stdout.trim() || stderr.trim() || "Operation completed."
  } catch (error) {
    const e = error as Error & { stderr?: string; stdout?: string }
    throw new Error(e.stderr?.trim() || e.stdout?.trim() || e.message)
  }
}

function projectPath(context: { directory: string }) {
  return context.directory
}

export const search = tool({
  description: "Manually search this project's persistent memory when the user explicitly requests a memory search or when the automatic <persistent-memory> context does not contain a needed historical fact. Results are restricted to this project.",
  args: {
    query: tool.schema.string().describe("Specific concepts, task, or decision to find"),
    limit: tool.schema.number().optional().describe("Maximum results (default 5, maximum 10)"),
  },
  async execute(args, context) {
    const limit = Math.max(1, Math.min(10, Math.floor(args.limit ?? 5)))
    return run(["search", "--query", args.query, "--limit", String(limit), "--project", projectPath(context)])
  },
})

export const store = tool({
  description: "Manual memory operation. Use only when the user explicitly asks to save or correct a memory. Automatic durable-memory extraction runs after completed tasks through the local memory plugin, so do not call this automatically. Never store passwords, keys, tokens, cookies, private keys, credentials, test secrets, temporary output, or redundant conversation. The backend redacts detected secrets.",
  args: {
    content: tool.schema.string().describe("One concise durable fact or decision"),
    type: tool.schema.string().optional().describe("Memory type, such as decision, architecture, fix, workflow, or milestone"),
    scope: tool.schema.enum(["project", "global"]).optional().describe("Use global only for an explicit user-wide preference or fact"),
  },
  async execute(args, context) {
    const metadata = JSON.stringify(args.scope === "global"
      ? { scope: "global" }
      : { project: projectPath(context) })
    return run(["store", "--type", args.type ?? "project_note", "--content", args.content, "--metadata", metadata])
  },
})

export const update = tool({
  description: "Update an existing persistent project memory by ID.",
  args: {
    memory_id: tool.schema.number().describe("Memory ID to update"),
    content: tool.schema.string().optional().describe("Replacement memory content"),
    metadata: tool.schema.string().optional().describe("Replacement JSON metadata"),
  },
  async execute(args, context) {
    const argv = ["update", "--id", String(args.memory_id)]
    if (args.content !== undefined) argv.push("--content", args.content)
    if (args.metadata !== undefined) {
      const metadata = JSON.parse(args.metadata) as Record<string, unknown>
      metadata.project = projectPath(context)
      argv.push("--metadata", JSON.stringify(metadata))
    }
    argv.push("--project", projectPath(context))
    return run(argv)
  },
})

export const forget = tool({
  description: "Delete a persistent memory by ID when asked to forget it.",
  args: { memory_id: tool.schema.number().describe("Memory ID to delete") },
  async execute(args, context) {
    return run(["delete", "--id", String(args.memory_id), "--project", projectPath(context)])
  },
})

export const list = tool({
  description: "List recent persistent memories tagged for the current project only.",
  args: { limit: tool.schema.number().optional().describe("Maximum results (default 20, maximum 100)") },
  async execute(args, context) {
    const limit = Math.max(1, Math.min(100, Math.floor(args.limit ?? 20)))
    return run(["list", "--limit", String(limit), "--project", projectPath(context)])
  },
})

export const stats = tool({
  description: "Show aggregate persistent-memory database statistics.",
  args: {},
  async execute() {
    return run(["stats"])
  },
})
