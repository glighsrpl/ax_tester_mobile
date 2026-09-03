.PHONY: format check mcpinspector dockerbuild dockerrun

# ruff formatting
format:
	ruff format . && ruff check --fix .
	
checkformat:
	ruff format --check && ruff check

# mcp inspector
mcpinspector:
	bash -c 'trap "kill 0" SIGINT; python mcp_server.py & sleep 2 && npx @modelcontextprotocol/inspector@latest'
