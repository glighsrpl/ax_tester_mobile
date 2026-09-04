# Accessibility Tester
AI agent capable of testing the accessibility of mobile app.

### Runtime lifecycle

### Crawl Strategy

### MCP Entry Point

### Results Folder Layout

Reports are saved under `ax_tester/results/<crawl_folder_name>/`:
- one folder per crawl invocation (`<crawl_folder_name>`, timestamp-based)
- inside it, 
- in the crawl root: `results.json`, containing the list of all page-level `ax_report` objects found in the page folders
- in the crawl root: aggregate `ax_report.json`, `ax_report.xlsx`, and `ax_report.pptx` for MCP retrieval

### Tool contract

## Unified Report Schema

All final reports use the same `Report` schema:
- `tool_name`: name of the tool/aggregator that produced the report
- `issue_list`: list of normalized issues
- `total_issues`: total number of issues in `issue_list`
- `page`: analyzed app_package/app_activity
- `score_passed`: counters of passed checks by WCAG level (`level_A`, `level_AA`, `level_AAA`)
- `score_total`: counters of total analyzed checks by WCAG level (`level_A`, `level_AA`, `level_AAA`)
- `metadata`: list of `{key, value}` entries for tool-specific extra data`


## Static Analysis Agent


## Installation and Usage
Install environment and dependencies: `cd` in `ax_tester_mobile` directory, then:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
rm -rf src/ax_tester.egg-info/
npm i
```

Create a `.env` file as suggested in [.env.example](.env.example):

You can use any LLM model by providing the required API key in `.env` and changing the model name in
[src/common/model.py](src/common/model.py).

To run the client agent, using the same terminal with source `.venv`:
Set `app_package` and `app_activity` in [run_local.py](run_local.py)
```bash
make run_local
```

### MCP Server

`ax-tester-mobile` can also run as an MCP server that exposes high-level tools only:

- `get_test_capabilities()`
- `run_full_mobile_test(app_package, app_activity, capability_id=None = None, max_steps=100, max_activities=10, max_depth=0)`
- `get_report_file(report_id, file_type)`

`run_full_mobile_test` returns the compact aggregate JSON report immediately and includes a run-level `report_id`.
Use `get_report_file` with `file_type` set to `json`, `powerpoint`, or `excel` to retrieve saved artifacts
from `results/<report_id>/`. The `report_id` is the crawl folder name returned by `run_full_mobile_test`.
The tool returns a downloadable MCP resource link; file content is served by
the matching MCP resource URI.


Run the server from the repository root:

```bash
.venv/bin/python mcp_server.py --host 127.0.0.1 --port 8080
```
or
```bash
make mcpinspector
```

## Code style

This project uses **Ruff** for formatting and linting. The same checks are enforced by the CI workflow ([`python-format.yml`](.github/workflows/python-format.yml)), so your push/PR will fail if they don’t pass. Run the following commands before pushing from root directory:

```bash
ruff check --fix && ruff format
```
or
```bash
make format
```
