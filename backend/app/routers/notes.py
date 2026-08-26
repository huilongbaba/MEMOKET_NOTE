"""笔记 CRUD。"""

from fastapi import APIRouter, Depends, HTTPException

from .. import store
from ..schemas import Note, NoteIn
from .deps import current_user

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("", response_model=list[Note])
def list_notes(user: str = Depends(current_user)):
    return store.list_notes(user)


@router.post("", response_model=Note)
def create_note(body: NoteIn, user: str = Depends(current_user)):
    return store.create_note(user, body.title, body.content)


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


@router.delete("/{note_id}")
def delete_note(note_id: str, user: str = Depends(current_user)):
    if not store.delete_note(user, note_id):
        raise HTTPException(404, "note not found")
    return {"deleted": note_id}
