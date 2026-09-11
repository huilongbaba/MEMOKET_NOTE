"""笔记 CRUD。"""

from fastapi import APIRouter, Depends, HTTPException

from ..database import store
from .schemas import CitingNoteOut, Note, NoteCreateIn, NoteIn, NoteLinksOut, SkeletonSaveIn
from .deps import current_user

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("", response_model=list[Note])
def list_notes(q: str = "", user: str = Depends(current_user)):
    return store.list_notes(user, q)


@router.post("", response_model=Note)
def create_note(body: NoteCreateIn, user: str = Depends(current_user)):
    """新建笔记，**同时挂到树上**。

    「新建文件夹」不是单独的操作——在 Trilium 的模型里文件夹不是一种东西，
    有子节点的笔记就是文件夹。所以建一个空笔记再往里面建东西，那个空笔记
    自然就成了文件夹。
    """
    return store.create_note(user, body.title, body.content, body.parent_note_id)


@router.get("/{note_id}", response_model=Note)
def get_note(note_id: str, user: str = Depends(current_user)):
    note = store.get_note(user, note_id)
    if not note:
        raise HTTPException(404, "note not found")
    return note


@router.get("/{note_id}/links", response_model=NoteLinksOut)
def note_links(note_id: str, user: str = Depends(current_user)):
    """这篇链出去的 + 链进来的（Trilium 的 note links / referenced by）。"""
    note = store.get_note(user, note_id)
    if not note:
        raise HTTPException(404, "note not found")
    outgoing = []
    for target in store.note_links_in(note["content"]):
        t = store.get_note(user, target)
        if t:
            outgoing.append(CitingNoteOut(id=t["id"], title=t["title"], updated_at=t["updated_at"],
                                          preview=(t["content"] or "")[:80]))
    return NoteLinksOut(outgoing=outgoing, backlinks=[CitingNoteOut(**r) for r in store.backlinks(user, note_id)])


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
    """删一篇笔记**以及它的整棵子树**。

    子树必须一起删：只删自己的话，孩子们的 branch 指向一个不存在的父节点，
    它们既不在树根也不在任何看得见的地方——是一批用户再也找不到、却还在库里
    占着的笔记。克隆是例外，在别处还长着的孩子只摘掉这条边。
    """
    removed = store.delete_note(user, note_id)
    if not removed:
        raise HTTPException(404, "note not found")
    return {"deleted": removed}


@router.post("/{note_id}/pin", response_model=Note)
def pin_note(note_id: str, user: str = Depends(current_user)):
    note = store.get_note(user, note_id)
    if not note:
        raise HTTPException(404, "note not found")
    updated = store.set_pinned(user, note_id, not note["pinned"])
    if not updated:
        raise HTTPException(404, "note not found")
    return updated
