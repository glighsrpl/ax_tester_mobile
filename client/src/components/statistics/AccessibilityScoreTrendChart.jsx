import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

function AccessibilityScoreTrendChart({ data }) {
  return (
    <article className="panel chart-card statistics-chart-card" aria-label="Accessibility score across runs">
      <h2>Accessibility Score Across Runs</h2>
      <div className="statistics-chart-wrap">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 12, right: 18, left: 0, bottom: 80 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis
              dataKey="dateTime"
              padding={{ left: 24, right: 0 }}
              angle={-90}
              height={72}
              interval={0}
              textAnchor="end"
              tick={{ fill: "var(--text-soft)", fontSize: 12 }}
            />
            <YAxis domain={[0, 100]} tick={{ fill: "var(--text-soft)", fontSize: 12 }} />
            <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)" }} />
            <Area
              type="monotone"
              dataKey="accessibilityScore"
              name="Accessibility score"
              stroke="var(--severity-minor)"
              fill="color-mix(in srgb, var(--severity-minor) 18%, var(--surface))"
              strokeWidth={2}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </article>
  );
}

export default AccessibilityScoreTrendChart;
