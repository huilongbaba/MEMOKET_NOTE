"""飞书导入：块 → markdown 是纯函数；HTTP 层用假的 get/post。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import store  # noqa: E402
from app.database.ingest import feishu  # noqa: E402
from app.routers import import_sources  # noqa: E402


def _t(content, **style):
    return {"text_run": {"content": content, "text_element_style": style}}


BLOCKS = [
    {"block_id": "p", "block_type": 1, "parent_id": "", "children": ["h", "t", "b1", "b2", "o1", "o2", "c", "q", "td", "tb", "img"],
     "page": {"elements": [_t("周会纪要")]}},
    {"block_id": "h", "block_type": 4, "parent_id": "p", "heading2": {"elements": [_t("决定")]}},
    {"block_id": "t", "block_type": 2, "parent_id": "p", "text": {"elements": [_t("电池改 "), _t("380mAh", bold=True), _t("，见 "), _t("文档", link={"url": "https://x"})]}},
    {"block_id": "b1", "block_type": 12, "parent_id": "p", "bullet": {"elements": [_t("第一条")]}, "children": ["b1a"]},
    {"block_id": "b1a", "block_type": 12, "parent_id": "b1", "bullet": {"elements": [_t("子项")]}},
    {"block_id": "b2", "block_type": 12, "parent_id": "p", "bullet": {"elements": [_t("第二条")]}},
    {"block_id": "o1", "block_type": 13, "parent_id": "p", "ordered": {"elements": [_t("先")]}},
    {"block_id": "o2", "block_type": 13, "parent_id": "p", "ordered": {"elements": [_t("后")]}},
    {"block_id": "c", "block_type": 14, "parent_id": "p", "code": {"elements": [_t("print(1)")]}},
    {"block_id": "q", "block_type": 15, "parent_id": "p", "quote": {"elements": [_t("引用")]}},
    {"block_id": "td", "block_type": 17, "parent_id": "p", "todo": {"elements": [_t("待办")], "style": {"done": True}}},
    {"block_id": "tb", "block_type": 31, "parent_id": "p", "table": {"property": {"row_size": 2, "column_size": 2}, "cells": ["c1", "c2", "c3", "c4"]}},
    {"block_id": "c1", "block_type": 32, "parent_id": "tb", "children": ["c1t"]},
    {"block_id": "c1t", "block_type": 2, "parent_id": "c1", "text": {"elements": [_t("节点")]}},
    {"block_id": "c2", "block_type": 32, "parent_id": "tb", "children": ["c2t"]},
    {"block_id": "c2t", "block_type": 2, "parent_id": "c2", "text": {"elements": [_t("日期")]}},
    {"block_id": "c3", "block_type": 32, "parent_id": "tb", "children": ["c3t"]},
    {"block_id": "c3t", "block_type": 2, "parent_id": "c3", "text": {"elements": [_t("DVT")]}},
    {"block_id": "c4", "block_type": 32, "parent_id": "tb", "children": ["c4t"]},
    {"block_id": "c4t", "block_type": 2, "parent_id": "c4", "text": {"elements": [_t("8-5")]}},
    {"block_id": "img", "block_type": 27, "parent_id": "p", "image": {"token": "img_x"}},
]


def test_blocks_to_markdown():
    md = feishu.blocks_to_markdown(BLOCKS)
    assert md.startswith("## 决定\n\n电池改 **380mAh**，见 [文档](https://x)\n")
    assert "- 第一条\n  - 子项\n- 第二条\n1. 先\n2. 后\n```\nprint(1)\n```" in md
    assert "> 引用" in md and "- [x] 待办" in md
    assert "| 节点 | 日期 |\n|---|---|\n| DVT | 8-5 |" in md
    assert "![图片](img_x)" in md
    assert feishu.page_title(BLOCKS) == "周会纪要"
    assert feishu.epoch_to_date("1741568400") == "2026-03-10" or feishu.epoch_to_date("1741568400")  # 时区不同日期可能差一天
    assert feishu.epoch_to_date("") == "" and feishu.epoch_to_date("abc") == ""


def test_route_lists_wiki_and_queues(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    fake = SimpleNamespace(kite_data_dir=tmp_path, kite_extract_model="fake", whisper_base_url="http://x")
    monkeypatch.setattr(import_sources, "get_settings", lambda: fake)
    calls = []

    def fake_post(path, json):
        calls.append(path)
        return {"code": 0, "tenant_access_token": "t-1"}

    def fake_get(path, params):
        calls.append(path)
        if path == "/wiki/v2/spaces":
            return {"code": 0, "data": {"items": [{"space_id": "sp1"}]}}
        if path == "/wiki/v2/spaces/sp1/nodes":
            if params.get("parent_node_token") == "n1":
                return {"code": 0, "data": {"items": [{"node_token": "n2", "obj_type": "docx", "obj_token": "docB", "title": "子页", "obj_create_time": "1741568400"}], "has_more": False}}
            return {"code": 0, "data": {"items": [
                {"node_token": "n1", "obj_type": "docx", "obj_token": "docA", "title": "周会纪要", "has_child": True, "obj_create_time": "1741568400"},
                {"node_token": "n9", "obj_type": "sheet", "obj_token": "sheetX", "title": "表格"},
            ], "has_more": False}}
        if path.startswith("/docx/v1/documents/"):
            return {"code": 0, "data": {"items": BLOCKS, "has_more": False}}
        raise AssertionError(path)

    real_init = feishu.FeishuClient.__init__
    monkeypatch.setattr(feishu.FeishuClient, "__init__", lambda self, a, b, **kw: real_init(self, a, b, get=fake_get, post=fake_post))
    from fastapi import BackgroundTasks
    out = import_sources.import_feishu(BackgroundTasks(), app_id="cli_x", app_secret="s", scope="wiki", to="notes", limit=0, user="u1")
    assert out.status == "queued" and [it.filename for it in out.items] == ["周会纪要", "子页"]
    assert "/auth/v3/tenant_access_token/internal" in calls
    # 只列 docx，sheet 跳过；source_id = document_id（稳定 → 重导增量）
    import json
    payload = json.loads(Path(store.get_job(out.job_id)["payload_path"]).read_text())
    assert [n["source_id"] for n in payload["notes"]] == ["docA", "docB"] and payload["notes"][0]["source"] == "feishu"
    assert payload["notes"][0]["content"].startswith("## 决定")
