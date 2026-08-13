# Current Task

You are working on DOSBox-X-AI.

Project root:

<repository-root>

Read AGENTS.md first.

Do not modify DOSBox-X C++ source yet.

## Execute these checks

1. Check Python:

.\.venv\Scripts\python.exe --version

2. Check MCP:

.\.venv\Scripts\mcp.exe version

3. Check Node:

node --version

4. Check npm:

npm --version

5. Check npx:

npx --version

## If Node/npm/npx is missing

STOP.

Do not install system software automatically.

Report exactly which command is missing.

## If all prerequisites pass

Create:

ai/server.py

Implement MCP 2.x server with:

- ping()
- get_project_status()

Then run:

.\.venv\Scripts\mcp.exe dev .\ai\server.py

Verify both tools using MCP Inspector.

Do not proceed to DOSBox-X source integration.

## Completion condition

Only report success after actually verifying:

- MCP Inspector starts
- ping() succeeds
- get_project_status() succeeds