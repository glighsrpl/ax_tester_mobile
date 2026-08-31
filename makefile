.PHONY: format check mcpinspector dockerbuild dockerrun

# ruff formatting
format:
	ruff format . && ruff check --fix .
	
checkformat:
	ruff format --check && ruff check

# mcp inspector
mcpinspector:
	bash -c 'trap "kill 0" SIGINT; python mcp_server.py & sleep 2 && npx @modelcontextprotocol/inspector'

# docker
dockerbuild:
	docker build -t ax-tester:latest .

dockerrun:  # requires dockerbuild:
	docker run --rm -it -p 8080:8080 -v "$$(pwd):/app" -w /app ax-tester:latest

