function scoreState(score) {
  if (score >= 90) return "Excellent";
  if (score >= 75) return "Good";
  if (score >= 60) return "Needs improvement";
  return "Critical";
}

function KpiGrid({ score }) {
  return (
    <section className="kpi-grid" aria-label="Key metrics">
      <article className="panel kpi-card">
        <div className="kpi-card-head">
          <p className="kpi-label">Accessibility Score</p>
          <span className="kpi-help">
            <button
              type="button"
              className="kpi-help-trigger"
              aria-label="How the accessibility score is calculated"
              aria-describedby="accessibility-score-tooltip"
            >
              ?
            </button>
            <span id="accessibility-score-tooltip" role="tooltip" className="kpi-help-tooltip">
              <strong className="kpi-help-tooltip-title">How the score is calculated</strong>
              <span
                className="kpi-help-tooltip-formula"
                aria-label="Accessibility score equals weighted passed checks divided by weighted total checks, multiplied by 100"
              >
                <span className="kpi-formula-left">Score =</span>
                <span className="kpi-fraction" aria-hidden="true">
                  <span className="kpi-fraction-top">weighted passed checks</span>
                  <span className="kpi-fraction-bottom">weighted total checks</span>
                </span>
                <span className="kpi-formula-right">x 100</span>
              </span>
              <span className="kpi-help-tooltip-subtitle">WCAG level weights</span>
              <span className="kpi-weight-list">
                <span className="kpi-weight-item">
                  <span className="kpi-weight-label">Level A</span>
                  <span className="kpi-weight-value">3x</span>
                </span>
                <span className="kpi-weight-item">
                  <span className="kpi-weight-label">Level AA</span>
                  <span className="kpi-weight-value">2x</span>
                </span>
                <span className="kpi-weight-item">
                  <span className="kpi-weight-label">Level AAA</span>
                  <span className="kpi-weight-value">1x</span>
                </span>
              </span>
            </span>
          </span>
        </div>
        <div className="kpi-main-row">
          <strong className="kpi-value">{score.complianceRate}%</strong>
          <span className="kpi-subvalue">{scoreState(score.complianceRate)}</span>
        </div>
        <div className="progress-track" aria-hidden="true">
          <span className="progress-fill" style={{ width: `${score.complianceRate}%` }} />
        </div>
        <p className="kpi-detail">
          {score.passedChecks} / {score.totalChecks} checks passed
        </p>
      </article>

    </section>
  );
}

export default KpiGrid;
