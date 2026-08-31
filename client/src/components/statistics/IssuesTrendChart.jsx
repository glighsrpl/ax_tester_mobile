import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

function IssuesTrendChart({ data }) {
  return (
    <article className="panel chart-card statistics-chart-card" aria-label="Total issues across runs">
      <h2>Total Issues Across Runs</h2>
      <div className="statistics-chart-wrap">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 12, right: 18, left: 0, bottom: 80 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="dateTime" 
            padding={{ left: 24, right: 0 }}
              angle={-90}
              height={72}
              interval={0}
              textAnchor="end"
              tick={{ fill: "var(--text-soft)", fontSize: 12 }} 
            />
            <YAxis allowDecimals={false} tick={{ fill: "var(--text-soft)", fontSize: 12 }} />
            <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)" }} />
            <Area
              type="monotone"
              dataKey="totalIssues"
              name="Total issues"
              stroke="var(--brand)"
              fill="var(--brand-soft)"
              strokeWidth={2}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </article>
  );
}

export default IssuesTrendChart;
