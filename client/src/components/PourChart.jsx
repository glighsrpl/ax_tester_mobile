const COLORS = {
  Perceivable: "var(--severity-minor)",
  Operable: "var(--brand)",
  Understandable: "var(--severity-critical)",
  Robust: "var(--text-soft)",
  "Best Practice": "color-mix(in srgb, var(--text-soft) 62%, var(--surface))",
};

function buildConicGradient(items) {
  const total = items.reduce((sum, item) => sum + item.value, 0);
  if (!total) {
    return "conic-gradient(color-mix(in srgb, var(--text-soft) 25%, var(--surface)) 0 100%)";
  }

  let cumulative = 0;
  const slices = items.map((item) => {
    const start = (cumulative / total) * 100;
    cumulative += item.value;
    const end = (cumulative / total) * 100;
    return `${COLORS[item.label]} ${start}% ${end}%`;
  });

  return `conic-gradient(${slices.join(", ")})`;
}

function PourChart({ items }) {
  const total = items.reduce((sum, item) => sum + item.value, 0);

  return (
    <article className="panel chart-card" aria-label="Issues by WCAG principle">
      <h2>Issues by WCAG Principle</h2>
      <div className="pour-layout">
        <div className="donut-wrap">
          <div className="donut" style={{ background: buildConicGradient(items) }}>
            <div className="donut-center">
              <strong>{total}</strong>
              <span>issues</span>
            </div>
          </div>
        </div>

        <ul className="legend-list">
          {items.map((item) => (
            <li key={item.label}>
              <span className="legend-dot" style={{ backgroundColor: COLORS[item.label] }} />
              <span className="legend-label">{item.label}</span>
              <strong>{item.value}</strong>
            </li>
          ))}
        </ul>
      </div>
    </article>
  );
}

export default PourChart;
