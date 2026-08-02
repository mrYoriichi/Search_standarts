"""HTTP endpoints of the settings module."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.settings import service
from backend.modules.settings.schemas import (
    AnswerLanguageSetting,
    DescribeImagesSetting,
    LibraryPathRequest,
    LibraryPathResponse,
    LibraryPathsResponse,
    LibraryPathUpdate,
    OpenAIKeyRequest,
    OpenAIKeyStatus,
    UiLanguageSetting,
    VisionModelSetting,
)


router = APIRouter()


@router.get("/settings/library", response_model=LibraryPathResponse)
def get_library_path(db: Session = Depends(get_session)) -> LibraryPathResponse:
    """Current library folder path. None — not set."""
    return LibraryPathResponse(path=service.get_library_path(db))


@router.put("/settings/library", response_model=LibraryPathResponse)
def set_library_path(
    body: LibraryPathRequest,
    db: Session = Depends(get_session),
) -> LibraryPathResponse:
    """Store the library folder path; validates that the folder exists."""
    try:
        saved = service.set_library_path(db, body.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LibraryPathResponse(path=saved)


@router.get("/settings/libraries", response_model=LibraryPathsResponse)
def get_library_paths(db: Session = Depends(get_session)) -> LibraryPathsResponse:
    """Library folder list (migrates from the old single path)."""
    return LibraryPathsResponse(paths=service.get_library_paths(db))


@router.post("/settings/libraries", response_model=LibraryPathsResponse)
def add_library_path(
    body: LibraryPathRequest,
    db: Session = Depends(get_session),
) -> LibraryPathsResponse:
    """Add a folder to the library list. 400 when absent on disk."""
    try:
        paths = service.add_library_path(db, body.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LibraryPathsResponse(paths=paths)


@router.put("/settings/libraries", response_model=LibraryPathsResponse)
def update_library_path(
    body: LibraryPathUpdate,
    db: Session = Depends(get_session),
) -> LibraryPathsResponse:
    """Edit a folder path in the list. 400 when the new folder is absent."""
    try:
        paths = service.update_library_path(db, body.old_path, body.new_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LibraryPathsResponse(paths=paths)


@router.delete("/settings/libraries", response_model=LibraryPathsResponse)
def remove_library_path(
    body: LibraryPathRequest,
    db: Session = Depends(get_session),
) -> LibraryPathsResponse:
    """Remove a folder from the library list. Indexes on disk stay."""
    paths = service.remove_library_path(db, body.path)
    return LibraryPathsResponse(paths=paths)


@router.get("/settings/projects-libraries", response_model=LibraryPathsResponse)
def get_projects_paths(db: Session = Depends(get_session)) -> LibraryPathsResponse:
    """Archive folder list (migrates from the old single path)."""
    return LibraryPathsResponse(paths=service.get_projects_paths(db))


@router.post("/settings/projects-libraries", response_model=LibraryPathsResponse)
def add_projects_path(
    body: LibraryPathRequest,
    db: Session = Depends(get_session),
) -> LibraryPathsResponse:
    """Add a folder to the archive list. 400 when absent on disk."""
    try:
        paths = service.add_projects_path(db, body.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LibraryPathsResponse(paths=paths)


@router.put("/settings/projects-libraries", response_model=LibraryPathsResponse)
def update_projects_path(
    body: LibraryPathUpdate,
    db: Session = Depends(get_session),
) -> LibraryPathsResponse:
    """Edit an archive folder path. 400 when the new folder is absent."""
    try:
        paths = service.update_projects_path(db, body.old_path, body.new_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LibraryPathsResponse(paths=paths)


@router.delete("/settings/projects-libraries", response_model=LibraryPathsResponse)
def remove_projects_path(
    body: LibraryPathRequest,
    db: Session = Depends(get_session),
) -> LibraryPathsResponse:
    """Remove a folder from the archive list. Indexes on disk stay."""
    paths = service.remove_projects_path(db, body.path)
    return LibraryPathsResponse(paths=paths)


@router.get("/settings/vision-model", response_model=VisionModelSetting)
def get_vision_model(db: Session = Depends(get_session)) -> VisionModelSetting:
    """Current vision model for document processing."""
    return VisionModelSetting(model=service.get_vision_model(db))


@router.put("/settings/vision-model", response_model=VisionModelSetting)
def set_vision_model(
    body: VisionModelSetting,
    db: Session = Depends(get_session),
) -> VisionModelSetting:
    """Store the vision-model choice. 400 on an unknown model."""
    try:
        saved = service.set_vision_model(db, body.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return VisionModelSetting(model=saved)


@router.get("/settings/describe-images", response_model=DescribeImagesSetting)
def get_describe_images(db: Session = Depends(get_session)) -> DescribeImagesSetting:
    """Is vision enabled during processing (image descriptions)?"""
    return DescribeImagesSetting(enabled=service.get_describe_images(db))


@router.put("/settings/describe-images", response_model=DescribeImagesSetting)
def set_describe_images(
    body: DescribeImagesSetting,
    db: Session = Depends(get_session),
) -> DescribeImagesSetting:
    """Store the description toggle. OFF = "No LLM" mode (free)."""
    saved = service.set_describe_images(db, body.enabled)
    return DescribeImagesSetting(enabled=saved)


@router.get("/settings/openai-key", response_model=OpenAIKeyStatus)
def get_openai_key(db: Session = Depends(get_session)) -> OpenAIKeyStatus:
    """OpenAI key status: whether set, plus the masked tail."""
    key = service.get_openai_key(db)
    return OpenAIKeyStatus(
        is_set=bool(key),
        masked=service.mask_key(key) if key else None,
    )


@router.put("/settings/openai-key", response_model=OpenAIKeyStatus)
def set_openai_key(
    body: OpenAIKeyRequest,
    db: Session = Depends(get_session),
) -> OpenAIKeyStatus:
    """Store the OpenAI key: format check, DB and environment."""
    try:
        saved = service.set_openai_key(db, body.key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OpenAIKeyStatus(is_set=True, masked=service.mask_key(saved))


@router.get("/settings/language", response_model=UiLanguageSetting)
def get_ui_language(db: Session = Depends(get_session)) -> UiLanguageSetting:
    """Current interface language (used for backend error texts)."""
    return UiLanguageSetting(language=service.get_ui_language(db))


@router.put("/settings/language", response_model=UiLanguageSetting)
def set_ui_language(
    body: UiLanguageSetting,
    db: Session = Depends(get_session),
) -> UiLanguageSetting:
    """Store the interface language; the Literal schema rejects junk."""
    return UiLanguageSetting(language=service.set_ui_language(db, body.language))


@router.get("/settings/answer-language", response_model=AnswerLanguageSetting)
def get_answer_language(db: Session = Depends(get_session)) -> AnswerLanguageSetting:
    """Current LLM answer language."""
    return AnswerLanguageSetting(language=service.get_answer_language(db))


@router.put("/settings/answer-language", response_model=AnswerLanguageSetting)
def set_answer_language(
    body: AnswerLanguageSetting,
    db: Session = Depends(get_session),
) -> AnswerLanguageSetting:
    """Store the answer language; the Literal schema rejects junk."""
    return AnswerLanguageSetting(
        language=service.set_answer_language(db, body.language)
    )
