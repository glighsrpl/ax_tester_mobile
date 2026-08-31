# Accessibility Tester
AI agent capable of testing the accessibility (also referred to as a11y or ax) of web pages.

## Browser Session (`BROWSER_SESSION`)

The project uses a shared singleton facade defined in [`src/utils/browser_session.py`](src/utils/browser_session.py).
The facade keeps browser operations behind one interface and can use either a local Playwright-backed Chrome
session or an external browser executor MCP server.

The backend is selected with `AXTESTER_EXECUTOR`:
- `local`: runs Chrome locally through Playwright via [`src/utils/browser_executor_client_local.py`](src/utils/browser_executor_client_local.py)
- `mcp`: delegates browser work to an external browser executor MCP server via [`src/utils/browser_executor_client.py`](src/utils/browser_executor_client.py)

When `AXTESTER_EXECUTOR=mcp`, the executor MCP URL is read from `BROWSER_EXECUTOR_URL`.

The local agent keeps one source of truth for the current browser session:
- one browser session per run
- one current page used by agents/tools
- centralized keyboard actions (`press_key`) and navigation (`goto`)
- serializable active-element snapshots through `get_active_element_info`

### Runtime lifecycle

1. The user sends a request to `RootAgent` (`adk web`) or through MCP.
2. `RootAgent` calls `run_crawl_test(url, max_depth, max_pages, same_host_only)` once.
3. `run_crawl_test` crawls pages with BFS and runs the full tester pipeline on each visited page.
4. Each page saves reports in its own folder; at the end of the crawl, run-level report artifacts are generated.

### Crawl Strategy

The root agent uses `run_crawl_test(url, max_depth, max_pages, same_host_only)` to test a site with BFS:
- links are explored level by level (queue-based crawl)
- crawling stops for a branch when depth reaches `0`
- by default only links on the same host are followed (`same_host_only=true`)
- if `max_depth` is not provided, default is `0` (only the current/root page)
- if `max_pages` is not provided, default is `10`


### MCP Entry Point

The MCP server exposes high-level tools:
- `run_full_test(url, depth=0, max_pages=10)`: runs the crawl/test flow and returns the aggregate JSON report immediately
- `get_report_file(report_id, file_type)`: returns a downloadable resource link for a saved run report
- `reset_session()`: resets the ADK/browser session

### Results Folder Layout

Reports are saved under `ax_tester/results/<crawl_folder_name>/`:
- one folder per crawl invocation (`<crawl_folder_name>`, timestamp-based)
- inside it, one timestamp-based folder per analyzed page, with a numeric suffix if needed
- inside each page folder: per-tool JSON reports + `ax_report.json` + Excel/PPT exports
- in the crawl root: `results.json`, containing the list of all page-level `ax_report` objects found in the page folders
- in the crawl root: aggregate `ax_report.json`, `ax_report.xlsx`, and `ax_report.pptx` for MCP retrieval

### Tool contract

- Tools must not access Playwright objects directly.
- Tools must use the `BROWSER_SESSION` facade for browser operations.
- Runtime tools must not navigate again to the same URL internally.
- Runtime tools should not require `url` input when they operate on the current page.
- Keyboard press timing logic is centralized in `BROWSER_SESSION.press_key`.
- Active element capture must use `BROWSER_SESSION.get_active_element_info`; the selected backend decides whether
  the snapshot comes from local Playwright/CDP or from the executor MCP primitive.

## Unified Report Schema

All final reports use the same `Report` schema:
- `tool_name`: name of the tool/aggregator that produced the report
- `issue_list`: list of normalized issues
- `total_issues`: total number of issues in `issue_list`
- `page`: analyzed URL
- `score_passed`: counters of passed checks by WCAG level (`level_A`, `level_AA`, `level_AAA`)
- `score_total`: counters of total analyzed checks by WCAG level (`level_A`, `level_AA`, `level_AAA`)
- `metadata`: list of `{key, value}` entries for tool-specific extra data

Each issue follows a single `Issue` schema and includes `image_url_or_path` (nullable):
- use the original image URL when the image comes from the analyzed page
- use a local path/folder when the issue refers to saved local screenshots
- use `null` when not available

## Static Analysis Agent

The **Static Analysis Agent** runs an accessibility assessment from the available HTML/DOM (no user interaction required) and produces a single, validated JSON report by combining:
- automated findings (**axe-core**)
- iterative, agent-guided review (**Loop Finder**)

### High-level pipeline

1. **AxeCore Agent**
   - Runs **axe-core** against the page/DOM.
   - Output: `axe_report` (violations + affected nodes/instances)

