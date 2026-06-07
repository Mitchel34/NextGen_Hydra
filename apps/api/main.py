"""FastAPI app for read-only access to approved cached artifacts."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi import Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .artifacts import (
    ArtifactError,
    artifact_catalog,
    create_acquisition_request,
    create_export,
    export_path,
    export_options,
    list_datasets,
    load_sites,
    preview_export,
    project_root,
    public_status,
    quality_report,
    schema_inspection,
    site_directory,
    site_directory_detail,
    streamflow_units_status,
)


app = FastAPI(
    title="NextGen Hydra Public API",
    version="0.1.0",
    description="Read-only API for CLI-approved NextGen Hydra artifacts.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/sites")
def api_sites() -> dict[str, object]:
    return {"sites": load_sites(project_root())}


@app.get("/api/site-directory")
def api_site_directory(
    query: str | None = None,
    source: str | None = None,
    limit: int = Query(default=50, ge=1, le=250),
) -> dict[str, object]:
    try:
        return site_directory(project_root(), query=query, source=source, limit=limit)
    except ArtifactError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/site-directory/{identifier}")
def api_site_directory_detail(identifier: str) -> dict[str, object]:
    try:
        return site_directory_detail(identifier, project_root())
    except ArtifactError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/status")
def api_status() -> dict[str, object]:
    return public_status(project_root())


@app.get("/api/datasets")
def api_datasets() -> dict[str, object]:
    return {"datasets": list_datasets(project_root())}


@app.get("/api/catalog")
def api_catalog() -> dict[str, object]:
    return artifact_catalog(project_root())


@app.get("/api/schema-inspection")
def api_schema_inspection() -> dict[str, object]:
    return schema_inspection(project_root())


@app.get("/api/qc")
def api_qc() -> dict[str, object]:
    return quality_report(project_root())


@app.get("/api/units")
def api_units() -> dict[str, object]:
    return streamflow_units_status(project_root())


@app.get("/api/export-options")
def api_export_options() -> dict[str, object]:
    return export_options(project_root())


@app.post("/api/exports/preview")
def api_export_preview(payload: dict[str, object]) -> dict[str, object]:
    try:
        return preview_export(payload, project_root())
    except ArtifactError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/exports")
def api_create_export(payload: dict[str, object]) -> dict[str, object]:
    try:
        return create_export(payload, project_root())
    except ArtifactError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/acquisition-requests")
def api_create_acquisition_request(payload: dict[str, object]) -> dict[str, object]:
    try:
        return create_acquisition_request(payload, project_root())
    except ArtifactError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/exports/{export_id}")
def api_get_export(export_id: str) -> FileResponse:
    try:
        path = export_path(export_id, project_root())
    except ArtifactError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path)
