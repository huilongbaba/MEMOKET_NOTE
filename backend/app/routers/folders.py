"""文件夹 CRUD——单层，不支持嵌套子文件夹。"""

from fastapi import APIRouter, Depends, HTTPException

from .. import store
from ..schemas import Folder, FolderIn
from .deps import current_user

router = APIRouter(prefix="/api/folders", tags=["folders"])


@router.get("", response_model=list[Folder])
def list_folders(user: str = Depends(current_user)):
    return store.list_folders(user)


@router.post("", response_model=Folder)
def create_folder(body: FolderIn, user: str = Depends(current_user)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "folder name required")
    return store.create_folder(user, name)


@router.put("/{folder_id}", response_model=Folder)
def rename_folder(folder_id: str, body: FolderIn, user: str = Depends(current_user)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "folder name required")
    folder = store.rename_folder(user, folder_id, name)
    if not folder:
        raise HTTPException(404, "folder not found")
    return folder


@router.delete("/{folder_id}")
def delete_folder(folder_id: str, user: str = Depends(current_user)):
    if not store.delete_folder(user, folder_id):
        raise HTTPException(404, "folder not found")
    return {"deleted": folder_id}
