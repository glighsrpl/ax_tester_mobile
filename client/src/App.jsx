import { useMemo, useState } from "react";
import ExecutionFilter from "./components/ExecutionFilter";
import FilterBar from "./components/FilterBar";
import Header from "./components/Header";
import IssuesTable from "./components/IssuesTable";
import KpiGrid from "./components/KpiGrid";
import PourChart from "./components/PourChart";
import IssueByWcagChart from "./components/IssueByWcagChart";
import StatisticsFilterBar from "./components/statistics/StatisticsFilterBar";
import StatisticsView from "./components/statistics/StatisticsView";
import { buildDashboardData, normalizeReports } from "./lib/reportUtils";

const reportModules = import.meta.glob("../results*.json", {
  eager: true,
  import: "default",
});

function buildExecutions() {
  return Object.entries(reportModules)
    .map(([path, rawReports]) => ({
      id: path,
      dateTime: Array.isArray(rawReports) ? rawReports[0]?.date_time || path.split("/").pop() : path.split("/").pop(),
      reports: rawReports,
    }))
    .sort((first, second) => second.dateTime.localeCompare(first.dateTime));
}

function App() {
  const executions = useMemo(() => buildExecutions(), []);
  const [selectedExecutionId, setSelectedExecutionId] = useState(() => executions[0]?.id ?? "");
  const [currentView, setCurrentView] = useState("dashboard");
  const [selectedPage, setSelectedPage] = useState("all");
  const [searchTerm, setSearchTerm] = useState("");

  const selectedRawReports = useMemo(
    () => executions.find((execution) => execution.id === selectedExecutionId)?.reports ?? [],
    [executions, selectedExecutionId],
  );
  const reports = useMemo(() => normalizeReports(selectedRawReports), [selectedRawReports]);

  const dashboard = useMemo(
    () => buildDashboardData(reports, selectedPage, searchTerm),
    [reports, selectedPage, searchTerm],
  );

  const handleExecutionChange = (executionId) => {
    setSelectedExecutionId(executionId);
    setSelectedPage("all");
    setCurrentView("dashboard");
  };

  return (
    <div className="app-shell">
      <Header />

      {currentView === "statistics" ? (
        <main className="content-wrap">
          <StatisticsFilterBar
            pageOptions={dashboard.pageOptions}
            selectedPage={selectedPage}
            onPageChange={setSelectedPage}
            onBack={() => setCurrentView("dashboard")}
          />
          <StatisticsView executions={executions} selectedPage={selectedPage} />
        </main>
      ) : (
        <>
          <ExecutionFilter
            executions={executions}
            selectedExecutionId={selectedExecutionId}
            onExecutionChange={handleExecutionChange}
            onStatisticsView={() => setCurrentView("statistics")}
          />

          <main className="content-wrap">
            <div className="filter-score-row">
              <FilterBar
                pageOptions={dashboard.pageOptions}
                selectedPage={selectedPage}
                onPageChange={setSelectedPage}
              />

              <KpiGrid score={dashboard.score} />
            </div>

            <section className="chart-grid">
              <IssueByWcagChart score={dashboard.score} />
              <PourChart items={dashboard.principleDistribution} />
            </section>

            <IssuesTable rows={dashboard.visibleIssues} searchTerm={searchTerm} onSearchChange={setSearchTerm} />
          </main>
        </>
      )}
    </div>
  );
}

export default App;
