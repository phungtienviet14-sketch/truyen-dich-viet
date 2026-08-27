"""Rendered-template contracts independent of the database and external APIs."""
from pathlib import Path
from types import SimpleNamespace

from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "templates"
ENV = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))


def test_public_nav_does_not_show_admin_link():
    public = BeautifulSoup(ENV.get_template("base.html").render(is_admin=False), "html.parser")
    admin = BeautifulSoup(ENV.get_template("base.html").render(is_admin=True), "html.parser")
    assert public.select_one('a[href="/admin"]') is None
    assert admin.select_one('a[href="/admin"]') is not None


def test_untrusted_titles_are_data_not_inline_javascript():
    payload = "');alert(1);//<img src=x onerror=alert(2)>"
    novel = SimpleNamespace(id=1, title=payload, title_vi=None, author=payload, cover_url=None,
                            total_chapters=3, translated_chapters=1, request_count=0, favorite_count=0)
    html = ENV.get_template("index.html").render(novels=[novel], total_novels=1,
                                                 total_chapters=3, total_translated=1)
    soup = BeautifulSoup(html, "html.parser")
    assert not any(payload in str(value) for element in soup.find_all() for key, value in element.attrs.items() if key.startswith("on"))
    download = soup.select_one('[data-novel-action="download"]')
    assert download["data-title"] == payload
    assert soup.select_one("img[onerror]") is None


def test_public_routes_and_reader_do_not_dispatch_paid_jobs():
    for filename in ("index.html", "novel_detail.html"):
        source = (TEMPLATES / filename).read_text(encoding="utf-8")
        assert "/request-translation" in source
        assert "/api/export/" not in source
        assert "/download?" in source
    reader = (TEMPLATES / "reader.html").read_text(encoding="utf-8")
    assert "/request-translation" in reader
    assert "}/translate'" not in reader
    assert "retranslate_completed" not in reader


def test_styles_and_icons_do_not_execute_remote_cdn_code():
    for filename in ("base.html", "admin/admin_base.html"):
        source = (TEMPLATES / filename).read_text(encoding="utf-8")
        assert "cdn.tailwindcss.com" not in source
        assert "unpkg.com" not in source
        assert 'href="/static/css/app.css"' in source
        assert 'src="/static/js/app.js"' in source


def test_admin_login_and_identity_are_explicit():
    login = BeautifulSoup(ENV.get_template("admin/login.html").render(error="Sai mật khẩu"), "html.parser")
    assert login.select_one('form[action="/admin/login"][method="post"]')
    assert login.select_one('input[name="username"][autocomplete="username"]')
    assert login.select_one('input[name="password"][type="password"]')
    assert login.select_one('[role="alert"]').get_text(strip=True) == "Sai mật khẩu"
    admin = ENV.get_template("admin/admin_base.html").render(is_admin=True, admin_username="editor<script>")
    assert "editor&lt;script&gt;" in admin
    assert "data-admin-logout" in admin