2. **Loop Finder Agent**
   - Iteratively inspects the HTML and partial results to increase coverage.
   - Output: `loop_report` (additional issues, risk-based checks, agent-driven findings)

3. **Merge Agent**
   - Merges **`axe_report` + `loop_report`** into one unified report.
   - De-duplicates by *WCAG rule + same node*.
   - Assigns `source` (`axe-core|llm|both`) and `confidence`.
   - Output: `static_report` (`Report`)

4. **JSON Formatter**
   - Normalizes and validates the final JSON:
     - safe escaping for HTML snippets

```text
                  ┌──────────────────────────┐
                  │   Static Analysis        │
                  │   Component              │
                  └────────────┬─────────────┘
                               │
                ┌──────────────┴───────────────┐
                │                              │ [set_wcag_level]
                |                              | [fetch_dom_html]
                v                              v
┌──────────────────────────┐   ┌───────────────────────────┐
│  AxeCore Agent           │   │  Loop Finder Agent        │
│  (axe-core scan)         │   │  (iterative checks)       │
└──────────────┬───────────┘   └───────────────┬───────────┘
               │ axe_report                    │ loop_report
               └───────────────┬───────────────┘
                               v
                  ┌──────────────────────────┐
                  │  Merge Agent             │
                  │  (dedupe + unify)        │
                  └────────────┬─────────────┘
                               │ static_report
                               │
                               v
                       Final Valid JSON         
                       issues[] + summary       
```
## Semantic Analysis Agent
The **Semantic Analysis Agent** checks whether images’ `alt` text is *semantically consistent* with what the image depicts. It runs a *sequential pipeline* (tools only) and outputs a single structured report.

### High-level pipeline

1. **Image + Alt Extractor**
   - Parses the available HTML/DOM.
   - Collects all images and their related `alt` text (if present).

2. **Caption Generator**
   - Generates a caption for each extracted image using LLM calls.

3. **Alt–Caption Similarity Verifier**
   - Verifies that each image caption and its `alt` text are similar enough.
   - Output: `image_analyzer_report` (`Report`)


```text
               ┌──────────────────────────────┐
               │   Semantic Analysis          │
               │   Component                  │
               └──────────────┬───────────────┘
                              │
                              │ [fetch_dom_html]
                              v
                ┌─────────────────────────────┐
                │  Image Extractor Tool       │
                │  (images + alt collection)  │
                └──────────────┬──────────────┘
                               │ images_inventory[]
                               v
                ┌─────────────────────────────┐
                │  Caption Generator Tool     │
                │  (caption per image)        │
                └──────────────┬──────────────┘
                               │ captions[]
                               v
                ┌─────────────────────────────┐
                │  Similarity Verifier Tool   │
                │  (alt vs caption match)     │
                └──────────────┬──────────────┘
                               │ semantic_report
                               v
                      Final Semantic JSON
                      issues[] + summary
```

## Navigator Agent
The **Navigator Agent** performs runtime keyboard navigation through the browser executor MCP server and emits a stream of `NavigatorState` snapshots. It follows a producer/consumer model:
- **Producer (Navigator)**: walks focusable elements (Tab/Space), requests serializable active-element snapshots from the executor, and captures screenshots and AX info through MCP primitives.
- **Consumers**: analyze each state independently and emit WCAG issues. Each consumer specializes in one WCAG rule (or a small set of closely related ones).

The default consumer set is centralized in:
- [`build_default_navigator_consumers()`](src/tools/consumers/__init__.py)

### High-level pipeline

0. **Runtime Navigator Tool** 
   - Navigates the remote page using keyboard MCP primitives.
   - Emits `NavigatorState` (prev/current focus context).

1. **Focus Visible Consumer** (WCAG 2.4.7, Level AA)
   - Consumes each state and collects element screenshots.
   - Uses LLM analysis to detect missing focus indicators.
   - Output: `focus_visible_report` (`Report`)

2. **Link Purpose Consumer** (WCAG 2.4.4 + 2.4.9)
   - Collects focused links (`role=link`) from AX info.
   - Sends accessible name/description + href + HTML snippet to LLM.
   - Output: `link_purpose_report` (`Report`)

3. **On Focus Consumer** (WCAG 3.2.1, Level A)
   - Detects unexpected context changes caused by focus transitions.
   - Flags events such as:
     - new tab/window opened only by focus
     - URL/title change triggered by focus alone
     - wrong focus restore behavior after `Space` / `Escape` on expandable widgets
   - Output: `on_focus_report` (`Report`)

