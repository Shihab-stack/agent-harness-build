# Agent Harness Build

A small, local-first command-line assistant built with Python and Ollama. It
can chat, use workspace and project-inspection tools, save local memory, and
optionally connect to MCP servers for time, web fetching, calendar, GitHub,
graph memory, and isolated Python execution. Optional cloud model backends are
available, but local Ollama is the default.

## Project layout

```text
README.md
pyproject.toml
uv.lock
config/
  mcp_servers.example.json       Example time/fetch/memory/docs/browser/sandbox MCP configuration
skills/
  systematic-debugging.md        Evidence-first debugging workflow
  code-reviewer.md               Severity-ranked code review workflow
  env-doctor.md                  Runtime and environment diagnostics
  git-commit-writer.md           Conventional Commit message workflow
  mcp-builder.md                 Safe MCP server design and scaffolding
  deep-reasoning.md              Optional structured reasoning workflow
src/agent_herness_build/
  __init__.py                    Package entry point
  cli.py                         Interactive commands and startup
  agent.py                       Model/tool conversation loop
  models.py                      Local and optional cloud model settings
  mcp.py                         MCP configuration, connections, and routing
  skills.py                      On-demand behavioral skill loading
  paths.py                       Shared project/config/workspace paths
  sandbox_mcp.py                 Docker-isolated Python execution MCP server
  tools/
    files.py                     Workspace and allowlisted project file tools
    memory.py                    Persistent local memory
sandbox/
  Dockerfile                     Python sandbox image definition
examples/
  chat.py                        Minimal direct Ollama chat example
  v1.py ... v4.py                 Step-by-step tool-agent examples
workspace/                        Your files and saved memory
tests/                             Offline unit tests
```

Python application code is under `src/`; sample configuration is under
`config/`; and assistant-managed data is in the project-root `workspace/`.
The assistant's file tools are restricted to that workspace. The memory file
is `workspace/memory.md`.

## Requirements and setup

