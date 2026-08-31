function toNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function buildLevelItems(score) {
  const totalsByLevel = score?.totalsByLevel ?? {};
  const passedByLevel = score?.passedByLevel ?? {};
  const levelAIssues = Math.max(toNumber(totalsByLevel.level_A) - toNumber(passedByLevel.level_A), 0);
  const levelAAIssues = Math.max(toNumber(totalsByLevel.level_AA) - toNumber(passedByLevel.level_AA), 0);
  const levelAAAIssues = Math.max(toNumber(totalsByLevel.level_AAA) - toNumber(passedByLevel.level_AAA), 0);

  return [
    { key: "critical", label: "Level A", value: levelAIssues },
    { key: "serious", label: "Level AA", value: levelAAIssues },
    { key: "minor", label: "Level AAA", value: levelAAAIssues },
  ];
}

function IssueByWcagChart({ score }) {
  const levelItems = buildLevelItems(score);
  const maxValue = Math.max(...levelItems.map((item) => item.value), 1);

  return (
    <article className="panel chart-card" aria-label="Issues by WCAG level">
      <h2>Issues by WCAG Level</h2>
      <div className="severity-list">
        {levelItems.map((item) => {
          const width = (item.value / maxValue) * 100;
          return (
            <div className="severity-row" key={item.label}>
              <span className="severity-name">{item.label}</span>
              <div className="severity-track" role="img" aria-label={`${item.label}: ${item.value}`}>
                <span className={`severity-fill severity-${item.key}`} style={{ width: `${width}%` }} />
              </div>
              <strong className="severity-value">{item.value}</strong>
            </div>
          );
        })}
      </div>
    </article>
  );
}

export default IssueByWcagChart;