4. **No Keyboard Trap Consumer** (WCAG 2.1.2, Level A)
   - Triggered on `Escape` transitions after expandable/modal interactions.
   - Uses root/before/after screenshots to verify that `Escape` closes the active modal.
   - Flags potential keyboard traps when modal remains open.
   - Output: `no_keyboard_trap_report` (`Report`)

### Implemented Consumers

| Consumer | Rule(s) | Strategy | Report key |
|---|---|---|---|
| `FocusVisibleConsumer` | `2.4.7` | LLM vision on focused element screenshots | `focus_visible_report` |
| `LinkPurposeConsumer` | `2.4.4`, `2.4.9` | LLM text analysis on link AX name/description + href + snippet | `link_purpose_report` |
| `OnFocusConsumer` | `3.2.1` | Deterministic transition checks on focus path/url/title/page count | `on_focus_report` |
| `NoKeyboardTrapConsumer` | `2.1.2` | LLM vision check before/after `Escape` for modal close behavior | `no_keyboard_trap_report` |

```text
               ┌──────────────────────────────┐
               │   Runtime Navigator          │
               │   Component                  │
               └───────────────┬──────────────┘
                               │
                               │ NavigatorState stream
                               v
              ┌─────────────────────────────┐
              | ┌─────────────────────────────┐
              └─│          Consumer           │
                └──────────────┬──────────────┘
                               │ <name>_report
                               │
                               v
                    Runtime Consumer Reports
                    (one Report per consumer)
```

## Installation and Usage
Install environment and dependencies: `cd` in `ax_tester` directory, then:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
rm -rf src/ax_tester.egg-info/
npm i
playwright install --with-deps chrome
```

Create a `.env` file as suggested in [.env.example](.env.example):

```env
OPENAI_API_KEY=sk-...
AXTESTER_EXECUTOR=local
BROWSER_EXECUTOR_URL=
CAPABILITY_POLICY=any
CAPABILITY_ID=
CAPABILITY_NAME=
```

Use `AXTESTER_EXECUTOR=local` for the default local Chrome/Playwright backend.

Use `AXTESTER_EXECUTOR=mcp` when browser work should be delegated to an external browser executor MCP endpoint.
In that mode, set `BROWSER_EXECUTOR_URL` to the executor URL, for example `http://127.0.0.1:8000/mcp`.
`CAPABILITY_POLICY=any` uses the shared `browser-chrome` capability; `CAPABILITY_POLICY=personal` requires
`CAPABILITY_ID` and `CAPABILITY_NAME`.

You can use any LLM model by providing the required API key in `.env` and changing the model name in
[src/common/model.py](src/common/model.py).

To run the client agent, using the same terminal with source `.venv`:
```bash
cd ..
adk web
```
> [!NOTE]
> `adk web` must be run from the parent directory of `ax_tester`.

### MCP Server

`ax-tester` can also run as an MCP server that exposes high-level tools only:

- `run_full_test(url, depth=0, max_pages=10)`
- `get_report_file(report_id, file_type)`
- `reset_session()`

`run_full_test` returns the compact aggregate JSON report immediately and includes a run-level `report_id`.
Use `get_report_file` with `file_type` set to `json`, `powerpoint`, or `excel` to retrieve saved artifacts
from `results/<report_id>/`. The `report_id` is the crawl folder name returned by `run_full_test`.
The tool returns a downloadable MCP resource link; file content is served by
the matching MCP resource URI.

The high-level MCP server does not expose raw browser primitives. Browser primitives stay behind the internal
`BROWSER_SESSION` facade and use the backend selected by `AXTESTER_EXECUTOR`.

Run the server from the repository root:

```bash
.venv/bin/python mcp_server.py --host 127.0.0.1 --port 8080
```

When `AXTESTER_EXECUTOR=mcp`, use a different port from the browser executor. For example, keep the browser
executor at `http://127.0.0.1:8000/mcp` and expose `ax-tester` at `http://127.0.0.1:8080/mcp`.

`reset_session()` closes the current browser session through `BROWSER_SESSION.close_session()` and opens a fresh
ADK session id. Calls are serialized inside `RootAgentBridge` so two MCP requests do not share and mutate the
same browser session concurrently.


## Code style

This project uses **Ruff** for formatting and linting. The same checks are enforced by the CI workflow ([`python-format.yml`](.github/workflows/python-format.yml)), so your push/PR will fail if they don’t pass. Run the following commands before pushing from root directory:

```bash
ruff check --fix && ruff format
```
or
```bash
make format
```

## Contributors
made with ❤️ by [whiitex](https://github.com/whiitex) ♿
