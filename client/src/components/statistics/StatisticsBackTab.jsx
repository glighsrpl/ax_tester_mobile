function StatisticsBackTab({ onBack }) {
  return (
    <section className="panel statistics-back-tab" aria-label="Statistics navigation">
      <button type="button" className="scope-action-button" onClick={onBack}>
        Back to dashboard
      </button>
    </section>
  );
}

export default StatisticsBackTab;
