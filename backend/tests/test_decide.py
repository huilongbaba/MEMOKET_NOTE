"""「拿主意」端点：Jev、Gemini、召回全是假的，不碰网络；凭据是占位符，响应里不许出现。"""

from __future__ import annotations

import asyncio
import base64
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app.database.kite.kite_memory import UserMemory
from app.routers import decide
from app.util import jev

TEXT = "供应商把交期改到十月中旬，是接受还是换供应商"
ROWS = [{"id": "f-1", "text": "九月的产线排期已经压到十月初。", "date": "2026-09-10", "kind": "plan"},
        {"id": "f-2", "text": "备选供应商上次报价高 8%。", "date": "2026-08-30", "kind": "fact"}]
FACTS = [{"id": "f-1", "text": "九月的产线排期已经压到十月初。", "when": "2026-09-10"},
         {"id": "f-2", "text": "备选供应商上次报价高 8%。", "when": "2026-08-30"}]
OPTIONS = {"frame": "交期推迟后怎么办", "is_decision": True, "options": [
    {"label": "接受十月中旬", "why": "排期本来就压到十月初，晚半个月影响有限。", "factIds": ["f-1", "f-9"]},
    {"label": "换供应商", "why": "备选报价只高 8%，交期更稳。", "factIds": ["f-2"]},
    {"label": "谈分批交付", "why": "先拿一部分货保住九月的排期。", "factIds": []},
]}
QUESTIONS = {"frame": "这段更像一条交期通知", "questions": [
    {"label": "要不要改排期", "why": "交期变了，排期多半跟着动。"},
    {"label": "要不要通知客户", "why": "下游交付可能受影响。"},
    {"label": "要不要找备选供应商", "why": "库里记着一家备选。"},
]}
# 剪贴板里的一张图：主进程给的是 PNG data URL。base64 正文带个标记，好断言它不会出现在任何响应里。
IMAGE_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"image-bytes-private-" * 4).decode()
IMAGE = "data:image/png;base64," + IMAGE_B64
DIGEST = "群里在问供应商把交期改到十月中旬，要接受还是换一家。"


@pytest.fixture(autouse=True)
def configuration(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-placeholder")
    monkeypatch.delenv("MEMOKET_GEMINI_KEY_FILE", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("MEMOKET_JEV_KEY_FILE", raising=False)

    def no_network():
        raise AssertionError("This test must inject a mock Gemini transport")

    monkeypatch.setattr(decide, "_gemini_client", no_network)
    jev_fake(monkeypatch)            # Jev 默认不在
    recall_fake(monkeypatch, [])     # 知识库默认是空的


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app, headers={"X-User-Id": "u1"}) as test_client:
        yield test_client


def candidate(payload) -> dict:
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}}]}


