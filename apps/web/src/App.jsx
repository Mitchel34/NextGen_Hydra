import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  Download,
  FileSearch,
  Filter,
  RefreshCw,
  Search,
  Send,
  ShieldCheck
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
  if (["pass", "resolved", "documented", "available", "ready"].includes(status)) return "good";
  if (status === "missing") return "muted";
  return "warn";
}

export default function App() {
  const mapElementRef = useRef(null);
  const leafletMapRef = useRef(null);
  const markerLayerRef = useRef(null);
  const [sites, setSites] = useState([]);
  const [datasets, setDatasets] = useState([]);
  const [status, setStatus] = useState({ status: "loading" });
  const [qc, setQc] = useState({ status: "loading", per_site: {} });
  const [units, setUnits] = useState({ status: "loading", evidence: [] });
  const [exportOptions, setExportOptions] = useState({ columns: [], preprocessing: {} });
  const [schema, setSchema] = useState({ status: "loading", errors: [] });
  const [directory, setDirectory] = useState({ sites: [], supported_sources: [] });
  const [mapSummary, setMapSummary] = useState({ record_count: 0, map_ready_record_count: 0, vpu_counts: {} });
  const [mapResult, setMapResult] = useState({ count: 0, total_matching_map_ready_count: 0, features: [] });
  const [mapFilters, setMapFilters] = useState({ query: "", vpu: "", source: "", state: "", huc: "" });
  const [selectedMapSite, setSelectedMapSite] = useState(null);
  const [siteQuery, setSiteQuery] = useState("");
  const [directorySource, setDirectorySource] = useState("");
  const [selectedDirectoryIds, setSelectedDirectoryIds] = useState(new Set());
  const [requestSources, setRequestSources] = useState(new Set(["nextgen"]));
  const [requestedComids, setRequestedComids] = useState("");
  const [requestedGages, setRequestedGages] = useState("");
  const [selectedSites, setSelectedSites] = useState(new Set());
  const [selectedStreams, setSelectedStreams] = useState(new Set());
  const [selectedColumns, setSelectedColumns] = useState(new Set());
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [format, setFormat] = useState("csv");
  const [missingStreamflow, setMissingStreamflow] = useState("keep");
  const [aggregation, setAggregation] = useState("none");
  const [preview, setPreview] = useState(null);
  const [exportResult, setExportResult] = useState(null);
  const [acquisitionResult, setAcquisitionResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const streamOptions = useMemo(
    () => Array.from(new Set(datasets.map((dataset) => dataset.stream))).sort(),
    [datasets]
  );
  const tidyReady = datasets.some((dataset) => dataset.tidy_available);
  const exportReady = datasets.some((dataset) => dataset.export_available);

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (!mapElementRef.current || leafletMapRef.current) return;
    const map = L.map(mapElementRef.current, {
      preferCanvas: true,
      scrollWheelZoom: false
    }).setView([39.5, -96], 4);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 12,
      attribution: "&copy; OpenStreetMap contributors"
    }).addTo(map);
    leafletMapRef.current = map;
    markerLayerRef.current = L.layerGroup().addTo(map);
    return () => {
      map.remove();
      leafletMapRef.current = null;
      markerLayerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = leafletMapRef.current;
    const layer = markerLayerRef.current;
    if (!map || !layer) return;
    layer.clearLayers();
    const bounds = [];
    for (const feature of mapResult.features || []) {
      const [longitude, latitude] = feature.geometry?.coordinates || [];
      if (latitude == null || longitude == null) continue;
      const properties = feature.properties || {};
      const marker = L.circleMarker([latitude, longitude], {
        radius: 5,
        color: "#24535d",
        weight: 1,
        fillColor: "#2f7f6f",
        fillOpacity: 0.72
      });
      marker.bindTooltip(properties.name || properties.usgs_gage_id || properties.site_id || "Paired site");
      marker.on("click", () => setSelectedMapSite(properties));
      marker.addTo(layer);
      bounds.push([latitude, longitude]);
    }
    if (bounds.length) {
      map.fitBounds(bounds, { padding: [24, 24], maxZoom: 8 });
    }
  }, [mapResult.features]);

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const [statusData, siteData, datasetData, schemaData, qcData, unitsData, optionsData, directoryData, mapSummaryData, mapData] = await Promise.all([
        fetchJson("/api/status"),
        fetchJson("/api/sites"),
        fetchJson("/api/datasets"),
        fetchJson("/api/schema-inspection"),
        fetchJson("/api/qc"),
        fetchJson("/api/units"),
        fetchJson("/api/export-options"),
        fetchJson("/api/site-directory?limit=10"),
        fetchJson("/api/site-map/summary"),
        fetchJson("/api/site-map?limit=25000")
      ]);
      setStatus(statusData || { status: "missing" });
      setSites(siteData.sites || []);
      setDatasets(datasetData.datasets || []);
      setSchema(schemaData || { status: "missing", errors: [] });
      setQc(qcData || { status: "missing", per_site: {} });
      setUnits(unitsData || { status: "missing", evidence: [] });
      setExportOptions(optionsData || { columns: [], preprocessing: {} });
      setDirectory(directoryData || { sites: [], supported_sources: [] });
      setMapSummary(mapSummaryData || { record_count: 0, map_ready_record_count: 0, vpu_counts: {} });
      setMapResult(mapData || { count: 0, total_matching_map_ready_count: 0, features: [] });
      setSelectedSites(new Set((siteData.sites || []).map((site) => site.site_id)));
      setSelectedStreams(new Set((datasetData.datasets || []).map((dataset) => dataset.stream)));
      setSelectedColumns(new Set((optionsData.columns || [])));
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

  function toggleColumn(column) {
    setSelectedColumns((current) => {
      const next = new Set(current);
      next.has(column) ? next.delete(column) : next.add(column);
      return next;
    });
  }

  function toggleDirectorySite(siteId) {
    setSelectedDirectoryIds((current) => {
      const next = new Set(current);
      next.has(siteId) ? next.delete(siteId) : next.add(siteId);
      return next;
    });
  }

  function toggleRequestSource(source) {
    setRequestSources((current) => {
      const next = new Set(current);
      next.has(source) ? next.delete(source) : next.add(source);
      return next;
    });
  }

  function payload() {
    return {
      site_ids: Array.from(selectedSites),
      streams: Array.from(selectedStreams),
      start_time_utc: startTime || null,
      end_time_utc: endTime || null,
      format,
      columns: Array.from(selectedColumns),
      preprocessing: {
        missing_streamflow: missingStreamflow,
        aggregation
      }
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

  async function searchDirectory() {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ limit: "25" });
      if (siteQuery) params.set("query", siteQuery);
      if (directorySource) params.set("source", directorySource);
      setDirectory(await fetchJson(`/api/site-directory?${params.toString()}`));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function searchMap() {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ limit: "25000" });
      for (const [key, value] of Object.entries(mapFilters)) {
        if (value) params.set(key, value);
      }
      setMapResult(await fetchJson(`/api/site-map?${params.toString()}`));
      setSelectedMapSite(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function updateMapFilter(key, value) {
    setMapFilters((current) => ({ ...current, [key]: value }));
  }

  function useMapSiteForRequest(site) {
    if (!site) return;
    if (site.site_id) {
      setSelectedDirectoryIds(new Set([site.site_id]));
    }
    setSiteQuery(site.usgs_gage_id || site.comid || site.name || "");
    setRequestedGages(site.usgs_gage_id || "");
    setRequestedComids(String(site.comid || (site.comid_candidates || [])[0] || ""));
    const sources = Object.entries(site.availability || {})
      .filter(([, available]) => available)
      .map(([source]) => source);
    if (sources.length) {
      setRequestSources(new Set(sources));
    }
  }

  async function requestAcquisition() {
    setLoading(true);
    setError("");
    setAcquisitionResult(null);
    try {
      const payload = {
        query: siteQuery || null,
        site_ids: Array.from(selectedDirectoryIds),
        comids: splitIdentifiers(requestedComids),
        usgs_gage_ids: splitIdentifiers(requestedGages),
        sources: Array.from(requestSources),
        streams: Array.from(selectedStreams),
        start_time_utc: startTime || null,
        end_time_utc: endTime || null,
        formats: [format],
        preprocessing: {
          missing_streamflow: missingStreamflow,
          aggregation
        }
      };
      setAcquisitionResult(
        await fetchJson("/api/acquisition-requests", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
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
          icon={<ShieldCheck size={16} />}
          label="Status"
          value={status.status}
          tone={status.status === "ready" ? "good" : "warn"}
        />
        <StatusChip
          icon={<FileSearch size={16} />}
          label="Schema"
          value={schema.status}
          tone={statusTone(schema.status)}
        />
        <StatusChip
          icon={tidyReady ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
          label="Tidy"
          value={tidyReady ? "ready" : "blocked"}
          tone={tidyReady ? "good" : "warn"}
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
            <legend>Find Sites</legend>
            <div className="searchRow">
              <input
                type="search"
                placeholder="COMID, USGS gage, name, or site ID"
                value={siteQuery}
                onChange={(event) => setSiteQuery(event.target.value)}
              />
              <button type="button" onClick={searchDirectory} disabled={loading} title="Search site directory">
                <Search size={18} />
              </button>
            </div>
            <div className="sourceGrid">
              {["nextgen", "nwm", "era5", "usgs"].map((source) => (
                <label key={source} className="miniCheck">
                  <input
                    type="checkbox"
                    checked={requestSources.has(source)}
                    onChange={() => toggleRequestSource(source)}
                  />
                  <span>{source.toUpperCase()}</span>
                </label>
              ))}
            </div>
            <div className="segmented compact">
              {["", "nextgen", "nwm", "era5", "usgs"].map((source) => (
                <button
                  key={source || "all"}
                  className={directorySource === source ? "selected" : ""}
                  onClick={() => setDirectorySource(source)}
                  type="button"
                >
                  {source ? source.toUpperCase() : "ALL"}
                </button>
              ))}
            </div>
            <div className="directoryList">
              {(directory.sites || []).map((site) => (
                <button
                  type="button"
                  key={`${site.site_id}-${site.comid}`}
                  className={selectedDirectoryIds.has(site.site_id) ? "directoryItem selected" : "directoryItem"}
                  onClick={() => toggleDirectorySite(site.site_id)}
                >
                  <span>
                    <strong>{site.usgs_gage_id || site.comid || site.site_id}</strong>
                    {site.name || "Unnamed site"}
                  </span>
                  <small>COMID {site.comid || "unknown"} VPU {site.vpu_id || "unknown"}</small>
                </button>
              ))}
            </div>
            <div className="manualGrid">
              <label>
                COMIDs
                <input value={requestedComids} onChange={(event) => setRequestedComids(event.target.value)} placeholder="comma separated" />
              </label>
              <label>
                USGS Gages
                <input value={requestedGages} onChange={(event) => setRequestedGages(event.target.value)} placeholder="comma separated" />
              </label>
            </div>
            <button className="requestButton" type="button" onClick={requestAcquisition} disabled={loading || requestSources.size === 0}>
              <Send size={18} />
              Submit Acquisition Request
            </button>
            {acquisitionResult && (
              <p className="requestStatus">
                {acquisitionResult.status}: {acquisitionResult.id}
              </p>
            )}
            <div className="mapSummary">
              <strong>{mapSummary.map_ready_record_count || 0}</strong>
              <span>map-ready paired sites across {Object.keys(mapSummary.vpu_counts || {}).length} VPUs</span>
            </div>
          </fieldset>

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

          <fieldset>
            <legend>Clean</legend>
            <div className="segmented">
              {["keep", "drop"].map((value) => (
                <button
                  key={value}
                  className={missingStreamflow === value ? "selected" : ""}
                  onClick={() => setMissingStreamflow(value)}
                  type="button"
                >
                  {value === "keep" ? "Keep Missing" : "Drop Missing"}
                </button>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend>Aggregate</legend>
            <div className="segmented">
              {["none", "daily_mean"].map((value) => (
                <button
                  key={value}
                  className={aggregation === value ? "selected" : ""}
                  onClick={() => setAggregation(value)}
                  type="button"
                >
                  {value === "none" ? "Hourly" : "Daily Mean"}
                </button>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend>Columns</legend>
            <div className="columnGrid">
              {(exportOptions.columns || []).map((column) => (
                <label key={column} className="miniCheck">
                  <input
                    type="checkbox"
                    checked={selectedColumns.has(column)}
                    onChange={() => toggleColumn(column)}
                  />
                  <span>{column}</span>
                </label>
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
          <div className="mapPanel" aria-label="National paired-site map">
            <div className="mapToolbar">
              <input
                type="search"
                placeholder="Search gage, COMID, name, HUC"
                value={mapFilters.query}
                onChange={(event) => updateMapFilter("query", event.target.value)}
              />
              <input
                value={mapFilters.vpu}
                onChange={(event) => updateMapFilter("vpu", event.target.value)}
                placeholder="VPU"
              />
              <select value={mapFilters.source} onChange={(event) => updateMapFilter("source", event.target.value)}>
                {["", "nextgen", "nwm", "era5", "usgs"].map((source) => (
                  <option key={source || "all"} value={source}>
                    {source ? source.toUpperCase() : "All sources"}
                  </option>
                ))}
              </select>
              <input
                value={mapFilters.state}
                onChange={(event) => updateMapFilter("state", event.target.value)}
                placeholder="State"
              />
              <input
                value={mapFilters.huc}
                onChange={(event) => updateMapFilter("huc", event.target.value)}
                placeholder="HUC"
              />
              <button type="button" onClick={searchMap} disabled={loading} title="Filter map">
                <Search size={18} />
              </button>
            </div>
            <div className="mapMeta">
              <strong>{mapResult.count || 0}</strong>
              <span>shown of {mapResult.total_matching_map_ready_count || 0} matching map-ready sites</span>
              <span>{mapSummary.map_ready_record_count || 0} national map-ready pairs</span>
            </div>
            <div ref={mapElementRef} className="mapCanvas" />
            {selectedMapSite && (
              <div className="mapDetails">
                <div>
                  <strong>{selectedMapSite.name || selectedMapSite.usgs_gage_id}</strong>
                  <span>USGS {selectedMapSite.usgs_gage_id || "unknown"} | VPU {selectedMapSite.vpu_id || "unknown"}</span>
                  <span>t-route {selectedMapSite.troute_feature_id || "unknown"} | COMID {selectedMapSite.comid || "candidate set"}</span>
                  <span>{selectedMapSite.comid_status || "unknown"}: {(selectedMapSite.comid_candidates || []).slice(0, 5).join(", ") || "no candidates"}</span>
                </div>
                <div className="sourcePills">
                  {Object.entries(selectedMapSite.availability || {}).map(([source, available]) => (
                    <span key={source} className={available ? "ready" : "blocked"}>{source.toUpperCase()}</span>
                  ))}
                </div>
                <button type="button" onClick={() => useMapSiteForRequest(selectedMapSite)}>
                  <Send size={16} />
                  Use for request
                </button>
              </div>
            )}
          </div>
          <div className="datasetTable">
            <div className="tableHeader">
              <span>Stream</span>
              <span>Run</span>
              <span>Sites</span>
              <span>Gates</span>
              <span>Status</span>
            </div>
            {datasets.map((dataset) => (
              <div className="tableRow" key={`${dataset.stream}-${dataset.run_date}-${dataset.run_type}-${dataset.cycle}`}>
                <span>{dataset.stream}</span>
                <span>{dataset.run_date} {dataset.run_type} {dataset.cycle}</span>
                <span>{dataset.site_ids.length}</span>
                <span className="gateStack">
                  <small className={`dot ${statusTone(dataset.crosswalk_status)}`}>{dataset.crosswalk_status}</small>
                  <small className={`dot ${statusTone(dataset.units_status)}`}>units {dataset.units_status}</small>
                </span>
                <span className={`dot ${dataset.export_available ? "good" : "warn"}`}>
                  {dataset.export_available ? "cached" : dataset.tidy_available ? "tidy ready" : dataset.schema_status}
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

          <div className="inspection">
            <h3>Units Evidence</h3>
            <p className={`schemaStatus ${statusTone(units.status)}`}>
              {units.status} {units.units ? `- ${units.units}` : ""}
            </p>
            {(units.evidence || []).slice(0, 3).map((item) => (
              <p className="schemaError" key={`${item.source}-${item.citation}`}>
                {item.source}: {item.citation}
              </p>
            ))}
          </div>

          <div className="inspection">
            <h3>Site QC</h3>
            <div className="qcGrid">
              {sites.map((site) => {
                const siteQc = (qc.per_site || {})[site.site_id] || {};
                return (
                  <div className="qcItem" key={site.site_id}>
                    <strong>{site.usgs_gage_id}</strong>
                    <span>{siteQc.row_count || 0} rows</span>
                    <span>{siteQc.start_time_utc || "missing"} to {siteQc.end_time_utc || "missing"}</span>
                    <span>missing {siteQc.missing_streamflow_count || 0}, duplicate {siteQc.duplicate_timestamp_count || 0}</span>
                  </div>
                );
              })}
            </div>
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
                <p>{preview.preprocessing?.aggregation || "none"}; missing {preview.preprocessing?.missing_streamflow || "keep"}</p>
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

function splitIdentifiers(value) {
  return String(value || "")
    .split(/[,\s]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}
