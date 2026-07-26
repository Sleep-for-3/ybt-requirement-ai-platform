from fastapi import APIRouter,Depends,File,HTTPException,UploadFile
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import DataSource,MetadataImportDocument
from app.schemas import MetadataImportApplyResponse,MetadataImportRead
from app.services.metadata.excel_import import apply_metadata_excel,ingest_metadata_excel

router=APIRouter(tags=["metadata imports"])
@router.post("/datasources/{datasource_id}/metadata-import/upload",response_model=MetadataImportRead)
async def upload(datasource_id:int,file:UploadFile=File(...),db:Session=Depends(get_db)):
    ds=db.get(DataSource,datasource_id)
    if ds is None:raise HTTPException(404,"Data source not found")
    try:return await ingest_metadata_excel(db,ds,file)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
@router.get("/metadata-imports/{document_id}/preview",response_model=MetadataImportRead)
def preview(document_id:int,db:Session=Depends(get_db)):
    item=db.get(MetadataImportDocument,document_id)
    if item is None:raise HTTPException(404,"Metadata import not found")
    return item
@router.post("/metadata-imports/{document_id}/apply",response_model=MetadataImportApplyResponse)
def apply(document_id:int,db:Session=Depends(get_db)):
    item=db.get(MetadataImportDocument,document_id)
    if item is None:raise HTTPException(404,"Metadata import not found")
    return MetadataImportApplyResponse(**apply_metadata_excel(db,item))
