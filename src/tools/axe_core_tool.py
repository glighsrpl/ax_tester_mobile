"""Axe-Core accessibility testing tool integration

This tool injects axe-core in the current shared browser page
(`BROWSER_SESSION`) and runs automated accessibility checks.

@test: .venv/bin/python src/tools/axe_core_tool.py shop.reply.com
"""

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from schemas import Issue, ScoreInfo
from tools.base import Tool, ToolExecutionError, ToolResult, ToolStatus
from utils.browser_session import BROWSER_SESSION
from utils.wcag_helper import get_rule_name_from_axe_tags, get_wcag_level

logger = logging.getLogger(__name__)


class AxeCoreTool(Tool):
    """Axe-Core static accessibility analyzer

    Executes axe-core rules on the current shared browser page and returns WCAG violations.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.axe_source = self._load_axe_source()

    def _load_axe_source(self) -> str:
        """Load axe-core JavaScript source from node_modules"""
        try:
            # get path to axe-core
            js_dir = Path(__file__).parent.parent.parent
            axe_path = js_dir / "node_modules" / "axe-core" / "axe.min.js"

            if not axe_path.exists():
                raise FileNotFoundError(f"Axe-core not found at {axe_path}. Run: npm i")

            with open(axe_path, encoding="utf-8") as f:
                return f.read()

        except Exception as e:
            logger.error(f"Failed to load axe-core source: {e}")
            raise ToolExecutionError(f"Cannot load axe-core: {e!s}") from e

    async def execute(self) -> ToolResult:
        """Async axe-core execution on the current shared browser page.

        Returns:
            ToolResult with axe-core violations and mapped issues

        """
        logger.info("Running axe-core analysis on current page")

        try:
            axe_results = await self._run_axe_core()
            violations = axe_results.get("violations", [])
            incomplete = axe_results.get("incomplete", [])
            inapplicable = axe_results.get("inapplicable", [])
            passes = axe_results.get("passes", [])
            page_url = axe_results.get("url", "")

            issue_list = self._map_violations_to_issues(violations)
            passed_list = self._map_violations_to_issues(passes)

            score_passed: ScoreInfo = self._build_score_info(passed_list)
            score_failed: ScoreInfo = self._build_score_info(issue_list)
            score_total: ScoreInfo = ScoreInfo(
                level_A=score_failed.level_A + score_passed.level_A,
                level_AA=score_failed.level_AA + score_passed.level_AA,
                level_AAA=score_failed.level_AAA + score_passed.level_AAA,
            )
            logger.info(
                f"Axe-core analysis complete for {page_url}: {len(violations)} violations, "
                f"{len(incomplete)} incomplete, {len(passes)} passes, {len(issue_list)} mapped issues"
            )

            return ToolResult(
                tool_name="axe-core",
                status=ToolStatus.SUCCESS,
                data={
                    "violations": violations,
                    "incomplete": incomplete,
                    "inapplicable": inapplicable,
                    "passes": passes,
                    "issue_list": issue_list,
                    "url": page_url,
                    "timestamp": axe_results.get("timestamp"),
                },
                score_passed=score_passed,
                score_total=score_total,
            )

        except ToolExecutionError:
            raise

        except Exception as e:
            logger.exception("Unexpected error in axe-core execution on current page")
            page_url = await BROWSER_SESSION.get_current_url() if BROWSER_SESSION.is_initialized() else ""
            return ToolResult(
                tool_name="axe-core",
                status=ToolStatus.FAILURE,
                data={},
                score_passed=ScoreInfo(),
                score_total=ScoreInfo(),
                error=str(e),
                metadata={"url": page_url},
            )

    async def _run_axe_core(self) -> dict[str, Any]:
        """Execute axe-core in the already-open shared browser page.

        Returns:
            Axe-core results dictionary

        Raises:
            ToolExecutionError: If execution fails

        """
        try:
            if not BROWSER_SESSION.is_initialized():
                raise ToolExecutionError(
                    "Browser session not initialized. Initialize and navigate with root tools before running axe-core."
                )

            has_axe = await BROWSER_SESSION.evaluate("typeof window.axe !== 'undefined'")
            if not has_axe:
                await BROWSER_SESSION.add_script(content=self.axe_source)

            axe_results = await BROWSER_SESSION.evaluate("() => axe.run(document)")
            if not isinstance(axe_results, dict):
                raise ToolExecutionError("axe-core returned a non-object payload")
            axe_results["url"] = await BROWSER_SESSION.get_current_url()

            return axe_results

        except ToolExecutionError:
            raise

        except Exception as e:
            current_url = (
                await BROWSER_SESSION.get_current_url() if BROWSER_SESSION.is_initialized() else "<unknown>"
            )
            logger.exception(f"Playwright execution error for {current_url}")
            raise ToolExecutionError(f"Playwright error: {e!s}") from e

    def _map_violations_to_issues(self, violations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for v in violations:
            description = v.get("description") or v.get("help") or ""
            impact = v.get("impact") or "moderate"
            wcag = get_rule_name_from_axe_tags(v.get("tags", []))
            for idx, node in enumerate(v.get("nodes", [])):
                snippet = node.get("html") or ""
                target = node.get("target") or []
                node_id = "-".join([str(t) for t in target]) if target else str(idx)
                issue = Issue(
                    id=f"axe-{wcag}-{node_id}",
                    wcag_rule=wcag,
                    description=description,
                    severity=self._map_impact(impact),
                    source="axe-core",
                    confidence="high",
                    html_snippet=snippet.replace("\\n", " "),
                    fix=v.get("help") or v.get("helpUrl") or "",
                    image_url_or_path=None,
                    why_this_matters="",
                    potential_exposures=[],
                ).model_dump()
                issues.append(issue)
        return issues

    def _map_impact(self, impact: str) -> str:
        impact = (impact or "moderate").lower()
        if impact in {"critical", "serious", "moderate", "minor"}:
            return impact
        return "moderate"

    def _build_score_info(self, items: list[dict[str, Any]]) -> ScoreInfo:
        level_counts = Counter(
            get_wcag_level(item.get("wcag_rule")) for item in items if item.get("wcag_rule") != "best-practice"
        )
        return ScoreInfo(
            level_A=level_counts["A"],
            level_AA=level_counts["AA"],
            level_AAA=level_counts["AAA"],
        )


# simple test runner
if __name__ == "__main__":
    import asyncio
    import sys

    # default_url = "https://apple.com"
    default_url = "https://shop.reply.com"
    test_url = default_url if len(sys.argv) < 2 else sys.argv[1]

    print(f"Testing URL: {test_url}")

    async def _run() -> None:
        url = test_url if test_url.startswith(("http://", "https://")) else f"https://{test_url}"
        await BROWSER_SESSION.create_session()
        await BROWSER_SESSION.goto(url)
        try:
            result = (await AxeCoreTool().execute()).to_dict()
            print(json.dumps(result, indent=2))
        finally:
            await BROWSER_SESSION.close_session()

    asyncio.run(_run())
