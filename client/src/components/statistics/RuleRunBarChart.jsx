import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const BAR_COLORS = [
  "var(--brand)",
  "var(--severity-minor)",
  "var(--severity-critical)",
  "var(--text-soft)",
  "color-mix(in srgb, var(--brand) 56%, var(--severity-minor))",
  "color-mix(in srgb, var(--severity-critical) 72%, var(--brand))",
];

function RuleRunBarChart({ data, runs }) {
  return (
    <article className="panel chart-card statistics-chart-card" aria-label="Issues by rule and run">
      <h2>Issues by Rule Across Runs</h2>
      <div className="statistics-chart-wrap statistics-bar-chart-wrap">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 36, right: 18, left: 0, bottom: 148 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis
              dataKey="rule"
              angle={-90}
              height={72}
              interval={0}
              textAnchor="end"
              tick={{ fill: "var(--text-soft)", fontSize: 12 }}
            />
            <YAxis allowDecimals={false} tick={{ fill: "var(--text-soft)", fontSize: 12 }} />
            <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)" }} />
            <Legend verticalAlign="top" align="center" wrapperStyle={{ top: 0 }} />
            {runs.map((run, index) => (
              <Bar
                key={run.key}
                dataKey={run.key}
                name={run.dateTime}
                fill={BAR_COLORS[index % BAR_COLORS.length]}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </article>
  );
}

export default RuleRunBarChart;
