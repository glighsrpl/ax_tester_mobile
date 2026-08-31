const DEFAULT_SEVERITY = "minor";

export const SEVERITY_META = {
  critical: { label: "Critical", colorVar: "--severity-critical" },
  serious: { label: "High", colorVar: "--severity-serious" },
  moderate: { label: "Medium", colorVar: "--severity-moderate" },
  minor: { label: "Low", colorVar: "--severity-minor" },
};

const SCORE_KEYS = ["level_A", "level_AA", "level_AAA"];
const SCORE_WEIGHTS = {
  level_A: 3,
  level_AA: 2,
  level_AAA: 1,
};

function ensureString(value, fallback = "") {
  if (typeof value === "string") {
    return value.trim();
  }
  return fallback;
}

function ensureNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeSeverity(value) {
  const normalized = ensureString(value).toLowerCase();
  return normalized in SEVERITY_META ? normalized : DEFAULT_SEVERITY;
}

function normalizeScoreInfo(score) {
  return {
    level_A: ensureNumber(score?.level_A, 0),
    level_AA: ensureNumber(score?.level_AA, 0),
    level_AAA: ensureNumber(score?.level_AAA, 0),
  };
}

function normalizePotentialExposures(exposures) {
  if (!Array.isArray(exposures)) {
    return [];
  }

  return exposures
    .map((exposure) => {
      if (typeof exposure === "string") {
        return {
          category: ensureString(exposure),
          description: "",
        };
      }

      return {
        category: ensureString(exposure?.category),
        description: ensureString(exposure?.description),
      };
    })
    .filter((exposure) => exposure.category || exposure.description);
}

function normalizeIssue(issue, page, idx) {
  return {
    id: ensureString(issue?.id, `${page}-${idx + 1}`),
    wcag_rule: ensureString(issue?.wcag_rule, "best-practice"),
    description: ensureString(issue?.description, "No description provided"),
    severity: normalizeSeverity(issue?.severity),
    source: ensureString(issue?.source, "axe-core"),
    confidence: ensureString(issue?.confidence, "medium"),
    html_snippet: ensureString(issue?.html_snippet),
    fix: ensureString(issue?.fix),
    image_url_or_path: typeof issue?.image_url_or_path === "string" ? issue.image_url_or_path : null,
    why_this_matters: ensureString(issue?.why_this_matters),
    potential_exposures: normalizePotentialExposures(issue?.potential_exposures),
    page,
  };
}

function normalizeMetadata(entries) {
  if (!Array.isArray(entries)) {
    return [];
  }

  return entries
    .map((entry) => ({
      key: ensureString(entry?.key),
      value: typeof entry?.value === "number" ? entry.value : ensureString(entry?.value),
    }))
    .filter((entry) => entry.key);
}

export function normalizeReports(rawReports) {
  if (!Array.isArray(rawReports)) {
    return [];
  }

  return rawReports.map((report, reportIndex) => {
    const page = ensureString(report?.page, `unknown-page-${reportIndex + 1}`);
    const issueList = Array.isArray(report?.issue_list)
      ? report.issue_list.map((issue, issueIndex) => normalizeIssue(issue, page, issueIndex))
      : [];

    return {
      tool_name: ensureString(report?.tool_name, "unknown-tool"),
      total_issues: ensureNumber(report?.total_issues, issueList.length),
      page,
      date_time: ensureString(report?.date_time),
      issue_list: issueList,
      score_passed: normalizeScoreInfo(report?.score_passed),
      score_total: normalizeScoreInfo(report?.score_total),
      metadata: normalizeMetadata(report?.metadata),
    };
  });
}

function flattenIssues(reports) {
  return reports.flatMap((report) => report.issue_list);
}

function scoreTotals(reports, scoreKey) {
  return reports.reduce(
    (acc, report) => {
      SCORE_KEYS.forEach((level) => {
        acc[level] += ensureNumber(report?.[scoreKey]?.[level], 0);
      });
      return acc;
    },
    { level_A: 0, level_AA: 0, level_AAA: 0 },
  );
}

function principleFromRule(rule) {
  const firstDigit = ensureString(rule).match(/^(\d)\./)?.[1];
  if (firstDigit === "1") return "Perceivable";
  if (firstDigit === "2") return "Operable";
  if (firstDigit === "3") return "Understandable";
  if (firstDigit === "4") return "Robust";
  return "Best Practice";
}

function matchesSearch(issue, searchTerm) {
  if (!searchTerm) {
    return true;
  }

  const haystack = [
    issue.id,
    issue.description,
    issue.wcag_rule,
    issue.page,
    issue.source,
    issue.confidence,
    issue.fix,
    issue.html_snippet,
    issue.why_this_matters,
    ...(issue.potential_exposures ?? []).flatMap((exposure) => [
      exposure.category,
      exposure.description,
    ]),
  ]
    .join(" ")
    .toLowerCase();

  return haystack.includes(searchTerm.toLowerCase());
}

function principleCounts(issues) {
  const base = {
    Perceivable: 0,
    Operable: 0,
    Understandable: 0,
    Robust: 0,
    "Best Practice": 0,
  };

  for (const issue of issues) {
    const principle = principleFromRule(issue.wcag_rule);
    base[principle] += 1;
  }

  return Object.entries(base).map(([label, value]) => ({ label, value }));
}

export function buildDashboardData(reports, selectedPage, searchTerm) {
  const pages = Array.from(new Set(reports.map((report) => report.page))).sort((a, b) => a.localeCompare(b));

  const selectedReports =
    selectedPage === "all" ? reports : reports.filter((report) => report.page === selectedPage);

  const scopedIssues = flattenIssues(selectedReports);
  const visibleIssues = scopedIssues.filter((issue) => matchesSearch(issue, searchTerm));

  const totalScore = scoreTotals(selectedReports, "score_total");
  const passedScore = scoreTotals(selectedReports, "score_passed");

  const totalChecks = SCORE_KEYS.reduce((sum, key) => sum + totalScore[key], 0);
  const passedChecks = SCORE_KEYS.reduce((sum, key) => sum + passedScore[key], 0);
  const weightedTotalChecks = SCORE_KEYS.reduce((sum, key) => sum + totalScore[key] * SCORE_WEIGHTS[key], 0);
  const weightedPassedChecks = SCORE_KEYS.reduce((sum, key) => sum + passedScore[key] * SCORE_WEIGHTS[key], 0);
  const complianceRate =
    weightedTotalChecks > 0 ? Math.round((weightedPassedChecks / weightedTotalChecks) * 100) : 0;

  const pageCount = selectedPage === "all" ? pages.length : selectedReports.length;

  return {
    pageOptions: pages,
    selectedIssues: scopedIssues,
    visibleIssues,
    principleDistribution: principleCounts(scopedIssues),
    score: {
      totalChecks,
      passedChecks,
      complianceRate,
      totalsByLevel: totalScore,
      passedByLevel: passedScore,
    },
    kpis: {
      totalPages: pageCount,
      totalIssues: scopedIssues.length,
      criticalIssues: scopedIssues.filter((issue) => issue.severity === "critical").length,
      avgIssuesPerPage: pageCount > 0 ? Number((scopedIssues.length / pageCount).toFixed(1)) : 0,
    },
  };
}

export function truncateText(value, maxLength = 140) {
  const normalized = ensureString(value);
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength)}...`;
}
