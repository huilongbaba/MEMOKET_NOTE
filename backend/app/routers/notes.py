"""笔记 CRUD。"""

from fastapi import APIRouter, Depends, HTTPException

from ..database import store
from ..schemas import Note, NoteFolderIn, NoteIn, SkeletonSaveIn
from .deps import current_user

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("", response_model=list[Note])
def list_notes(q: str = "", user: str = Depends(current_user)):
    return store.list_notes(user, q)


@router.post("", response_model=Note)
def create_note(body: NoteIn, user: str = Depends(current_user)):
    return store.create_note(user, body.title, body.content, body.folder_id)


@router.get("/{note_id}", response_model=Note)
def get_note(note_id: str, user: str = Depends(current_user)):
    note = store.get_note(user, note_id)
    if not note:
        raise HTTPException(404, "note not found")
    return note


@router.put("/{note_id}", response_model=Note)
def update_note(note_id: str, body: NoteIn, user: str = Depends(current_user)):
    note = store.update_note(user, note_id, body.title, body.content)
    if not note:
        raise HTTPException(404, "note not found")
    return note


@router.put("/{note_id}/skeleton", response_model=Note)
def save_skeleton(note_id: str, body: SkeletonSaveIn, user: str = Depends(current_user)):
    """保存写作骨架。骨架是**这一篇**的东西，harness 每轮都拿它当主线依据。

    之前它只活在前端内存里：换一篇笔记、刷新页面、甚至无限续写开着「跟随」
    自动切到下一段，骨架就没了——用户看到的就是「一会儿就不见了」，而下次跑
    harness 还得重新花一次模型调用生成一份。
    """
    if not store.get_note(user, note_id):
        raise HTTPException(404, "note not found")
    store.set_skeleton(user, note_id, body.spine.strip(),
                       [b for b in (x.strip() for x in body.beats) if b])
    return store.get_note(user, note_id)


@router.delete("/{note_id}")
def delete_note(note_id: str, user: str = Depends(current_user)):
    if not store.delete_note(user, note_id):
        raise HTTPException(404, "note not found")
    return {"deleted": note_id}


@router.post("/{note_id}/pin", response_model=Note)
def pin_note(note_id: str, user: str = Depends(current_user)):
    note = store.get_note(user, note_id)
    if not note:
        raise HTTPException(404, "note not found")
    updated = store.set_pinned(user, note_id, not note["pinned"])
    if not updated:
        raise HTTPException(404, "note not found")
    return updated


@router.put("/{note_id}/folder", response_model=Note)
def move_note(note_id: str, body: NoteFolderIn, user: str = Depends(current_user)):
    updated = store.set_note_folder(user, note_id, body.folder_id)
    if not updated:
        raise HTTPException(404, "note not found")
    return updated
