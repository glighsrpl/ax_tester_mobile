import { useEffect, useMemo, useState } from "react";
import { SEVERITY_META, truncateText } from "../lib/reportUtils";

const ITEMS_PER_PAGE = 10;
const VIEW_MODES = {
  QUALITATIVE: "qualitative",
  TECHNICAL: "technical",
};

function SortIcon({ direction }) {
  if (direction === "asc") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 20V5" />
        <path d="m7 10 5-5 5 5" />
      </svg>
    );
  }

  if (direction === "desc") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 4v15" />
        <path d="m7 14 5 5 5-5" />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8 19V5" />
      <path d="m4.5 8.5 3.5-3.5 3.5 3.5" />
      <path d="M16 5v14" />
      <path d="m12.5 15.5 3.5 3.5 3.5-3.5" />
    </svg>
  );
}

function compactWcagRule(rule) {
  const normalized = String(rule || "").trim();
  if (!normalized || normalized === "best-practice") {
    return "Best practice";
  }

  const ruleId = normalized.match(/^(\d+\.\d+\.\d+)/)?.[1];
  const level = normalized.match(/\(Level (A{1,3})\)/)?.[1];
  return [ruleId, level].filter(Boolean).join(" ") || normalized;
}

function getIssueKey(issue) {
  return `${issue.page}-${issue.id}`;
}

function PotentialExposuresCell({ exposures, expanded, onToggle }) {
  if (!exposures.length) {
    return <span className="empty-cell">-</span>;
  }

  const visibleExposures = expanded ? exposures : exposures.slice(0, 2);
  const hiddenCount = Math.max(0, exposures.length - 2);

  return (
    <div className="exposure-list">
      {visibleExposures.map((exposure, index) => (
        <div className="exposure-item" key={`${exposure.category}-${index}`}>
          {exposure.category ? <strong className="exposure-category">{exposure.category}</strong> : null}
          {exposure.description ? <span className="exposure-description">{exposure.description}</span> : null}
        </div>
      ))}
      {hiddenCount > 0 ? (
        <button
          type="button"
          className="exposure-toggle"
          onClick={onToggle}
          aria-expanded={expanded}
        >
          {expanded ? "Show less" : `+${hiddenCount} more`}
        </button>
      ) : null}
    </div>
  );
}

