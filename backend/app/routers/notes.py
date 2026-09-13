"""笔记 CRUD。"""

from fastapi import APIRouter, Depends, HTTPException

from ..database import store
from ..database.kite.kite_memory import UserMemory
from .schemas import CitingNoteOut, Note, NoteCreateIn, NoteIn, NoteLinksOut, RevisionFullOut, RevisionOut, SkeletonSaveIn
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


@router.get("/trash")
def list_trash(user: str = Depends(current_user)) -> list[dict]:
    """最近删除：30 天内删掉的笔记（连同子树里的每一篇），可恢复、可彻底删。"""
    return store.list_trash(user)


@router.post("/trash/{note_id}/restore", response_model=Note)
def restore_trash(note_id: str, user: str = Depends(current_user)):
    n = store.restore_from_trash(user, note_id)
    if not n:
        raise HTTPException(404, "最近删除里没有这篇")
    return n


@router.delete("/trash/{note_id}")
def purge_trash(note_id: str, user: str = Depends(current_user)) -> dict:
    if not store.purge_trash(user, note_id):
        raise HTTPException(404, "最近删除里没有这篇")
    return {"ok": True}


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


@router.get("/{note_id}/revisions", response_model=list[RevisionOut])
def list_revisions(note_id: str, user: str = Depends(current_user)):
    if not store.get_note(user, note_id):
        raise HTTPException(404, "note not found")
    return store.list_revisions(user, note_id)


@router.post("/{note_id}/revisions", response_model=RevisionOut)
def snapshot_note(note_id: str, user: str = Depends(current_user)):
    """手动存一版。正文为空时 409——空版本没有意义。"""
    if not store.get_note(user, note_id):
        raise HTTPException(404, "note not found")
    r = store.snapshot_note(user, note_id)
    if not r:
        raise HTTPException(409, "正文是空的，没什么可存")
    return r


@router.get("/{note_id}/revisions/{rev_id}", response_model=RevisionFullOut)
def get_revision(note_id: str, rev_id: str, user: str = Depends(current_user)):
    r = store.get_revision(user, note_id, rev_id)
    if not r:
        raise HTTPException(404, "revision not found")
    r["chars"] = len(r["content"])
    return r


@router.post("/{note_id}/revisions/{rev_id}/restore", response_model=Note)
def restore_revision(note_id: str, rev_id: str, user: str = Depends(current_user)):
    n = store.restore_revision(user, note_id, rev_id)
    if not n:
        raise HTTPException(404, "revision not found")
    return n


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


@router.get("/{note_id}/kb")
def note_kb(note_id: str, user: str = Depends(current_user)) -> dict:
    """这篇笔记跟知识库的关系：贡献了哪些事实、上次摄入是什么时候、正文之后改过没
    （stale = 改过，知识库里还是旧版）。"""
    n = store.get_note(user, note_id)
    if not n:
        raise HTTPException(404, "note not found")
    ingested_at = n.get("ingested_at") or ""
    updated_at = n.get("updated_at") or ""
    facts = UserMemory(user).facts_for_prefix(UserMemory.note_prefix(note_id)) if ingested_at else []
    return {
        "note_id": note_id,
        "ingested_at": ingested_at,
        "updated_at": updated_at,
        # ISO UTC 字符串按字典序就是时间序
        "stale": bool(ingested_at) and updated_at > ingested_at,
        "facts": facts,
        "manual_session": f"note-{note_id}-manual",
    }
