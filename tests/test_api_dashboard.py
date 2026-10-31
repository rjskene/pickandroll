"""The API serves the dashboard's build under /app when it exists (#262): the routine host's
API, which the tailnet reaches, is then the dashboard too, its root redirecting there (#271).
Without a build nothing changes."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app

HTML = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


def build(root: Path) -> Path:
    dist = root / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<!doctype html>\n<div id="root"></div>\n')
    (dist / "assets" / "index-abc123.js").write_text("console.log(1);\n")
    return dist


def test_the_api_serves_the_dashboard_build_under_app(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    with TestClient(create_app(SessionStore(), data_dir=data, web_dist=build(tmp_path))) as c:
        # the page, for every path the app keeps a view in, with its queries
        for path in ("/app", "/app/", "/app/progress", "/app/queue", "/app/?league=31822"):
            r = c.get(path, headers=HTML)
            assert r.status_code == 200, path
            assert r.text.startswith("<!doctype html>") and "text/html" in r.headers["content-type"]
        r = c.get("/app/assets/index-abc123.js")
        assert r.status_code == 200 and r.text == "console.log(1);\n"
        # the API's own routes are what they were, the Progress screen's JSON among them
        assert c.get("/health").json()["status"] == "ok"
        assert "leagues" in c.get("/progress", headers=HTML).json()
        assert c.get("/sessions/none", headers=HTML).status_code == 404
        # a file the build lacks, or an unknown path outside /app: 404 as always
        assert c.get("/app/favicon.ico", headers=HTML).status_code == 404
        assert c.get("/app/assets/missing.js").status_code == 404
        assert c.get("/nope", headers=HTML).status_code == 404


def test_with_a_build_the_root_redirects_to_the_dashboard(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    with TestClient(create_app(SessionStore(), data_dir=data, web_dist=build(tmp_path))) as c:
        r = c.get("/", headers=HTML, follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == "/app/"
        followed = c.get("/", headers=HTML)
        assert followed.status_code == 200 and followed.text.startswith("<!doctype html>")


def test_without_a_build_the_api_serves_no_page(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    with TestClient(create_app(SessionStore(), data_dir=data, web_dist=tmp_path / "none")) as c:
        assert c.get("/app", headers=HTML).status_code == 404
        assert c.get("/app/progress", headers=HTML).status_code == 404
        assert c.get("/health").json()["status"] == "ok"
        # The root keeps its answer (#271): no redirect to a page that is not there.
        root = c.get("/", headers=HTML, follow_redirects=False)
        assert root.status_code == 404 and root.json() == {"detail": "Not Found"}
