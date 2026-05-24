"""HTTP-эндпоинты модуля documents."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.core.database import get_session
from backend.modules.documents import service
from backend.modules.documents.schemas import DocumentResponse


router = APIRouter()


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(db: Session = Depends(get_session)) -> list:
    """Список всех документов в библиотеке."""
    return service.list_documents(db)
