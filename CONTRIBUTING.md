# Contributing made easy
Here is a short guideline to develop and debug.

## Development
Follow the installation guide on [README.md](README.md) to set up the environment.

Follow the repository structure and add your code in the right place. If you are adding a new feature, please also add tests for it.

Follow the code style and make sure to run the formatter command before committing, otherwise the pipeline will fail and ask you to fix the code style. You can run:
```bash
make format
```
or, from the repository root:
```bash
ruff format && ruff check --fix
```

## Debug
Before committing, make sure to test everything, according to the following debug process.

The `make full_local`, `make mcp_executor`, and `make staging_axtester` shortcuts referenced below are Taffy
repository shortcuts.

1. Full Local Debug
    Analyze new features or fix bugs by running the entire system locally. This includes:
    - local Taffy, default at `127.0.0.1:5000`
    - local ax_tester, default at `127.0.0.1:8000`
    - local browser backend, accessed through `browser_executor_client_local.py`

    Use the following env variables in the proper directories:
    - taffy/TAFFY_AXTESTER_BACKEND=local
    - ax_tester/AXTESTER_EXECUTOR=local

    bash code:
    ```bash
    cd <taffy_dir> && \
    AXTESTER_EXECUTOR=local <axtester_dir>/.venv/bin/python <axtester_dir>/mcp_server.py & \
    TAFFY_AXTESTER_BACKEND=local <taffy_dir>/.venv/bin/python -m chainlit run chainlit_ui.py -w --port 5000
    ```

    or in `<taffy_dir>`, you can use the Taffy makefile shortcut:
    ```bash
    make full_local
    ```

2. MCP Browser Executor Debug
    Debug the browser executor integration. This includes:
    - local Taffy, default at `127.0.0.1:5000`
    - local ax_tester, default at `127.0.0.1:8000`
    - MCP browser executor, accessed through `browser_executor_client.py`

    Use the following env variables in the proper directories:
    - taffy/TAFFY_AXTESTER_BACKEND=local
    - ax_tester/AXTESTER_EXECUTOR=mcp

    > you must run executor_main.exe on your pc to expose your capability

    bash code:
    ```bash
    cd <taffy_dir> && \
    AXTESTER_EXECUTOR=mcp <axtester_dir>/.venv/bin/python <axtester_dir>/mcp_server.py & \
    TAFFY_AXTESTER_BACKEND=local <taffy_dir>/.venv/bin/python -m chainlit run chainlit_ui.py -w --port 5000
    ```

    or in `<taffy_dir>`, you can use the Taffy makefile shortcut:
    ```bash
    make mcp_executor
    ```

3. Staging AxTester Debug
    After pushing to the dev branch, verify the updated ax_tester behaves as expected also in the staging environment. This includes:
    - local Taffy, default at `127.0.0.1:5000`
    - staging ax_tester, at https://www.accessibility.staging.cncqitreply.com/mcp


    Use the following env variables in the proper directories:
    - taffy/TAFFY_AXTESTER_BACKEND=mcp

    > you must run executor_main.exe on your pc to expose your capability

    bash code:
    ```bash
    cd <taffy_dir> && \
    TAFFY_AXTESTER_BACKEND=mcp <taffy_dir>/.venv/bin/python -m chainlit run chainlit_ui.py -w --port 5000
    ```

    or in `<taffy_dir>`, you can use the Taffy makefile shortcut:
    ```bash
    make staging_axtester
    ```

4. Client Taffy Debug
    Debug the Taffy client integration directly at https://www.staging.cncqitreply.com/chatbot-taffy > Taffy. Just ask to analyze the accessibility of a url on your executor.

    > you must run executor_main.exe on your pc to expose your capability


Some tips:
- if the executor doesn't open a session at the requested capability, it might be because it is filled up, so restart `testerservice` at https://www.tafmanagement.cncqitreply.com/services > staging
- after every push in dev, you should also wait for the pipeline to finish and restart the accessibility.staging.cncqitreply.com server in taffy management > staging, to make sure the staging environment is up to date for later staging ax_tester debug
- look CLOSELY at logs (in your terminal or in https://www.tafmanagement.cncqitreply.com/services > staging > ax_tester > logs) to understand what is going wrong; also make sure to log (using logger) _meaningful_ messages at _meaningful_ steps in the code



## Contributors
made with ❤️ by [whiitex](https://github.com/whiitex) 🦍
