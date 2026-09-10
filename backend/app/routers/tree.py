"""笔记树——照 Trilium 的模型。

**这里没有「文件夹」。** 任何有子节点的笔记就是文件夹，所以不需要一套单独
的文件夹 CRUD：新建文件夹 = 新建一篇笔记，重命名文件夹 = 改笔记标题，
删文件夹 = 删笔记（连同子树）。这个路由只管**树的形状**：谁挂在谁下面、
展开没有、克隆到哪儿。

操作的主语是 **branch**（哪篇笔记 · 在哪个父节点下），不是笔记：一篇笔记
可以同时长在好几个位置，说「移动这篇笔记」是没有指向的。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..database import store
from .deps import current_user
from .schemas import BranchAttachIn, BranchExpandIn, BranchMoveIn, BranchReorderIn, TreeRow

router = APIRouter(prefix="/api/tree", tags=["tree"])


@router.get("", response_model=list[TreeRow])
def get_tree(user: str = Depends(current_user)):
    """整棵树一次拿全。

    **不做成按需一层层拿。** 笔记在几千这个量级时一次查完是几毫秒的事；
    按层拿会让「展开一个节点」变成一次网络往返，树用起来一顿一顿的。
    """
    return store.tree(user)


@router.post("/branches", response_model=TreeRow)
def attach(body: BranchAttachIn, user: str = Depends(current_user)):
    """把一篇已有的笔记挂到某个父节点下 = **克隆**。

    克隆不是复制：两处是同一篇笔记，改一处处处都变。
    """
    if not store.get_note(user, body.note_id):
        raise HTTPException(404, "笔记不在")
    if body.parent_note_id != store.ROOT_ID and \
            not store.get_note(user, body.parent_note_id):
        raise HTTPException(404, "父节点不在")
    if body.note_id == body.parent_note_id:
        raise HTTPException(400, "不能把笔记挂到它自己下面")
    store.attach(user, body.note_id, body.parent_note_id)
    row = next((r for r in store.tree(user)
                if r["note_id"] == body.note_id
                and r["parent_note_id"] == body.parent_note_id), None)
    if not row:
        raise HTTPException(500, "挂上了却读不回来")
    return row


@router.delete("/branches")
def detach(note_id: str, parent_note_id: str, user: str = Depends(current_user)):
    """摘掉一条 branch——只是「不在这个位置显示了」，笔记本身还在别处。

    最后一条不给摘：摘掉之后它不在树上的任何位置，用户再也找不到而它还在
    库里占着。那不是删除，是丢失。要删笔记走 DELETE /api/notes/{id}。
    """
    if not store.detach(user, note_id, parent_note_id):
        raise HTTPException(
            400, "这是它在树上的最后一个位置了。要删掉这篇笔记，用删除笔记。")
    return {"detached": note_id, "from": parent_note_id}


@router.patch("/branches/reorder")
def reorder(body: BranchReorderIn, user: str = Depends(current_user)):
    """拖拽排序：一个父节点下的子节点按给定顺序重编号。"""
    return {"parent": body.parent_note_id,
            "count": store.reorder(user, body.parent_note_id, body.order)}


@router.patch("/branches/move")
def move(body: BranchMoveIn, user: str = Depends(current_user)):
    """把一条 branch 换个父节点。

    拒绝成环：树里一旦成环，任何一次深度遍历（渲染树、算路径、删子树）都会
    无限转下去，症状是界面直接卡死而不是报一个错。
    """
    ok = store.move_branch(user, body.note_id, body.from_parent_id,
                           body.to_parent_id, body.position)
    if not ok:
        raise HTTPException(400, "移不过去：目标在这棵笔记自己的子树里，会成环")
    return {"moved": body.note_id, "to": body.to_parent_id}


@router.patch("/branches/expanded")
def set_expanded(body: BranchExpandIn, user: str = Depends(current_user)):
    """展开状态存在库里，不在前端内存里——刷新一次就全收起来的树，几十个
    节点之后就没法用了。"""
    store.set_expanded(user, body.note_id, body.parent_note_id, body.expanded)
    return {"note_id": body.note_id, "expanded": body.expanded}


@router.get("/paths/{note_id}")
def paths(note_id: str, user: str = Depends(current_user)) -> list[list[str]]:
    """这篇笔记在树上的所有位置。克隆之后「它在哪」没有唯一答案，面包屑要
    显示的是用户当前从哪条路径点进来的，所以这里返回全部，由调用方挑。"""
    if not store.get_note(user, note_id):
        raise HTTPException(404, "笔记不在")
    return store.note_paths(user, note_id)
