"""HTTP-эндпоинты модуля documents."""

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.documents import service
from backend.modules.documents.schemas import DocumentResponse, UploadResponse


router = APIRouter()


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(db: Session = Depends(get_session)) -> list:
    """Список всех документов в библиотеке."""
    return service.list_documents(db)


@router.post("/documents", response_model=UploadResponse)
def upload_documents(
    request: Request,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_session),
) -> UploadResponse:
    """Принимает пачку PDF, новые ставит в очередь на обработку."""
    # Executor создан в lifespan приложения (backend/app.py)
    executor = request.app.state.executor
    items = service.create_documents_from_uploads(files, db, executor)
    return UploadResponse(items=items)