def gemini(monkeypatch, *, options=None, questions=None, weights=None, status=200, error=None):
    """按 responseSchema 分发：options / questions / weights 三种调用各给各的回复；没给的那种回 500。"""
    calls = []

    def respond(request):
        sent = json.loads(request.content)
        calls.append({"url": str(request.url), "headers": dict(request.headers), "body": sent})
        if error:
            raise error
        required = sent["generationConfig"]["responseSchema"]["required"]
        body = options if "options" in required else questions if "questions" in required else weights
        if body is None:
            return httpx.Response(500, json={"error": "unexpected-call"})
        return httpx.Response(status, json=body if "candidates" in body else candidate(body))

    monkeypatch.setattr(decide, "_gemini_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    return calls


def jev_fake(monkeypatch, *, route=None, pick=None, model="jev-1.13.0"):
    """route：Noul 概率（None = 没答）；pick：{label: 概率}（None = 没答）。全没答就回 None，像 Jev 不在。"""
    calls = []

    async def systemone(state, questions, **_):
        calls.append({"state": state, "questions": questions})
        answers = {}
        if "route" in questions and route is not None:
            answers["route"] = {"type": "noul", "noul": route}
        if "pick" in questions and pick is not None:
            probabilities = {oid: pick.get(desc.split("：")[0], 0.0) for oid, desc in questions["pick"]["criteria"].items()}
            answers["pick"] = {"type": "choice", "choice": max(probabilities, key=probabilities.get),
                               "confidence": max(probabilities.values()), "probabilities": probabilities}
        if not answers:
            return None
        out = jev.Answers(answers)
        out.model, out.usage = model, {"input_tokens": 1, "output_tokens": 1}
        return out

    monkeypatch.setattr(decide, "systemone", systemone)
    return calls


def recall_fake(monkeypatch, rows):
    calls = []
    monkeypatch.setattr(UserMemory, "is_empty", lambda self: not rows)

    def recall(self, query, limit=8, scope="all", *, evidence=False):
        calls.append({"user": self.user_id, "query": query, "limit": limit, "scope": scope, "evidence": evidence})
        return list(rows), ["交期"], 0.4

    monkeypatch.setattr(UserMemory, "recall", recall)
    return calls


def body(**changes):
    return {"text": TEXT, "source": "Safari", **changes}


# ---------------------------------------------------------------- 主路


def test_options_with_jev_scores_grounded_candidates(client, monkeypatch):
    recalled = recall_fake(monkeypatch, ROWS)
    asked = jev_fake(monkeypatch, route=0.93, pick={"接受十月中旬": 0.2, "换供应商": 0.7, "谈分批交付": 0.1})
    calls = gemini(monkeypatch, options=OPTIONS)
    response = client.post("/api/desktop/decide", json=body(context="客户那边十月底才验收"))
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["mode"] == "options" and out["frame"] == "交期推迟后怎么办" and out["isDecision"] == 0.93
    assert out["scorer"] == "jev" and out["model"] == "jev-1.13.0" and out["grounded"] is True
    assert out["facts"] == FACTS
    assert [(i["id"], i["label"], i["probability"], i["factIds"]) for i in out["items"]] == [
        ("a", "换供应商", 0.7, ["f-2"]), ("b", "接受十月中旬", 0.2, ["f-1"]), ("c", "谈分批交付", 0.1, []),
    ]
    assert set(out) == {"mode", "digest", "frame", "isDecision", "items", "facts", "grounded", "scorer", "model", "tookMs"}
    assert isinstance(out["tookMs"], float) and out["digest"] == ""     # 只有文字：不摆 digest
    # 召回：正文 + 背景当查询，候选池那一档（evidence=False），只取 5 条
    assert recalled == [{"user": "u1", "query": f"{TEXT} 客户那边十月底才验收", "limit": 5, "scope": "all", "evidence": False}]
    # Jev：先判再估；估的时候 state 带着事实，criteria 是「label：why」
    assert [list(c["questions"]) for c in asked] == [["route"], ["pick"]]
    assert asked[0]["questions"]["route"]["type"] == "noul" and "补充背景：客户那边十月底才验收" in asked[0]["state"]
    assert asked[1]["state"] == {"text": TEXT, "context": "客户那边十月底才验收", "facts": FACTS}
    assert asked[1]["questions"]["pick"]["criteria"]["b"] == "换供应商：备选报价只高 8%，交期更稳。"
    # Gemini：一次候选调用，事实进了 user content，schema 带 is_decision
    assert len(calls) == 1
    assert calls[0]["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test-model:generateContent"
    assert calls[0]["headers"]["x-goog-api-key"] == "unit-test-placeholder"
    sent = calls[0]["body"]
    assert len(sent["contents"][0]["parts"]) == 1      # 只有文字：没有 inlineData
    assert json.loads(sent["contents"][0]["parts"][0]["text"]) == {
        "text": TEXT, "source": "Safari", "context": "客户那边十月底才验收", "question": "", "facts": FACTS}
    assert sent["generationConfig"]["responseSchema"]["required"] == ["digest", "frame", "is_decision", "options"]
    assert sent["generationConfig"]["temperature"] == 0.3 and "tools" not in sent
    assert "不可信的引用材料" in sent["systemInstruction"]["parts"][0]["text"]
    assert "读图" not in sent["systemInstruction"]["parts"][0]["text"]
    assert "placeholder" not in response.text


def test_low_noul_probability_asks_questions_ranked_by_jev(client, monkeypatch):
    asked = jev_fake(monkeypatch, route=0.12, pick={"要不要改排期": 0.5, "要不要通知客户": 0.15, "要不要找备选供应商": 0.35})
    calls = gemini(monkeypatch, questions=QUESTIONS)
    response = client.post("/api/desktop/decide", json=body())
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["mode"] == "questions" and out["frame"] == "这段更像一条交期通知" and out["isDecision"] == 0.12
    assert out["scorer"] == "jev" and out["grounded"] is False and out["facts"] == []
    assert [(i["id"], i["label"], i["probability"]) for i in out["items"]] == [
        ("a", "要不要改排期", 0.5), ("b", "要不要找备选供应商", 0.35), ("c", "要不要通知客户", 0.15)]
    assert all(i["factIds"] == [] for i in out["items"])
    assert len(calls) == 1 and calls[0]["body"]["generationConfig"]["responseSchema"]["required"] == ["digest", "frame", "questions"]
    assert "想问" in asked[1]["questions"]["pick"]["instructions"]


def test_forced_options_mode_skips_the_route_question(client, monkeypatch):
    asked = jev_fake(monkeypatch, route=0.01, pick={"接受十月中旬": 0.3, "换供应商": 0.6, "谈分批交付": 0.1})
    gemini(monkeypatch, options=OPTIONS)
    response = client.post("/api/desktop/decide", json=body(mode="options"))
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "options" and response.json()["isDecision"] == 1.0
    assert [list(c["questions"]) for c in asked] == [["pick"]]


def test_a_chosen_question_enters_options_mode_and_reaches_the_prompt(client, monkeypatch):
    asked = jev_fake(monkeypatch, route=0.01, pick={"换供应商": 0.6})
    calls = gemini(monkeypatch, options=OPTIONS)
    response = client.post("/api/desktop/decide", json=body(question="要不要找备选供应商"))
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "options" and response.json()["isDecision"] == 1.0
    assert [list(c["questions"]) for c in asked] == [["pick"]]
    sent = json.loads(calls[0]["body"]["contents"][0]["parts"][0]["text"])
    assert sent["question"] == "要不要找备选供应商"
    assert "question" in calls[0]["body"]["systemInstruction"]["parts"][0]["text"]


def test_forced_questions_mode_skips_jev_route_and_options(client, monkeypatch):
    asked = jev_fake(monkeypatch, route=0.99, pick={"要不要改排期": 1.0})
    calls = gemini(monkeypatch, questions=QUESTIONS)
    response = client.post("/api/desktop/decide", json=body(mode="questions"))
    assert response.status_code == 200 and response.json()["mode"] == "questions"
    assert response.json()["isDecision"] == 0.0
    assert [list(c["questions"]) for c in asked] == [["pick"]] and len(calls) == 1


# ---------------------------------------------------------------- 退路


def test_without_jev_gemini_routes_and_weighs(client, monkeypatch):
    recall_fake(monkeypatch, ROWS)
    calls = gemini(monkeypatch, options=OPTIONS, weights={"weights": [{"id": "a", "weight": 2}, {"id": "b", "weight": 1}, {"id": "c", "weight": 1}, {"id": "zz", "weight": 9}]})
    response = client.post("/api/desktop/decide", json=body())
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["mode"] == "options" and out["isDecision"] == 1.0
    assert out["scorer"] == "model" and out["model"] == "gemini-test-model" and out["grounded"] is True
    assert [(i["id"], i["label"], i["probability"]) for i in out["items"]] == [
        ("a", "接受十月中旬", 0.5), ("b", "换供应商", 0.25), ("c", "谈分批交付", 0.25)]
    assert [c["body"]["generationConfig"]["responseSchema"]["required"] for c in calls] == [["digest", "frame", "is_decision", "options"], ["weights"]]
    weighed = json.loads(calls[1]["body"]["contents"][0]["parts"][0]["text"])
    assert weighed["mode"] == "options" and [i["id"] for i in weighed["items"]] == ["a", "b", "c"] and weighed["facts"] == FACTS
    weighed_system = next(c["body"]["systemInstruction"]["parts"][0]["text"] for c in calls if c["body"]["generationConfig"]["responseSchema"]["required"] == ["weights"])
    assert "会选" in weighed_system and "应该选" not in weighed_system   # 和 Jev 一样问「会选」，不问「该选」


def test_without_jev_gemini_can_say_it_is_not_a_decision(client, monkeypatch):
    calls = gemini(monkeypatch, options={**OPTIONS, "is_decision": False}, questions=QUESTIONS,
                   weights={"weights": [{"id": "a", "weight": 0.2}, {"id": "b", "weight": 0.3}, {"id": "c", "weight": 0.5}]})
    response = client.post("/api/desktop/decide", json=body())
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["mode"] == "questions" and out["isDecision"] == 0.0 and out["frame"] == "这段更像一条交期通知"
    assert out["scorer"] == "model" and [i["label"] for i in out["items"]] == ["要不要找备选供应商", "要不要通知客户", "要不要改排期"]
    assert [c["body"]["generationConfig"]["responseSchema"]["required"][-1] for c in calls] == ["options", "questions", "weights"]


def test_with_neither_scorer_the_answer_has_no_numbers(client, monkeypatch):
    gemini(monkeypatch, options=OPTIONS, weights={"candidates": [{"finishReason": "SAFETY"}]})
    response = client.post("/api/desktop/decide", json=body())
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["scorer"] == "none" and out["model"] == "gemini-test-model" and out["mode"] == "options"
    assert [(i["id"], i["label"], i["probability"]) for i in out["items"]] == [
        ("a", "接受十月中旬", 0.0), ("b", "换供应商", 0.0), ("c", "谈分批交付", 0.0)]
    assert out["grounded"] is False        # 没召回到事实，就不算有依据


def test_jev_route_then_jev_score_failure_still_falls_back(client, monkeypatch):
    jev_fake(monkeypatch, route=0.8, pick=None)
    gemini(monkeypatch, options=OPTIONS, weights={"weights": [{"id": "a", "weight": 0.1}, {"id": "b", "weight": 0.9}, {"id": "c", "weight": 0}]})
    response = client.post("/api/desktop/decide", json=body())
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["isDecision"] == 0.8 and out["scorer"] == "model" and out["model"] == "gemini-test-model"
    assert [(i["label"], i["probability"]) for i in out["items"]] == [("换供应商", 0.9), ("接受十月中旬", 0.1), ("谈分批交付", 0.0)]


def test_fewer_than_two_options_switches_to_questions(client, monkeypatch):
    asked = jev_fake(monkeypatch, route=0.8, pick={"要不要改排期": 0.7, "要不要通知客户": 0.2, "要不要找备选供应商": 0.1})
    calls = gemini(monkeypatch, options={**OPTIONS, "options": OPTIONS["options"][:1]}, questions=QUESTIONS)
    response = client.post("/api/desktop/decide", json=body())
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["mode"] == "questions" and out["frame"] == "这段看不出要选什么" and out["isDecision"] == 0.8
    assert [i["label"] for i in out["items"]] == ["要不要改排期", "要不要通知客户", "要不要找备选供应商"]
    assert out["scorer"] == "jev"
    assert [c["body"]["generationConfig"]["responseSchema"]["required"][-1] for c in calls] == ["options", "questions"]
    assert [list(c["questions"]) for c in asked] == [["route"], ["pick"]]


def test_duplicate_and_empty_candidates_are_dropped_and_unknown_fact_ids_filtered(client, monkeypatch):
    recall_fake(monkeypatch, ROWS)
    jev_fake(monkeypatch, route=0.9, pick={"换供应商": 0.5, "接受十月中旬": 0.5})
    gemini(monkeypatch, options={"frame": " 交期 \n 怎么办 ", "is_decision": True, "options": [
        {"label": "换供应商", "why": "x", "factIds": ["f-2", "f-2", "nope", 3]},
        {"label": "换供应商", "why": "重复", "factIds": []},
        {"label": "   ", "why": "空", "factIds": []},
        "not-an-object",
        {"label": "接受十月中旬", "why": "", "factIds": ["f-1"]},
    ]})
    out = client.post("/api/desktop/decide", json=body()).json()
    assert out["frame"] == "交期 怎么办"
    assert [(i["label"], i["factIds"]) for i in out["items"]] == [("换供应商", ["f-2"]), ("接受十月中旬", ["f-1"])]
    assert out["grounded"] is True


def test_recall_failure_or_empty_store_is_not_an_error(client, monkeypatch):
    def boom(self, *args, **kwargs):
        raise RuntimeError("index unavailable")

    monkeypatch.setattr(UserMemory, "is_empty", lambda self: False)
    monkeypatch.setattr(UserMemory, "recall", boom)
    jev_fake(monkeypatch, route=0.9, pick={"换供应商": 1.0})
    gemini(monkeypatch, options=OPTIONS)
    out = client.post("/api/desktop/decide", json=body()).json()
    assert out["facts"] == [] and out["grounded"] is False and all(i["factIds"] == [] for i in out["items"])


# ---------------------------------------------------------------- 剪贴板图片


def parts_of(call: dict) -> list[dict]:
    return call["body"]["contents"][0]["parts"]


def test_image_only_reads_the_picture_then_recalls_and_scores_on_the_digest(client, monkeypatch):
    recalled = recall_fake(monkeypatch, ROWS)
    asked = jev_fake(monkeypatch, route=0.01, pick={"接受十月中旬": 0.2, "换供应商": 0.7, "谈分批交付": 0.1})
    calls = gemini(monkeypatch, options={**OPTIONS, "digest": f"  {DIGEST} \n "})
    response = client.post("/api/desktop/decide", json={"text": "", "image": IMAGE, "source": "微信"})
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["mode"] == "options" and out["digest"] == DIGEST and out["frame"] == "交期推迟后怎么办"
    assert out["isDecision"] == 1.0                    # 没字可判：Jev Noul 不问，Gemini 的 is_decision 说了算
    assert out["scorer"] == "jev" and [(i["label"], i["probability"]) for i in out["items"]] == [
        ("换供应商", 0.7), ("接受十月中旬", 0.2), ("谈分批交付", 0.1)]
    # 召回：等 Gemini 读出 digest 之后才做、只做一次、用 digest 当查询；事实进了 Jev 的打分状态
    assert recalled == [{"user": "u1", "query": DIGEST, "limit": 5, "scope": "all", "evidence": False}]
    assert out["facts"] == FACTS
    assert [list(c["questions"]) for c in asked] == [["pick"]]
    assert asked[0]["state"] == {"text": DIGEST, "context": "", "facts": FACTS}
    # 候选那一步 Gemini 还没见过事实，它写的 factIds 一律不算数
    assert out["grounded"] is False and all(i["factIds"] == [] for i in out["items"])
    # Gemini：JSON 文字 part + inlineData part，系统提示先读图
    assert len(calls) == 1
    assert parts_of(calls[0]) == [
        {"text": json.dumps({"text": "", "source": "微信", "context": "", "question": "", "facts": []}, ensure_ascii=False)},
        {"inlineData": {"mimeType": "image/png", "data": IMAGE_B64}},
    ]
    system = calls[0]["body"]["systemInstruction"]["parts"][0]["text"]
    assert "先读图" in system and "digest" in system and "不可信" in system
    assert "image-bytes" not in response.text and "base64" not in response.text


def test_text_and_image_together_send_both_and_jev_still_routes_on_the_text(client, monkeypatch):
    recalled = recall_fake(monkeypatch, ROWS)
    asked = jev_fake(monkeypatch, route=0.93, pick={"换供应商": 1.0})
    calls = gemini(monkeypatch, options={**OPTIONS, "digest": DIGEST})
    response = client.post("/api/desktop/decide", json=body(image=IMAGE, context="十月底验收"))
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["mode"] == "options" and out["isDecision"] == 0.93 and out["digest"] == DIGEST
    assert [list(c["questions"]) for c in asked] == [["route"], ["pick"]]
    assert asked[1]["state"] == {"text": TEXT, "context": "十月底验收", "facts": FACTS}
    assert recalled == [{"user": "u1", "query": f"{TEXT} 十月底验收", "limit": 5, "scope": "all", "evidence": False}]
    parts = parts_of(calls[0])
    assert json.loads(parts[0]["text"])["text"] == TEXT and json.loads(parts[0]["text"])["facts"] == FACTS
    assert parts[1] == {"inlineData": {"mimeType": "image/png", "data": IMAGE_B64}}
    assert out["grounded"] is True


def test_image_only_without_jev_gemini_routes_asks_and_weighs_with_the_picture(client, monkeypatch):
    calls = gemini(monkeypatch, options={**OPTIONS, "is_decision": False, "digest": DIGEST},
                   questions={**QUESTIONS, "digest": "另一句不该覆盖前一句"},
                   weights={"weights": [{"id": "a", "weight": 0.2}, {"id": "b", "weight": 0.3}, {"id": "c", "weight": 0.5}]})
    response = client.post("/api/desktop/decide", json={"image": IMAGE})
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["mode"] == "questions" and out["isDecision"] == 0.0 and out["digest"] == DIGEST
    assert out["scorer"] == "model" and [i["label"] for i in out["items"]] == ["要不要找备选供应商", "要不要通知客户", "要不要改排期"]
    assert [c["body"]["generationConfig"]["responseSchema"]["required"][-1] for c in calls] == ["options", "questions", "weights"]
    # 三次调用都带着图；第一次读出的 digest 从第二次起进了 JSON，打权重时 text 为空也有东西可估
    assert all(parts_of(c)[1] == {"inlineData": {"mimeType": "image/png", "data": IMAGE_B64}} for c in calls)
    assert "digest" not in json.loads(parts_of(calls[0])[0]["text"])
    assert json.loads(parts_of(calls[1])[0]["text"])["digest"] == DIGEST
    weighed = json.loads(parts_of(calls[2])[0]["text"])
    assert weighed["text"] == "" and weighed["digest"] == DIGEST and weighed["mode"] == "questions"
    assert "image-bytes" not in response.text


def test_image_only_with_an_empty_digest_still_answers_without_recalling(client, monkeypatch):
    recalled = recall_fake(monkeypatch, ROWS)
    asked = jev_fake(monkeypatch, route=0.9, pick={"换供应商": 1.0})
    gemini(monkeypatch, options={**OPTIONS, "digest": ""})
    out = client.post("/api/desktop/decide", json={"image": IMAGE}).json()
    assert out["mode"] == "options" and out["digest"] == "" and out["facts"] == []
    assert recalled == []                               # 没有查询词就不去翻库
    assert asked == [] and out["scorer"] != "jev"       # Jev 什么都没看到，就不问它、也不挂它的名


def test_digest_is_clamped_to_200_chars_and_never_shown_for_text_only_input(client, monkeypatch):
    jev_fake(monkeypatch, route=0.9, pick={"换供应商": 1.0})
    gemini(monkeypatch, options={**OPTIONS, "digest": "字" * 300})
    assert client.post("/api/desktop/decide", json=body()).json()["digest"] == ""
    assert client.post("/api/desktop/decide", json={"image": IMAGE}).json()["digest"] == "字" * 200


@pytest.mark.parametrize("payload", [
    {"text": "", "image": ""}, {"image": ""}, {"text": "   ", "image": ""},
    {"image": "data:image/gif;base64,QUFBQQ=="},                    # 不收的格式
    {"image": "data:image/png;base64,not base64 private!!"},        # base64 里混了别的
    {"image": "data:image/png,QUFBQQ=="},                            # 不是 base64 编码
    {"image": "https://example.test/private.png"},                   # 不是 data URL
    {"image": IMAGE + "\n"},                                          # 尾巴上多了东西
    {"image": "data:image/png;base64," + "A" * 8_000_001},           # 超大
    {"image": 42}, {"image": IMAGE, "text": "x" * 6001}, {"image": IMAGE, "context": "y" * 2001},
])
def test_invalid_image_input_is_422_without_echo(client, payload):
    response = client.post("/api/desktop/decide", json=payload)
    assert response.status_code == 422 and set(response.json()) == {"detail"}
    assert "private" not in response.text and "AAAA" not in response.text and "image-bytes" not in response.text
    assert "xxxx" not in response.text and "yyyy" not in response.text


@pytest.mark.parametrize("mime", ["png", "jpeg", "webp"])
def test_accepted_image_formats_reach_gemini_with_their_mime_type(client, monkeypatch, mime):
    jev_fake(monkeypatch, route=0.9, pick={"换供应商": 1.0})
    calls = gemini(monkeypatch, options=OPTIONS)
    assert client.post("/api/desktop/decide", json={"image": f"data:image/{mime};base64,{IMAGE_B64}"}).status_code == 200
    assert parts_of(calls[0])[1] == {"inlineData": {"mimeType": f"image/{mime}", "data": IMAGE_B64}}


# ---------------------------------------------------------------- 错误


def test_gemini_not_configured_is_503_before_any_call(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    asked = jev_fake(monkeypatch, route=0.9)
    response = client.post("/api/desktop/decide", json=body())
    assert response.status_code == 503 and response.json()["detail"] == "桌面 AI 尚未配置可用的 Gemini 密钥。"
    assert asked == []
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-placeholder")
    monkeypatch.setenv("GEMINI_MODEL", "../bad model")
    assert client.post("/api/desktop/decide", json=body()).status_code == 503


@pytest.mark.parametrize("payload", [
    body(text="x" * 6001), body(text="   "), body(text=""), {}, body(mode="guess"),
    body(text=42), body(context="y" * 2001), body(question="z" * 301),
])
def test_invalid_input_is_422_without_echo(client, payload):
    response = client.post("/api/desktop/decide", json=payload)
    assert response.status_code == 422 and set(response.json()) == {"detail"}
    assert "xxxx" not in response.text and "yyyy" not in response.text and "zzzz" not in response.text


def test_text_is_stripped_and_exactly_6000_chars_are_allowed(client, monkeypatch):
    jev_fake(monkeypatch, route=0.9, pick={"换供应商": 1.0})
    calls = gemini(monkeypatch, options=OPTIONS)
    response = client.post("/api/desktop/decide", json=body(text="  " + "字" * 6000 + "\n"))
    assert response.status_code == 200
    assert json.loads(calls[0]["body"]["contents"][0]["parts"][0]["text"])["text"] == "字" * 6000


@pytest.mark.parametrize("upstream,expected,detail", [
    (400, 400, "拒绝了"), (401, 401, "密钥未通过验证"), (403, 403, "拒绝访问"), (429, 429, "额度不足"),
    (404, 503, "模型当前不可用"), (500, 502, "暂时不可用"),
])
def test_gemini_provider_errors_map_like_compose_note(client, monkeypatch, upstream, expected, detail):
    gemini(monkeypatch, options={"candidates": [], "error": "provider-private-diagnostics"}, status=upstream)
    response = client.post("/api/desktop/decide", json=body())
    assert response.status_code == expected and detail in response.json()["detail"]
    assert "provider-private" not in response.text and "placeholder" not in response.text


@pytest.mark.parametrize("error,status,detail", [
    (httpx.ReadTimeout("unit-test-placeholder"), 504, "超时"),
    (httpx.ConnectError("unit-test-placeholder"), 502, "无法连接"),
])
def test_gemini_transport_errors_are_safe(client, monkeypatch, error, status, detail):
    gemini(monkeypatch, error=error)
    response = client.post("/api/desktop/decide", json=body())
    assert response.status_code == status and detail in response.json()["detail"]
    assert "placeholder" not in response.text


@pytest.mark.parametrize("data", [
    {}, {"candidates": []}, {"candidates": [{"content": {"parts": [{"text": "not-json-private"}]}}]},
    candidate(["a-list"]), {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{}"}]}}]},
])
def test_unusable_candidate_output_is_502_without_echo(client, monkeypatch, data):
    gemini(monkeypatch, options=data)
    response = client.post("/api/desktop/decide", json=body())
    assert response.status_code == 502 and "private" not in response.text


# ---------------------------------------------------------------- Jev 客户端


def test_key_helper_only_accepts_single_line_ascii_and_never_leaks_the_path(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("JEV_API_KEY", " env-key-placeholder \n")
    assert jev.jev_api_key() == "env-key-placeholder"
    for bad in ("multi\nline-placeholder", "非ASCII-placeholder", "with space placeholder", "x" * 8193, "   "):
        monkeypatch.setenv("JEV_API_KEY", bad)
        assert jev.jev_api_key() == ""
    monkeypatch.delenv("JEV_API_KEY")
    assert jev.jev_api_key() == ""
    key_file = tmp_path / "jev.key"
    key_file.write_text("  file-key-placeholder \n", encoding="utf-8")
    monkeypatch.setenv("MEMOKET_JEV_KEY_FILE", str(key_file))
    assert jev.jev_api_key() == "file-key-placeholder"
    key_file.write_text("line-one\nline-two\n", encoding="utf-8")
    assert jev.jev_api_key() == ""
    key_file.write_bytes(b"\xff\xfe")
    assert jev.jev_api_key() == ""
    monkeypatch.setenv("MEMOKET_JEV_KEY_FILE", str(tmp_path / "missing.key"))
    assert jev.jev_api_key() == ""
    monkeypatch.setenv("MEMOKET_JEV_KEY_FILE", str(tmp_path))     # a directory
    assert jev.jev_api_key() == ""
    with caplog.at_level(logging.DEBUG, logger="jev"):
        assert asyncio.run(jev.systemone("s", {"q": jev.noul_question("i", "t", "f")})) is None
    assert str(tmp_path) not in caplog.text and "placeholder" not in caplog.text


def test_question_helpers_build_the_documented_shapes():
    assert jev.noul_question("是不是", "是", "不是") == {"type": "noul", "instructions": "是不是", "criteria": {"true": "是", "false": "不是"}}
    assert jev.choice_question("选哪个", {"a": "甲", "b": "乙"}) == {"type": "choice", "instructions": "选哪个", "criteria": {"a": "甲", "b": "乙"}}
    with pytest.raises(ValueError):
        jev.choice_question("选哪个", {})
    with pytest.raises(ValueError):
        jev.choice_question("选哪个", {str(i): "x" for i in range(256)})


def jev_transport(monkeypatch, respond):
    monkeypatch.setenv("JEV_API_KEY", "jev-key-placeholder")
    return httpx.AsyncClient(transport=httpx.MockTransport(respond))


def test_systemone_posts_bearer_and_parses_answers(monkeypatch, caplog):
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"model": "jev-1.13.0", "answers": {
            "r": {"type": "noul", "noul": 0.97},
            "p": {"type": "choice", "choice": "b", "confidence": 0.9, "probabilities": {"a": 0.1, "b": 0.9}},
        }, "usage": {"input_tokens": 12, "output_tokens": 3}})

    client = jev_transport(monkeypatch, respond)
    questions = {"r": jev.noul_question("i", "t", "f"), "p": jev.choice_question("c", {"a": "甲", "b": "乙"})}
    with caplog.at_level(logging.DEBUG, logger="jev"):
        answers = asyncio.run(jev.systemone({"text": "状态"}, questions, client=client, timeout=3.0))
    assert isinstance(answers, dict) and answers.model == "jev-1.13.0" and answers.usage == {"input_tokens": 12, "output_tokens": 3}
    assert jev.noul_probability(answers, "r") == 0.97
    assert jev.choice_probabilities(answers, "p", ["b", "a", "missing"]) == {"b": 0.9, "a": 0.1, "missing": 0.0}
    assert jev.noul_probability(answers, "p") is None and jev.choice_probabilities(answers, "r", ["a"]) is None
    assert jev.noul_probability(None, "r") is None and jev.choice_probabilities({}, "p", ["a"]) is None
    request = seen[0]
    assert str(request.url) == jev.JEV_URL and request.method == "POST"
    assert request.headers["authorization"] == "Bearer jev-key-placeholder"
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {"model": "jev-latest", "state": {"text": "状态"}, "questions": questions}
    assert "placeholder" not in caplog.text


@pytest.mark.parametrize("respond", [
    lambda request: httpx.Response(401, json={"error": "invalid key placeholder"}),
    lambda request: httpx.Response(429, text="slow down"),
    lambda request: httpx.Response(529, text="overloaded"),
    lambda request: httpx.Response(200, text="<html>placeholder</html>"),
    lambda request: httpx.Response(200, json={"model": "jev-1.13.0"}),
    lambda request: httpx.Response(200, json=["answers"]),
    lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("placeholder-timeout")),
    lambda request: (_ for _ in ()).throw(httpx.ConnectError("placeholder-connect")),
])
def test_systemone_returns_none_on_every_failure_without_logging_secrets(monkeypatch, caplog, respond):
    client = jev_transport(monkeypatch, respond)
    with caplog.at_level(logging.DEBUG, logger="jev"):
        assert asyncio.run(jev.systemone("s", {"q": jev.noul_question("i", "t", "f")}, client=client)) is None
    assert caplog.records and "placeholder" not in caplog.text


def test_systemone_without_questions_or_key_does_not_call_the_network(monkeypatch):
    def respond(request):
        raise AssertionError("must not be called")

    client = jev_transport(monkeypatch, respond)
    assert asyncio.run(jev.systemone("s", {}, client=client)) is None
    monkeypatch.delenv("JEV_API_KEY")
    assert asyncio.run(jev.systemone("s", {"q": jev.noul_question("i", "t", "f")}, client=client)) is None