- Python 3.13 or newer
- [Git](https://git-scm.com/downloads)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Ollama](https://ollama.com/download)

Install Git, Python, uv, and Ollama for your operating system using their
official download pages. To install uv from a terminal:

**macOS / Linux (Terminal):**

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After installing tools, open a new terminal and check that they are available:

```sh
python --version
git --version
uv --version
ollama --version
```

Clone this repository from GitHub (replace `YOUR-USERNAME` with the account
that owns the repository), then enter the project folder:

```sh
git clone https://github.com/YOUR-USERNAME/agent-harness-build.git
cd agent-harness-build
```

Download the default local model and install the project dependencies:

```sh
ollama pull qwen3.5:4b
uv sync --no-editable
```

Ollama must be installed and running locally before using a local model. Check
the models installed on your computer with:

```sh
ollama list
```

`qwen3.5:4b` is the default. The smaller `local-small` option defaults to
`qwen2.5-coder:3b`. Neither local option requires a model-provider API key.
The optional `gpt` and `claude` backends use paid provider APIs; set
`OPENAI_API_KEY` or `ANTHROPIC_API_KEY` before selecting those backends.

The `--no-editable` option works across operating systems and avoids editable
install path issues some Python environments can have.

## Run the main assistant

Run from the repository root so the assistant finds `config/` and `workspace/`:

```sh
uv run --no-editable agent-harness-build
```

You can select a backend at startup:

```sh
uv run --no-editable agent-harness-build --model local-small
```

Run without starting MCP servers (local file and memory tools still work):

```sh
uv run --no-editable agent-harness-build --no-mcp
```

Before starting, the CLI checks that Ollama is reachable and that the selected
local model is installed. If the model is missing, install it using the
suggested `ollama pull <model>` command or select one already installed with
`OLLAMA_MODEL` or `OLLAMA_SMALL_MODEL`. Model responses stream as they arrive.

At the `you:` prompt, type a normal request, for example:

- `List the files in my workspace.`
- `Create a file named ideas.txt containing three project ideas.`
- `What time is it in Dhaka?`
- `Fetch https://example.com and summarize it.`
- `Remember that I prefer concise answers.`

Commands:

| Command | Purpose |
|---|---|
| `/models` | Show configured model backends and the active one |
| `/model local` | Switch to the default local Ollama model |
| `/model local-small` | Switch to the smaller local Ollama model |
| `/model gpt` | Select OpenAI (requires an API key and may incur charges) |
| `/model claude` | Select Anthropic (requires an API key and may incur charges) |
| `/tools` | List tools available in this run |
| `/memory` | Display saved memory |
| `/skills` | List available behavioral skills and the active skill |
| `/skill <name>` | Activate a skill for subsequent turns |
| `/skill off` | Deactivate the current skill |
| `/save <name>` | Save the current conversation under `workspace/conversations/` |
| `/resume <name>` | Resume a saved conversation |
| `/help` | Show available commands |
| `/quit` or `/exit` | Exit the assistant |

Conversation names may contain letters, numbers, hyphens, and underscores.
Project inspection is read-only and limited to `README.md`, `pyproject.toml`,
`src/`, `tests/`, and `config/mcp_servers.example.json`. Local configuration,
credentials, environment files, Git metadata, and workspace data are excluded
from project inspection. Workspace listing and reading remain scoped to
`workspace/`; `write_file` can create or replace files only under
`workspace/generated/` and asks before overwriting an existing file. Review
generated files before using them as project changes.
Use `list_project_files` and `read_project_file` to inspect the approved
project files.

## Behavioral skills

Skills are Markdown workflows under the project-root `skills/` directory.
They are instructions for the current model, not model training or additional
tools. List and activate them in the interactive CLI:

```text
/skills
/skill systematic-debugging
The app fails to load its settings. Help me reproduce and diagnose it.
/skill off
/skill mcp-builder
Help me design a read-only MCP server for our internal status API.
```

Available skills are `systematic-debugging`, `code-reviewer`, `env-doctor`,
`git-commit-writer`, `mcp-builder`, and `deep-reasoning`. The selected skill is
included in the system prompt for subsequent turns in the current CLI session;
it is not persisted across restarts. Use `/skill off` to return to the base
behavior. Skills cannot grant capabilities the configured tools do not provide;
if required tools are unavailable, the assistant should say what it could not
inspect or verify.

## MCP servers

The assistant reads `config/mcp_servers.json` when it exists; otherwise it
uses `config/mcp_servers.example.json`. The example starts time and fetch via
`uvx`, memory, GitHub, Context7, and Playwright via `npx`, and the Python
sandbox via `uv`. Context7 provides library documentation tools; the headless
Playwright MCP provides browser automation for navigation and web-app testing.
The Sequential Thinking MCP exposes a tool for structuring complex problem
solving; it does not guarantee correct answers or replace independent
verification. First startup may download MCP packages and needs internet
access. Playwright may also need its Chromium browser installed on the host
(for example, `npx playwright install chromium`). Set
`GITHUB_PERSONAL_ACCESS_TOKEN` in the environment before launching the
assistant to authenticate the GitHub server; do not put personal access
tokens in the config file. You can customize server commands by copying the
example:

```sh
cp config/mcp_servers.example.json config/mcp_servers.json
```

The local config is git-ignored so personal settings stay out of commits.
Use `--no-mcp` to skip MCP startup if you only need local tools.

Example requests when the configured servers are connected:

- `Use Context7 to find the current documentation for the installed FastAPI version.`
- `Use the headless browser to open my local app, check the sign-in page, and report what you observe.`

Tool availability depends on successful MCP startup. Use `/tools` to see the
tools registered in the current session; do not assume a server connected
when it failed to start.

To try Sequential Thinking, restart the harness after configuring it, run
`/tools` and look for tools with the `mcp_sequential-thinking_` prefix, then
activate the skill and ask a multi-step question:

```text
/skill deep-reasoning
Solve this multi-step logic puzzle. Use the Sequential Thinking tool if it is
available, verify the result, and give me a concise explanation without
revealing private chain-of-thought.
```

### Isolated Python execution

The `sandbox` MCP server exposes `run_script`. It starts a fresh
`agent-harness-python:3.13` container for each call. The existing
`mcp-run-python` entry is intentionally not configured: it would execute code
outside this Docker boundary.

Prerequisites: Docker Desktop or Docker Engine must be installed and running.
Build the image once from the repository root:

```sh
docker build --pull -t agent-harness-python:3.13 sandbox
uv sync --no-editable --reinstall-package agent-harness-build
```

`--pull` is needed only when building/updating the image. Runtime uses
`--pull=never`, so the MCP server does not fetch an image when handling code.
The configured stdio server is started by:

```sh
uv run --no-sync python -m agent_herness_build.sandbox_mcp
```

Each script runs without network access (`--network=none`), with a read-only
root filesystem, no host mounts, dropped Linux capabilities, no-new-privileges,
an unprivileged UID, and a small writable `/tmp` tmpfs. Docker limits each
container to 0.5 CPU, 256 MiB memory, no additional swap (`--memory-swap=256m`),
64 processes, 64 KiB of input, 64 KiB of captured output, and 30 seconds of
execution. The container is removed after the call. No project or workspace
files are mounted into it.

The agent invokes `mcp_sandbox_run_script` with a `python_code` string. For
example:

```json
{
  "python_code": "print(sum(range(10)))"
}
```

The harness sends this as the MCP `run_script` argument; the MCP server passes
the code to `python -I -` on the container's standard input. It is not
interpolated into a shell command.

The server returns the exit status and captured stdout/stderr. The fixtures in
`tests/sandbox_scripts/` check normal computation and temporary-file access,
blocked outbound networking, and behavior when a 1 GiB allocation exceeds the
memory limit. The memory test may be terminated by the container OOM killer
(reported as exit code 137) rather than catching `MemoryError`.

Run the fixtures by passing their contents to `run_script`; these files are
test inputs and are not mounted into the container. The normal offline unit
tests mock Docker and verify the security flags. A live sandbox test requires
Docker and the prebuilt image. Docker container isolation reduces risk but is
not a hardened boundary against kernel or Docker-daemon vulnerabilities; do
not use it to run code from untrusted parties on a security-critical host.

## Examples

The `examples/` scripts show the agent growing in stages. Run any example from
the project root, for example:

```sh
uv run --no-editable python examples/v1.py
uv run --no-editable python examples/v2.py
uv run --no-editable python examples/v3.py
uv run --no-editable python examples/v4.py
```

These are educational, separate implementations. Use
`uv run --no-editable agent-harness-build` for the maintained assistant and
shared configuration.

## Tests

Run the offline unit tests with Python's built-in test runner:

```sh
uv run --no-editable python -m unittest discover -s tests -v
```

Tests do not call Ollama or launch MCP servers. They cover the local tools,
conversation save/restore, CLI commands, model checks, streaming/tool dispatch,
and file-overwrite confirmation.

## Publish this project to GitHub

These steps publish your local project folder as a new GitHub repository.
You need a GitHub account and Git installed. Do not upload API keys, `.env`
files, private MCP configuration, or personal assistant data. Files under
`workspace/` are ignored by Git because they can contain private notes and
memory.

1. On [GitHub](https://github.com/new), create a new repository named
   `agent-harness-build`. Choose public or private. For the simplest first
   upload, leave "Add a README", `.gitignore`, and license unchecked; this
   project already has a README and `.gitignore`.
2. In a terminal, go to the project folder. If you are following these
   instructions after cloning, you are already in it:

   ```sh
   cd agent-harness-build
   ```

3. Review what Git will upload. Personal workspace files should not appear:

   ```sh
   git status --short
   git diff --cached --check
   git diff --cached --stat
   ```

   If you see private files, stop and remove them from Git's staging area
   before continuing. `git rm --cached PATH` removes a file from the upload
   without deleting your local copy.
4. Stage the project files, then review the staged list and its changes:

   ```sh
   git add .
   git status --short
   git diff --cached --check
   git diff --cached
   ```

   Read through the diff before uploading. In particular, make sure it
   contains no passwords, API keys, personal notes, or other private data.
   Also review the author contact information in `pyproject.toml` and use
   only an email address you are comfortable making public.
5. Save the first version in Git:

   ```sh
   git branch -M main
   git commit -m "Initial project upload"
   ```

   If Git asks who you are, set the name and email you want associated with
   your commits:

   ```sh
   git config --global user.name "Your Name"
   git config --global user.email "you@example.com"
   ```

   Then run the `git commit` command again.
6. Connect your local project to the new GitHub repository. Replace
   `YOUR-USERNAME` with your GitHub username:

   ```sh
   git remote add origin https://github.com/YOUR-USERNAME/agent-herness-build.git
   git push -u origin main
   ```

   Follow GitHub's sign-in prompt if one appears. Do not put a password or
   access token directly into the command.
7. Refresh the repository page on GitHub. Your project files and README should
   now be visible.

For later updates, make changes and run the tests, then use:

```sh
git add .
git diff --cached
git commit -m "Describe your change"
git push
```

## Environment settings

| Variable | Purpose |
|---|---|
| `OLLAMA_MODEL` | Override the default local model |
| `OLLAMA_SMALL_MODEL` | Override the smaller local model |
| `OLLAMA_BASE_URL` | Change the Ollama OpenAI-compatible endpoint |
| `OPENAI_API_KEY` | Enable the optional OpenAI backend |
| `OPENAI_MODEL` | Override the OpenAI model name |
| `ANTHROPIC_API_KEY` | Enable the optional Anthropic backend |
| `ANTHROPIC_MODEL` | Override the Anthropic model name |
| `AGENT_PROJECT_ROOT` | Explicitly select the checkout/data root |
| `AGENT_WORKSPACE` | Override the assistant's user-data folder |
| `AGENT_CONFIG_DIR` | Override the MCP configuration folder |
