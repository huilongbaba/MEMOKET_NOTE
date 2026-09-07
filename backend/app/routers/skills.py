"""Skill 系统的管理接口：CRUD + 开关 + 排序 + 可用 scope 列表。

真正"生效"的地方不在这里——各个生成调用点（compose.py/writing_plan.py）
在拼 system prompt 时自己调 store.enabled_skills_for_scope() +
prompts.compose_system()，这个路由只管前端面板增删改查。
"""

import json

from fastapi import APIRouter, Depends, HTTPException

from .. import llm, prompts, store
from ..schemas import Skill, SkillGenerateIn, SkillIn, SkillReorderIn, SkillScope
from .deps import current_user

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("/scopes", response_model=list[SkillScope])
def list_scopes():
    return [{"value": k, "label": v} for k, v in prompts.SKILL_SCOPES.items()]


@router.get("", response_model=list[Skill])
def list_skills(user: str = Depends(current_user)):
    return store.list_skills(user)


@router.post("/generate", response_model=SkillIn)
async def generate_skill(body: SkillGenerateIn, user: str = Depends(current_user)):
    """用一两句话描述想要的写作行为，让模型草拟一条 skill——返回的是草稿
    （SkillIn 形状），不直接落库。前端在同一个编辑表单里展示，用户看过、
    改过、选好 scope 之后再调 POST /api/skills 真正保存，跟"导入第三方
    skill"走的是同一套"先预览再保存"流程。"""
    goal = body.goal.strip()
    if not goal:
        raise HTTPException(400, "goal required")
    text = await llm.complete(
        [{"role": "system", "content": prompts.skill_generate_system()},
         {"role": "user", "content": prompts.skill_generate_user(goal, body.scope_hint)}],
        max_tokens=500, temperature=0.5)
    parsed = llm.extract_json(text)
    if not isinstance(parsed, dict):
        raise HTTPException(502, "模型没能生成有效的技能内容，换个描述再试试")
    scopes = [s for s in (parsed.get("scopes") or []) if s in prompts.SKILL_SCOPES]
    content = str(parsed.get("content") or "").strip()
    if not content:
        raise HTTPException(502, "模型没能生成有效的技能内容，换个描述再试试")
    return SkillIn(
        name=str(parsed.get("name") or "").strip() or "未命名技能",
        description=str(parsed.get("description") or "").strip(),
        scopes=scopes,
        content=content,
        enabled=True,
    )


@router.post("", response_model=Skill)
def create_skill(body: SkillIn, user: str = Depends(current_user)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "skill name required")
    if not body.content.strip():
        raise HTTPException(400, "skill content required")
    return store.create_skill(user, name, body.description, body.scopes, body.content, body.enabled)


@router.put("/{skill_id}", response_model=Skill)
def update_skill(skill_id: str, body: SkillIn, user: str = Depends(current_user)):
    updated = store.update_skill(
        user, skill_id,
        name=body.name.strip() or "未命名技能",
        description=body.description,
        scopes=json.dumps(body.scopes, ensure_ascii=False),
        content=body.content,
        enabled=1 if body.enabled else 0,
    )
    if not updated:
        raise HTTPException(404, "skill not found")
    return updated


@router.post("/{skill_id}/toggle", response_model=Skill)
def toggle_skill(skill_id: str, user: str = Depends(current_user)):
    skill = store.get_skill(user, skill_id)
    if not skill:
        raise HTTPException(404, "skill not found")
    updated = store.update_skill(user, skill_id, enabled=0 if skill["enabled"] else 1)
    return updated


@router.delete("/{skill_id}")
def delete_skill(skill_id: str, user: str = Depends(current_user)):
    if not store.delete_skill(user, skill_id):
        raise HTTPException(404, "skill not found")
    return {"deleted": skill_id}


@router.post("/reorder")
def reorder_skills(body: SkillReorderIn, user: str = Depends(current_user)):
    store.reorder_skills(user, body.ordered_ids)
    return {"ok": True}
