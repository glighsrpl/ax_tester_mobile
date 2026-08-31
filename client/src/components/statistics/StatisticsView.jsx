import AccessibilityScoreTrendChart from "./AccessibilityScoreTrendChart";
import IssuesTrendChart from "./IssuesTrendChart";
import RuleRunBarChart from "./RuleRunBarChart";
import WcagLevelTrendChart from "./WcagLevelTrendChart";
import WcagPrincipleTrendChart from "./WcagPrincipleTrendChart";

const SCORE_KEYS = ["level_A", "level_AA", "level_AAA"];
const SCORE_WEIGHTS = {
  level_A: 3,
  level_AA: 2,
  level_AAA: 1,
};

function toNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function issueListFromReports(reports) {
  if (!Array.isArray(reports)) {
    return [];
  }

  return reports.flatMap((report) => (Array.isArray(report?.issue_list) ? report.issue_list : []));
}

function levelFromRule(rule) {
  const level = typeof rule === "string" ? rule.match(/Level\s+(A{1,3})\b/i)?.[1].toUpperCase() : null;
  if (level === "AAA") return "levelAAA";
  if (level === "AA") return "levelAA";
  if (level === "A") return "levelA";
  return null;
}

function principleFromRule(rule) {
  const firstDigit = typeof rule === "string" ? rule.match(/^(\d)\./)?.[1] : null;
  if (firstDigit === "1") return "perceivable";
  if (firstDigit === "2") return "operable";
  if (firstDigit === "3") return "understandable";
  if (firstDigit === "4") return "robust";
  return "bestPractice";
}

function countIssuesByCategory(issues, categoryFromIssue) {
  const counts = {};
  for (const issue of issues) {
    const category = categoryFromIssue(issue);
    if (!category) {
      continue;
    }
    counts[category] = (counts[category] ?? 0) + 1;
  }
  return counts;
}

function buildAccessibilityScore(reports) {
  const score = reports.reduce(
    (acc, report) => {
      SCORE_KEYS.forEach((level) => {
        acc.total += toNumber(report?.score_total?.[level]) * SCORE_WEIGHTS[level];
        acc.passed += toNumber(report?.score_passed?.[level]) * SCORE_WEIGHTS[level];
      });
      return acc;
    },
    { total: 0, passed: 0 },
  );

  return score.total > 0 ? Math.round((score.passed / score.total) * 100) : 0;
}

function buildStatisticsData(executions, selectedPage) {
  const runs = executions
    .map((execution, index) => {
      const reports = Array.isArray(execution.reports) ? execution.reports : [];
      const scopedReports = selectedPage === "all" ? reports : reports.filter((report) => report?.page === selectedPage);

      return {
        key: `run_${index}`,
        id: execution.id,
        dateTime: execution.dateTime,
        issues: issueListFromReports(scopedReports),
        accessibilityScore: buildAccessibilityScore(scopedReports),
      };
    })
    .sort((first, second) => first.dateTime.localeCompare(second.dateTime));

  const trendData = runs.map((run) => ({
    dateTime: run.dateTime,
    totalIssues: run.issues.length,
    accessibilityScore: run.accessibilityScore,
  }));

  const levelTrendData = runs.map((run) => ({
    dateTime: run.dateTime,
    levelA: 0,
    levelAA: 0,
    levelAAA: 0,
    ...countIssuesByCategory(run.issues, (issue) => levelFromRule(issue?.wcag_rule)),
  }));

  const principleTrendData = runs.map((run) => ({
    dateTime: run.dateTime,
    perceivable: 0,
    operable: 0,
    understandable: 0,
    robust: 0,
    bestPractice: 0,
    ...countIssuesByCategory(run.issues, (issue) => principleFromRule(issue?.wcag_rule)),
  }));

  const ruleCounts = new Map();
  for (const run of runs) {
    for (const issue of run.issues) {
      const rule = typeof issue?.wcag_rule === "string" && issue.wcag_rule.trim() ? issue.wcag_rule.trim() : "unknown-rule";
      if (!ruleCounts.has(rule)) {
        ruleCounts.set(rule, Object.fromEntries(runs.map((candidate) => [candidate.key, 0])));
      }
      ruleCounts.get(rule)[run.key] += 1;
    }
  }

  const ruleData = Array.from(ruleCounts.entries())
    .map(([rule, counts]) => ({ rule, ...counts }))
    .sort((first, second) => first.rule.localeCompare(second.rule));

  return { runs, trendData, levelTrendData, principleTrendData, ruleData };
}

function StatisticsView({ executions, selectedPage }) {
  const { runs, trendData, levelTrendData, principleTrendData, ruleData } = buildStatisticsData(executions, selectedPage);

  return (
    <section className="statistics-view">
      <section className="statistics-trend-grid">
        <IssuesTrendChart data={trendData} />
        <AccessibilityScoreTrendChart data={trendData} />
      </section>
      <RuleRunBarChart data={ruleData} runs={runs} />
      <section className="statistics-trend-grid">
        <WcagLevelTrendChart data={levelTrendData} />
        <WcagPrincipleTrendChart data={principleTrendData} />
      </section>
    </section>
  );
}

export default StatisticsView;
