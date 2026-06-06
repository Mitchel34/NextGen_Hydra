"""FastAPI app for read-only access to approved cached artifacts."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .artifacts import (
    ArtifactError,
    create_export,
    export_path,
    list_datasets,
    load_sites,
    preview_export,
    project_root,
    schema_inspection,
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


@app.get("/api/datasets")
def api_datasets() -> dict[str, object]:
    return {"datasets": list_datasets(project_root())}


@app.get("/api/schema-inspection")
def api_schema_inspection() -> dict[str, object]:
    return schema_inspection(project_root())


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


@app.get("/api/exports/{export_id}")
def api_get_export(export_id: str) -> FileResponse:
    try:
        path = export_path(export_id, project_root())
    except ArtifactError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path)
