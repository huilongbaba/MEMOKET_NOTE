"""Note attachments are owned copies, exportable, and never active web uploads."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import time
import zipfile
from urllib.parse import unquote

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.database import assets as assets_store, store
from app.routers import assets


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


@pytest.fixture
def client(tmp_path, monkeypatch):
    owned = tmp_path / "assets"
    owned.mkdir()
    monkeypatch.setattr(assets_store, "assets_dir", lambda: owned)
    app = FastAPI()
    app.include_router(assets.router)
    with TestClient(app) as test_client:
        yield test_client


def attach(client, name, data, content_type="application/octet-stream"):
    response = client.post("/api/assets/attachments", files={"file": (name, data, content_type)})
    assert response.status_code == 200, response.text
    return response.json()


def test_file_is_an_independent_copy_with_its_original_download_name(client, tmp_path):
    source = tmp_path / "会议方案.pdf"
    source.write_bytes(b"%PDF-1.7\nAttachment test material")
    original = source.read_bytes()
    with source.open("rb") as file:
        response = client.post("/api/assets/attachments", files={"file": (source.name, file, "application/pdf")})
    assert source.read_bytes() == original
    source.unlink()
    result = response.json()
    assert result == {"url": result["url"], "name": "会议方案.pdf", "kind": "file",
                      "bytes": len(original), "content_type": "application/pdf"}
    assert re.fullmatch(r"/api/assets/[a-f0-9]{24}\.pdf", result["url"])
    download = client.get(result["url"])
    assert download.content == original
    assert download.headers["content-type"] == "application/octet-stream"
    assert download.headers["content-disposition"].startswith("attachment;")
    assert "会议方案.pdf" in unquote(download.headers["content-disposition"])
    assert download.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in download.headers["content-security-policy"]


def test_raster_image_uses_actual_content_and_is_renderable(client):
    result = attach(client, "拍摄图片.unknown", PNG)
    assert result["kind"] == "image" and result["content_type"] == "image/png"
    assert result["name"] == "拍摄图片.unknown" and result["bytes"] == len(PNG)
    response = client.get(result["url"])
    assert response.content == PNG and response.headers["content-type"] == "image/png"
    assert "attachment" not in response.headers.get("content-disposition", "")
    assert attach(client, "另一个名字.png", PNG, "image/png")["url"] == result["url"]


@pytest.mark.parametrize("name,data,content_type", [
    ("草稿图片.png", PNG, "image/png"),
    ("草稿附件.pdf", b"%PDF-1.7\nunsaved draft attachment", "application/pdf"),
])
def test_unsaved_draft_attachment_survives_age_and_startup_sweep(client, name, data, content_type):
    result = attach(client, name, data, content_type)
    stored_name = result["url"].rsplit("/", 1)[-1]
    directory = assets_store.assets_dir()
    owned = directory / stored_name
    marker = directory / assets_store.ATTACHMENT_METADATA_DIR / f"{stored_name}.json"
    assert json.loads(marker.read_text())["retained_for_note"] is True
    old = time.time() - 8 * 86400
    os.utime(owned, (old, old))
    os.utime(marker, (old, old))
    orphan = directory / ("f" * 24 + ".png")
    orphan.write_bytes(b"old unrelated image")
    os.utime(orphan, (old, old))
    # The same function runs at startup. Nothing was saved in the notes DB;
    # retain the on-disk ownership marker without needing browser state.
    assert store.sweep_orphan_assets(directory) == {"removed": 1, "bytes": len(b"old unrelated image")}
    assert owned.read_bytes() == data and marker.is_file() and not orphan.exists()
    with TestClient(client.app) as restarted:
        response = restarted.get(result["url"])
        assert response.content == data
        assert response.headers["content-type"] == ("image/png" if result["kind"] == "image" else "application/octet-stream")
        assert restarted.get(f"/api/assets/{assets_store.ATTACHMENT_METADATA_DIR}/{stored_name}.json").status_code == 404


def test_legacy_raster_dedup_gets_durable_attachment_ownership_without_rewriting(client):
    legacy = client.post("/api/assets", files={"file": ("原图.png", PNG, "image/png")}).json()
    stored_name = legacy["url"].rsplit("/", 1)[-1]
    owned = assets_store.assets_dir() / stored_name
    old = time.time() - 8 * 86400
    os.utime(owned, (old, old))
    first = attach(client, "第一次附加.png", PNG, "image/png")
    marker = assets_store.assets_dir() / assets_store.ATTACHMENT_METADATA_DIR / f"{stored_name}.json"
    first_metadata = marker.read_bytes()
    second = attach(client, "另一次附加.png", PNG, "image/png")
    assert legacy["url"] == first["url"] == second["url"]
    assert owned.stat().st_mtime == old and owned.read_bytes() == PNG
    assert marker.read_bytes() == first_metadata
    assert store.sweep_orphan_assets(assets_store.assets_dir()) == {"removed": 0, "bytes": 0}


@pytest.mark.parametrize("name,content_type", [
    ("active.html", "text/html"), ("active.svg", "image/svg+xml"),
    ("fake.png", "image/png"), ("fake.avif", "image/avif"),
    ("fake.mp3", "audio/mpeg"), ("page.xml", "application/xml"),
])
def test_active_content_and_spoofed_media_are_always_downloads(client, name, content_type):
    result = attach(client, name, b"<html><script>alert(document.cookie)</script></html>", content_type)
    assert result["kind"] == "file"
    response = client.get(result["url"])
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment;")
    # Losing filename metadata must never turn previously safe content inline.
    stored = result["url"].rsplit("/", 1)[-1]
    (assets_store.assets_dir() / ".attachment-names" / f"{stored}.json").unlink()
    fallback = client.get(result["url"])
    assert fallback.headers["content-type"] == "application/octet-stream"
    assert fallback.headers["content-disposition"].startswith("attachment;")


def test_names_cannot_write_paths_or_expose_metadata(client):
    result = attach(client, r"C:\Downloads\..\report.pdf", b"pdf material")
    assert result["name"] == "report.pdf"
    assert assets._attachment_name("../../notes/\r\nreport.pdf\x00") == "report.pdf"
    assert assets._attachment_name("..") == "附件"
    assert len(assets._attachment_name("a" * 300)) == 180
    assert client.get("/api/assets/%2E%2E%5Coutside.txt").status_code == 400
    assert client.get("/api/assets/..%2Foutside.txt").status_code == 404
    stored = result["url"].rsplit("/", 1)[-1]
    assert client.get(f"/api/assets/.attachment-names/{stored}.json").status_code == 404


def test_symlink_cannot_be_used_to_serve_an_outside_file(client, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    (assets_store.assets_dir() / "link.txt").symlink_to(outside)
    assert client.get("/api/assets/link.txt").status_code == 404


def test_file_names_and_contents_do_not_overwrite_each_other(client):
    first = attach(client, "report.txt", b"first")
    duplicate = attach(client, "report.txt", b"first")
    revised = attach(client, "report.txt", b"second")
    renamed = attach(client, "renamed.txt", b"first")
    assert first["url"] == duplicate["url"]
    assert len({first["url"], revised["url"], renamed["url"]}) == 3
    assert client.get(first["url"]).content == b"first"
    assert client.get(revised["url"]).content == b"second"


def test_empty_and_oversized_uploads_are_rejected_without_asset_files(client, monkeypatch):
    monkeypatch.setattr(assets, "MAX_BYTES", 16)
    assert client.post("/api/assets/attachments", files={"file": ("empty.txt", b"")}).status_code == 400
    assert client.post("/api/assets/attachments", files={"file": ("large.txt", b"x" * 17)}).status_code == 413
    assert list(assets_store.assets_dir().iterdir()) == []
    assert attach(client, "limit.txt", b"x" * 16)["bytes"] == 16


def test_upload_read_is_bounded_and_file_is_closed_even_on_failure(monkeypatch):
    monkeypatch.setattr(assets, "MAX_BYTES", 16)

    class Incoming:
        filename = "large.txt"
        closed = False
        requested = []

        async def read(self, size=-1):
            self.requested.append(size)
            assert size == 17
            return b"x" * size

        async def close(self):
            self.closed = True

    incoming = Incoming()
    with pytest.raises(HTTPException) as error:
        asyncio.run(assets.upload_attachment(incoming, "unit-test"))
    assert error.value.status_code == 413
    assert incoming.requested == [17] and incoming.closed


def test_attachments_are_included_in_existing_markdown_export(client):
    from app.routers.export import build_export

    file = attach(client, "资料.pdf", b"%PDF-1.7\nexported attachment")
    image = attach(client, "图.png", PNG, "image/png")
    store.create_note("attachment-export", "带附件", f"[资料]({file['url']})\n\n![图]({image['url']})")
    archive = zipfile.ZipFile(io.BytesIO(build_export("attachment-export")))
    body = archive.read("带附件.md").decode()
    for item in (file, image):
        name = item["url"].rsplit("/", 1)[-1]
        assert archive.read(f"_assets/{name}") == client.get(item["url"]).content
        assert f"_assets/{name}" in body
    assert "/api/assets/" not in body
    assert not any("attachment-names" in name for name in archive.namelist())


def test_legacy_media_upload_contract_remains_unchanged(client):
    response = client.post("/api/assets", files={"file": ("recording.wav", b"RIFFaudio", "audio/wav")})
    assert response.status_code == 200
    result = response.json()
    assert result["kind"] == "audio" and result["name"] == "recording.wav"
    assert client.get(result["url"]).headers["content-type"] in ("audio/wav", "audio/x-wav")
    assert client.post("/api/assets", files={"file": ("report.pdf", b"%PDF", "application/pdf")}).status_code == 400
