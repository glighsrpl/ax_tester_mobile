function isValidUrl(value) {
  try {
    new URL(value);
    return true;
  } catch {
    return false;
  }
}

function FilterBar({ pageOptions, selectedPage, onPageChange }) {
  const isAllPages = selectedPage === "all";
  const canOpenPage = !isAllPages && isValidUrl(selectedPage);

  const handleOpenPage = () => {
    if (!canOpenPage) {
      return;
    }
    window.open(selectedPage, "_blank", "noopener,noreferrer");
  };

  return (
    <section className="panel filter-panel" aria-label="Report filters">
      <div className="field-group">
        <label htmlFor="page-filter">Page</label>
        <select id="page-filter" value={selectedPage} onChange={(event) => onPageChange(event.target.value)}>
          <option value="all">All pages</option>
          {pageOptions.map((page) => (
            <option key={page} value={page}>
              {page}
            </option>
          ))}
        </select>
      </div>

      <div className="current-scope-actions" aria-live="polite">
        <button
          type="button"
          className="scope-action-button"
          onClick={() => onPageChange("all")}
          disabled={isAllPages}
        >
          View all pages
        </button>
        <button type="button" className="scope-action-button" onClick={handleOpenPage} disabled={!canOpenPage}>
          Open page
        </button>
      </div>
    </section>
  );
}

export default FilterBar;