function IssuesTable({ rows, searchTerm, onSearchChange }) {
  const [sortConfig, setSortConfig] = useState({ key: null, direction: null });
  const [currentPage, setCurrentPage] = useState(1);
  const [viewMode, setViewMode] = useState(VIEW_MODES.QUALITATIVE);
  const [expandedExposureRows, setExpandedExposureRows] = useState(() => new Set());

  const getSortDirection = (key) => (sortConfig.key === key ? sortConfig.direction : null);
  const isQualitativeView = viewMode === VIEW_MODES.QUALITATIVE;

  const sortedRows = useMemo(() => {
    if (!sortConfig.key || !sortConfig.direction) {
      return rows;
    }

    const severityOrder = {
      minor: 0,
      moderate: 1,
      serious: 2,
      critical: 3,
    };

    return rows
      .map((issue, index) => ({ issue, index }))
      .sort((left, right) => {
        let compareResult = 0;

        if (sortConfig.key === "severity") {
          const leftRank = severityOrder[left.issue.severity] ?? 0;
          const rightRank = severityOrder[right.issue.severity] ?? 0;
          compareResult = leftRank - rightRank;
        } else {
          const leftValue = String(left.issue?.[sortConfig.key] ?? "");
          const rightValue = String(right.issue?.[sortConfig.key] ?? "");
          compareResult = leftValue.localeCompare(rightValue, undefined, { numeric: true, sensitivity: "base" });
        }

        if (compareResult === 0) {
          return left.index - right.index;
        }

        return sortConfig.direction === "asc" ? compareResult : -compareResult;
      })
      .map((entry) => entry.issue);
  }, [rows, sortConfig]);

  const handleSortToggle = (key) => {
    setCurrentPage(1);
    setSortConfig((current) => {
      if (current.key === key) {
        return { key, direction: current.direction === "asc" ? "desc" : "asc" };
      }
      return { key, direction: "asc" };
    });
  };

  const handleViewModeChange = (nextViewMode) => {
    setViewMode(nextViewMode);
    if (nextViewMode === VIEW_MODES.QUALITATIVE && sortConfig.key && sortConfig.key !== "severity") {
      setSortConfig({ key: null, direction: null });
    }
  };

  const totalPages = Math.max(1, Math.ceil(sortedRows.length / ITEMS_PER_PAGE));
  const pagedRows = useMemo(() => {
    const start = (currentPage - 1) * ITEMS_PER_PAGE;
    return sortedRows.slice(start, start + ITEMS_PER_PAGE);
  }, [sortedRows, currentPage]);
  const visiblePageItems = useMemo(() => {
    if (totalPages <= 7) {
      return Array.from({ length: totalPages }, (_, idx) => idx + 1);
    }

    const pages = new Set([1, totalPages, currentPage - 1, currentPage, currentPage + 1]);
    const filteredPages = Array.from(pages)
      .filter((page) => page >= 1 && page <= totalPages)
      .sort((a, b) => a - b);

    const items = [];
    for (let i = 0; i < filteredPages.length; i += 1) {
      const page = filteredPages[i];
      const prevPage = filteredPages[i - 1];

      if (i > 0 && page - prevPage > 1) {
        items.push("ellipsis");
      }

      items.push(page);
    }

    return items;
  }, [currentPage, totalPages]);

  useEffect(() => {
    setCurrentPage((page) => Math.min(page, totalPages));
  }, [totalPages]);

  const handlePageChange = (page) => {
    if (page < 1 || page > totalPages) {
      return;
    }
    setCurrentPage(page);
  };

  const handleExposureToggle = (issueKey) => {
    setExpandedExposureRows((current) => {
      const next = new Set(current);
      if (next.has(issueKey)) {
        next.delete(issueKey);
      } else {
        next.add(issueKey);
      }
      return next;
    });
  };

  return (
    <section className="panel table-panel" aria-label="Issue details">
      <div className="table-header">
        <div className="table-title-group">
          <h2>Issue Details</h2>
          <p>{rows.length} results found</p>
        </div>
        <div className="table-actions">
          <div className="table-view-toggle" role="group" aria-label="Issue table view">
            <button
              type="button"
              className={`table-view-button ${isQualitativeView ? "is-active" : ""}`}
              onClick={() => handleViewModeChange(VIEW_MODES.QUALITATIVE)}
              aria-pressed={isQualitativeView}
            >
              Qualitative
            </button>
            <button
              type="button"
              className={`table-view-button ${!isQualitativeView ? "is-active" : ""}`}
              onClick={() => handleViewModeChange(VIEW_MODES.TECHNICAL)}
              aria-pressed={!isQualitativeView}
            >
              Technical
            </button>
          </div>
          <div className="field-group table-search">
            <label htmlFor="issue-search-table">Issue Search</label>
            <input
              id="issue-search-table"
              type="search"
              value={searchTerm}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder="Search by issue, WCAG rule, exposure..."
            />
          </div>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="empty-state">
          <strong>No issues found</strong>
          <p>Try changing the page filter or search query.</p>
        </div>
      ) : (
        <>
          <div className={`table-wrap table-wrap-${viewMode}`}>
            <table>
              {isQualitativeView ? (
                <thead>
                  <tr>
                    <th>Issue</th>
                    <th
                      aria-sort={
                        getSortDirection("severity") === "asc"
                          ? "ascending"
                          : getSortDirection("severity") === "desc"
                            ? "descending"
                            : "none"
                      }
                    >
                      <button
                        type="button"
                        className="table-sort-button"
                        onClick={() => handleSortToggle("severity")}
                      >
                        Severity
                        <span className="table-sort-arrow" aria-hidden="true">
                          <SortIcon direction={getSortDirection("severity")} />
                        </span>
                      </button>
                    </th>
                    <th>Why This Matters</th>
                    <th>Potential Exposures</th>
                    <th>Recommended Action</th>
                  </tr>
                </thead>
              ) : (
                <thead>
                  <tr>
                    <th>Issue</th>
                    <th
                      aria-sort={
                        getSortDirection("severity") === "asc"
                          ? "ascending"
                          : getSortDirection("severity") === "desc"
                            ? "descending"
                            : "none"
                      }
                    >
                      <button
                        type="button"
                        className="table-sort-button"
                        onClick={() => handleSortToggle("severity")}
                      >
                        Severity
                        <span className="table-sort-arrow" aria-hidden="true">
                          <SortIcon direction={getSortDirection("severity")} />
                        </span>
                      </button>
                    </th>
                    <th
                      aria-sort={
                        getSortDirection("wcag_rule") === "asc"
                          ? "ascending"
                          : getSortDirection("wcag_rule") === "desc"
                            ? "descending"
                            : "none"
                      }
                    >
                      <button
                        type="button"
                        className="table-sort-button"
                        onClick={() => handleSortToggle("wcag_rule")}
                      >
                        WCAG Rule
                        <span className="table-sort-arrow" aria-hidden="true">
                          <SortIcon direction={getSortDirection("wcag_rule")} />
                        </span>
                      </button>
                    </th>
                    <th
                      aria-sort={
                        getSortDirection("page") === "asc"
                          ? "ascending"
                          : getSortDirection("page") === "desc"
                            ? "descending"
                            : "none"
                      }
                    >
                      <button type="button" className="table-sort-button" onClick={() => handleSortToggle("page")}>
                        Page
                        <span className="table-sort-arrow" aria-hidden="true">
                          <SortIcon direction={getSortDirection("page")} />
                        </span>
                      </button>
                    </th>
                    <th>Element</th>
                    <th>Suggested Fix</th>
                  </tr>
                </thead>
              )}
              <tbody>
                {pagedRows.map((issue) => {
                  const issueKey = getIssueKey(issue);
                  const imageLink =
                    typeof issue.image_url_or_path === "string" && issue.image_url_or_path.trim().length > 0
                      ? issue.image_url_or_path.trim()
                      : null;

                  if (isQualitativeView) {
                    return (
                      <tr key={issueKey}>
                        <td>
                          <strong>{issue.description}</strong>
                          <div className="issue-meta-row">
                            <span className="wcag-compact">{compactWcagRule(issue.wcag_rule)}</span>
                          </div>
                        </td>
                        <td>
                          <span className={`severity-pill severity-${issue.severity}`}>
                            {SEVERITY_META[issue.severity]?.label ?? issue.severity}
                          </span>
                        </td>
                        <td>
                          <div className="why-cell">
                            <span className="plain-cell">{issue.why_this_matters || "-"}</span>
                          </div>
                        </td>
                        <td>
                          <PotentialExposuresCell
                            exposures={issue.potential_exposures ?? []}
                            expanded={expandedExposureRows.has(issueKey)}
                            onToggle={() => handleExposureToggle(issueKey)}
                          />
                        </td>
                        <td>{truncateText(issue.fix || "-", 160)}</td>
                      </tr>
                    );
                  }

                  return (
                    <tr key={issueKey}>
                      <td>
                        <strong>{issue.description}</strong>
                        <span className="sub-cell">SOURCE: {issue.source}</span>
                      </td>
                      <td>
                        <span className={`severity-pill severity-${issue.severity}`}>
                          {SEVERITY_META[issue.severity]?.label ?? issue.severity}
                        </span>
                      </td>
                      <td>{issue.wcag_rule}</td>
                      <td>{issue.page}</td>
                      <td>
                        <div className="element-cell">
                          <code>{truncateText(issue.html_snippet || "-", 120)}</code>
                          {imageLink ? (
                            <a
                              className="element-image-link"
                              href={imageLink}
                              target="_blank"
                              rel="noreferrer"
                              aria-label="Open image reference"
                              title="Open image reference"
                            >
                              <svg viewBox="0 0 24 24" aria-hidden="true">
                                <path d="M10 13a5 5 0 0 1 0-7l1.6-1.6a5 5 0 0 1 7 7L17 13" />
                                <path d="M14 11a5 5 0 0 1 0 7l-1.6 1.6a5 5 0 0 1-7-7L7 11" />
                              </svg>
                            </a>
                          ) : null}
                        </div>
                      </td>
                      <td>{truncateText(issue.fix || "-", 140)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="table-pagination" aria-label="Issues pagination">
            <button
              type="button"
              className="table-page-button"
              onClick={() => handlePageChange(currentPage - 1)}
              disabled={currentPage === 1}
            >
              Previous
            </button>

            <div className="table-page-list">
              {visiblePageItems.map((item, idx) => {
                if (item === "ellipsis") {
                  return (
                    <span key={`ellipsis-${idx}`} className="table-page-ellipsis" aria-hidden="true">
                      ...
                    </span>
                  );
                }

                return (
                  <button
                    key={item}
                    type="button"
                    className={`table-page-button ${item === currentPage ? "is-active" : ""}`}
                    onClick={() => handlePageChange(item)}
                    aria-current={item === currentPage ? "page" : undefined}
                  >
                    {item}
                  </button>
                );
              })}
            </div>

            <button
              type="button"
              className="table-page-button"
              onClick={() => handlePageChange(currentPage + 1)}
              disabled={currentPage === totalPages}
            >
              Next
            </button>
          </div>
        </>
      )}
    </section>
  );
}

export default IssuesTable;
