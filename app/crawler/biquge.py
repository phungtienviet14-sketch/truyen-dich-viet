import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .base import BaseCrawler
from .security import MAX_CATALOG_CHAPTERS, canonical_url, same_source_url


class BiqugeCrawler(BaseCrawler):
    encoding = "utf-8"

    async def get_novel_info(self, url: str) -> dict:
        url = canonical_url(url)
        soup = BeautifulSoup(await self.fetch_html(url), "html.parser")
        heading = soup.find("h1") or soup.title
        title = heading.get_text(" ", strip=True).split("_")[0] if heading else ""
        if not title:
            raise ValueError("Không tìm thấy tiêu đề truyện tại nguồn.")
        author = ""
        for tag in soup.find_all(["p", "span", "div"]):
            text = tag.get_text(" ", strip=True)
            match = re.search(r"作\s*者[：:\s]*([^\s]+)", text)
            if len(text) < 80 and match:
                author = match.group(1)
                break
        description = soup.select_one("#intro, .intro, p.review")
        image = soup.select_one("#fmimg img, .cover img")
        cover = ""
        if image and image.get("src"):
            try:
                cover = same_source_url(url, image["src"])
            except ValueError:
                pass  # Optional external images are deliberately omitted.
        return {"title": title, "author": author,
                "description": description.get_text(" ", strip=True) if description else "",
                "cover_url": cover, "source_url": url,
                "source_name": "biquge", "catalog_url": url}

    async def get_chapter_list(self, catalog_url: str) -> list[dict]:
        catalog_url = canonical_url(catalog_url)
        soup = BeautifulSoup(await self.fetch_html(catalog_url), "html.parser")
        container = soup.select_one("#list, .listmain, .chapterlist")
        if container is None:
            raise ValueError("Không tìm thấy danh sách chương tại nguồn.")
        chapters, seen = [], set()
        for anchor in container.find_all("a", href=True):
            try:
                candidate = same_source_url(catalog_url, anchor["href"])
            except ValueError:
                continue
            title, path = anchor.get_text(" ", strip=True), urlsplit(candidate).path
            if (not title or candidate == catalog_url or candidate in seen
                    or not (path.endswith(".html") or re.search(r"/\d+/\d+/?$", path))):
                continue
            seen.add(candidate)
            chapters.append({"title": title, "url": candidate, "index": len(chapters) + 1})
            if len(chapters) > MAX_CATALOG_CHAPTERS:
                raise ValueError("Mục lục vượt giới hạn chương.")
        if not chapters:
            raise ValueError("Không tìm thấy danh sách chương tại nguồn.")
        return chapters

    async def get_chapter_content(self, chapter_url: str) -> dict[str, str]:
        soup = BeautifulSoup(await self.fetch_html(canonical_url(chapter_url)), "html.parser")
        heading = soup.find("h1")
        body = soup.select_one("#content, #chaptercontent, .content")
        if body is None:
            raise ValueError("Không tìm thấy nội dung chương (content).")
        for tag in body.find_all(["script", "style", "a"]):
            tag.decompose()
        content = "\n\n".join(line.strip() for line in body.get_text("\n").splitlines() if line.strip())
        if not content:
            raise ValueError("Không tìm thấy nội dung chương (content).")
        return {"title": heading.get_text(" ", strip=True) if heading else "", "content": content}
