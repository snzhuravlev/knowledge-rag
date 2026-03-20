from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.dependencies import get_state, require_admin, require_reader
from app.schemas import SourceOut, SourceUpdate, User
from app.state import AppState

router = APIRouter(prefix="/api", tags=["sources"])


async def _save_upload(file: UploadFile, destination: Path, max_bytes: int) -> int:
    written = 0
    with destination.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                out.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Uploaded file is too large.")
            out.write(chunk)
    await file.close()
    return written


@router.post("/sources", response_model=SourceOut)
async def create_source(
    title: str,
    file: UploadFile = File(...),
    _: User = Depends(require_admin),
    state: AppState = Depends(get_state),
) -> SourceOut:
    safe_name = file.filename or "uploaded"
    dest_path = state.settings.upload_dir / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{safe_name}"
    await _save_upload(file, dest_path, state.settings.upload_max_bytes)
    file_format = dest_path.suffix.lower().lstrip(".") or "txt"
    row = await state.source_repo.create(title, str(dest_path), safe_name, file_format)
    await state.indexing_service.enqueue(row["id"])
    return SourceOut(
        id=row["id"],
        title=row["title"],
        original_name=row["original_name"],
        format=row["format"],
        status=row["status"],
    )


@router.get("/sources", response_model=List[SourceOut])
async def list_sources(
    _: User = Depends(require_reader),
    state: AppState = Depends(get_state),
) -> List[SourceOut]:
    rows = await state.source_repo.list_all()
    return [
        SourceOut(
            id=row["id"],
            title=row["title"],
            original_name=row["original_name"],
            format=row["format"],
            status=row["status"],
        )
        for row in rows
    ]


@router.patch("/sources/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: int,
    payload: SourceUpdate,
    _: User = Depends(require_admin),
    state: AppState = Depends(get_state),
) -> SourceOut:
    row = await state.source_repo.find_basic(source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found")
    new_title = payload.title if payload.title is not None else row["title"]
    row = await state.source_repo.update_title(source_id, new_title)
    return SourceOut(
        id=row["id"],
        title=row["title"],
        original_name=row["original_name"],
        format=row["format"],
        status=row["status"],
    )


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: int,
    _: User = Depends(require_admin),
    state: AppState = Depends(get_state),
) -> dict:
    src = await state.source_repo.get_file_path(source_id)
    await state.chunk_repo.delete_by_source_id(source_id)
    await state.source_repo.delete(source_id)
    if src and src["file_path"]:
        Path(src["file_path"]).unlink(missing_ok=True)
    return {"status": "ok"}
