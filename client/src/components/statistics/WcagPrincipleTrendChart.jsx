import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const PRINCIPLE_SERIES = [
  { key: "perceivable", name: "Perceivable", color: "var(--severity-minor)" },
  { key: "operable", name: "Operable", color: "var(--brand)" },
  { key: "understandable", name: "Understandable", color: "var(--severity-critical)" },
  { key: "robust", name: "Robust", color: "var(--text-soft)" },
  { key: "bestPractice", name: "Best Practice", color: "color-mix(in srgb, var(--text-soft) 62%, var(--surface))" },
];

function WcagPrincipleTrendChart({ data }) {
  return (
    <article className="panel chart-card statistics-chart-card" aria-label="Issues by WCAG principle across runs">
      <h2>Issues by WCAG Principle Across Runs</h2>
      <div className="statistics-chart-wrap">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 36, right: 18, left: 0, bottom: 80 }}>
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
            <YAxis allowDecimals={false} tick={{ fill: "var(--text-soft)", fontSize: 12 }} />
            <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)" }} />
            <Legend verticalAlign="top" align="center" wrapperStyle={{ top: 0 }} />
            {PRINCIPLE_SERIES.map((series) => (
              <Area
                key={series.key}
                type="monotone"
                dataKey={series.key}
                name={series.name}
                stroke={series.color}
                fill="transparent"
                fillOpacity={0}
                strokeWidth={2}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </article>
  );
}

export default WcagPrincipleTrendChart;
