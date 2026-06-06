import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  Download,
  FileSearch,
  Filter,
  RefreshCw
} from "lucide-react";

const API_ROOT = "";

async function fetchJson(path, options) {
  const response = await fetch(`${API_ROOT}${path}`, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Request failed: ${response.status}`);
  }
  return data;
}

function statusTone(status) {
  if (status === "pass" || status === "resolved") return "good";
  if (status === "missing") return "muted";
  return "warn";
}

export default function App() {
  const [sites, setSites] = useState([]);
  const [datasets, setDatasets] = useState([]);
  const [schema, setSchema] = useState({ status: "loading", errors: [] });
  const [selectedSites, setSelectedSites] = useState(new Set());
  const [selectedStreams, setSelectedStreams] = useState(new Set());
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [format, setFormat] = useState("csv");
  const [preview, setPreview] = useState(null);
  const [exportResult, setExportResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const streamOptions = useMemo(
    () => Array.from(new Set(datasets.map((dataset) => dataset.stream))).sort(),
    [datasets]
  );
  const exportReady = datasets.some((dataset) => dataset.export_available);

  useEffect(() => {
    refresh();
  }, []);

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const [siteData, datasetData, schemaData] = await Promise.all([
        fetchJson("/api/sites"),
        fetchJson("/api/datasets"),
        fetchJson("/api/schema-inspection")
      ]);
      setSites(siteData.sites || []);
      setDatasets(datasetData.datasets || []);
      setSchema(schemaData || { status: "missing", errors: [] });
      setSelectedSites(new Set((siteData.sites || []).map((site) => site.site_id)));
      setSelectedStreams(new Set((datasetData.datasets || []).map((dataset) => dataset.stream)));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function toggleSite(siteId) {
    setSelectedSites((current) => {
      const next = new Set(current);
      next.has(siteId) ? next.delete(siteId) : next.add(siteId);
      return next;
    });
  }

  function toggleStream(stream) {
    setSelectedStreams((current) => {
      const next = new Set(current);
      next.has(stream) ? next.delete(stream) : next.add(stream);
      return next;
    });
  }

  function payload() {
    return {
      site_ids: Array.from(selectedSites),
      streams: Array.from(selectedStreams),
      start_time_utc: startTime || null,
      end_time_utc: endTime || null,
      format
    };
  }

  async function runPreview() {
    setLoading(true);
    setError("");
    setExportResult(null);
    try {
      setPreview(
        await fetchJson("/api/exports/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload())
        })
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function createExport() {
    setLoading(true);
    setError("");
    try {
      setExportResult(
        await fetchJson("/api/exports", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload())
        })
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand">
          <img src="/appalachian-hydro.svg" alt="" />
          <div>
            <h1>NextGen Hydra</h1>
            <p>Appalachian historical streamflow portal</p>
          </div>
        </div>
        <button className="iconButton" onClick={refresh} disabled={loading} title="Refresh artifacts">
          <RefreshCw size={18} />
        </button>
      </header>

      <section className="statusStrip" aria-label="Artifact status">
        <StatusChip icon={<Database size={16} />} label="Datasets" value={datasets.length} tone="muted" />
        <StatusChip
          icon={<FileSearch size={16} />}
          label="Schema"
          value={schema.status}
          tone={statusTone(schema.status)}
        />
        <StatusChip
          icon={exportReady ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
          label="Exports"
          value={exportReady ? "available" : "blocked"}
          tone={exportReady ? "good" : "warn"}
        />
      </section>

      {error && <div className="errorBanner">{error}</div>}

      <div className="workspace">
        <section className="panel controls" aria-label="Export filters">
          <div className="panelHeader">
            <Filter size={18} />
            <h2>Request</h2>
          </div>
          <fieldset>
            <legend>Sites</legend>
            <div className="checkGrid">
              {sites.map((site) => (
                <label key={site.site_id} className="checkRow">
                  <input
                    type="checkbox"
                    checked={selectedSites.has(site.site_id)}
                    onChange={() => toggleSite(site.site_id)}
                  />
                  <span>
                    <strong>{site.usgs_gage_id}</strong>
                    {site.name}
                  </span>
                  <small className={`dot ${statusTone(site.crosswalk_status)}`}>{site.crosswalk_status}</small>
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend>Streams</legend>
            <div className="segmented">
              {streamOptions.map((stream) => (
                <button
                  key={stream}
                  className={selectedStreams.has(stream) ? "selected" : ""}
                  onClick={() => toggleStream(stream)}
                  type="button"
                >
                  {stream}
                </button>
              ))}
            </div>
          </fieldset>

          <fieldset className="timeGrid">
            <legend>Time</legend>
            <label>
              Start UTC
              <input type="datetime-local" value={startTime} onChange={(event) => setStartTime(event.target.value)} />
            </label>
            <label>
              End UTC
              <input type="datetime-local" value={endTime} onChange={(event) => setEndTime(event.target.value)} />
            </label>
          </fieldset>

          <fieldset>
            <legend>Format</legend>
            <div className="segmented">
              {["csv", "parquet"].map((value) => (
                <button
                  key={value}
                  className={format === value ? "selected" : ""}
                  onClick={() => setFormat(value)}
                  type="button"
                >
                  {value.toUpperCase()}
                </button>
              ))}
            </div>
          </fieldset>

          <div className="actions">
            <button onClick={runPreview} disabled={loading || selectedSites.size === 0}>
              <FileSearch size={18} />
              Preview
            </button>
            <button
              className="primary"
              onClick={createExport}
              disabled={loading || !preview?.available}
            >
              <Download size={18} />
              Export
            </button>
          </div>
        </section>

        <section className="panel results" aria-label="Available datasets">
          <div className="panelHeader">
            <Database size={18} />
            <h2>Datasets</h2>
          </div>
          <div className="datasetTable">
            <div className="tableHeader">
              <span>Stream</span>
              <span>Run</span>
              <span>Sites</span>
              <span>Status</span>
            </div>
            {datasets.map((dataset) => (
              <div className="tableRow" key={`${dataset.stream}-${dataset.run_date}-${dataset.run_type}-${dataset.cycle}`}>
                <span>{dataset.stream}</span>
                <span>{dataset.run_date} {dataset.run_type} {dataset.cycle}</span>
                <span>{dataset.site_ids.length}</span>
                <span className={`dot ${dataset.export_available ? "good" : "warn"}`}>
                  {dataset.export_available ? "cached" : dataset.schema_status}
                </span>
              </div>
            ))}
          </div>

          <div className="inspection">
            <h3>Schema Inspection</h3>
            <p className={`schemaStatus ${statusTone(schema.status)}`}>{schema.status}</p>
            {(schema.errors || []).slice(0, 4).map((item) => (
              <p className="schemaError" key={item}>{item}</p>
            ))}
          </div>

          <div className="preview">
            <h3>Export Preview</h3>
            {preview ? (
              <>
                <p className={preview.available ? "ready" : "blocked"}>
                  {preview.available
                    ? `${preview.row_count} rows across ${preview.record_count} cached files`
                    : preview.reasons.join("; ")}
                </p>
                <p>{preview.format?.toUpperCase()}</p>
              </>
            ) : (
              <p>No preview requested.</p>
            )}
            {exportResult && (
              <a className="downloadLink" href={`/api/exports/${exportResult.id}`}>
                Download {exportResult.id}
              </a>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}

function StatusChip({ icon, label, value, tone }) {
  return (
    <div className={`statusChip ${tone}`}>
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
