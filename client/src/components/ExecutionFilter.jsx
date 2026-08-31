function ExecutionFilter({ executions, selectedExecutionId, onExecutionChange, onStatisticsView }) {
  return (
    <section className="panel execution-filter-panel" aria-label="Execution filter">
      <div className="field-group">
        <label htmlFor="execution-filter">Date and time execution</label>
        <select
          id="execution-filter"
          value={selectedExecutionId}
          onChange={(event) => onExecutionChange(event.target.value)}
        >
          {executions.map((execution) => (
            <option key={execution.id} value={execution.id}>
              {execution.dateTime}
            </option>
          ))}
        </select>
      </div>

      <button type="button" className="scope-action-button" onClick={onStatisticsView}>
        View all statistics
      </button>
    </section>
  );
}

export default ExecutionFilter;
