import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .base import BaseCrawler
from .security import MAX_CATALOG_CHAPTERS, canonical_url, same_source_url


class PiaotiaCrawler(BaseCrawler):
    encoding = "gb18030"

    def _normalize_url(self, url: str) -> tuple[str, str]:
        url = canonical_url(url)
        parsed = urlsplit(url)
        match = re.fullmatch(r"/(?:bookinfo|html)/(\d+)/(\d+)(?:\.html|/|/index\.html)?", parsed.path)
        if not match:
            raise ValueError("URL truyện Piaotia không hợp lệ.")
        first, second = match.groups()
        root = f"https://{parsed.netloc}"
        return f"{root}/bookinfo/{first}/{second}.html", f"{root}/html/{first}/{second}/index.html"

    async def get_novel_info(self, url: str) -> dict:
        info_url, catalog_url = self._normalize_url(url)
        soup = BeautifulSoup(await self.fetch_html(info_url), "html.parser")
        heading = soup.find("h1") or soup.title
        title = re.split(r"最新章节|_", heading.get_text(strip=True))[0] if heading else ""
        if not title:
            raise ValueError("Không tìm thấy tiêu đề truyện tại nguồn.")
        author = ""
        for tag in soup.find_all(["td", "span", "div"]):
            text = tag.get_text(" ", strip=True)
            match = re.search(r"作\s*者[：:\s]*([^\s]+)", text)
            if len(text) < 80 and match:
                author = match.group(1)
                break
        description = soup.select_one("span.hottext, td.v_content, div#content")
        if description is None:
            description = next((tag for tag in soup.find_all("td")
                                if len(tag.get_text()) > 80 and
                                any(label in tag.get_text() for label in ("内容简介", "作品简介"))), None)
        image = soup.find("img", src=re.compile(r"/files/article/image/"))
        cover = ""
        if image:
            try:
                cover = same_source_url(info_url, image.get("src", ""))
            except ValueError:
                pass  # An untrusted optional image is omitted, never fetched.
        return {"title": title, "author": author,
                "description": description.get_text(" ", strip=True) if description else "",
                "cover_url": cover, "source_url": catalog_url,
                "source_name": "piaotia", "catalog_url": catalog_url}

    async def get_chapter_list(self, catalog_url: str) -> list[dict]:
        _, catalog_url = self._normalize_url(catalog_url)
        soup = BeautifulSoup(await self.fetch_html(catalog_url), "html.parser")
        directory = urlsplit(catalog_url).path.rsplit("/", 1)[0] + "/"
        chapters, seen = [], set()
        for anchor in soup.find_all("a", href=True):
            try:
                candidate = same_source_url(catalog_url, anchor["href"])
            except ValueError:
                continue
            path = urlsplit(candidate).path
            title = anchor.get_text(" ", strip=True)
            if (path.rsplit("/", 1)[0] + "/" != directory
                    or not re.fullmatch(r"\d+\.html", path.rsplit("/", 1)[-1])
                    or not title or candidate in seen):
                continue
            seen.add(candidate)
            chapters.append({"title": title, "url": candidate, "index": len(chapters) + 1})
            if len(chapters) > MAX_CATALOG_CHAPTERS:
                raise ValueError("Mục lục vượt giới hạn chương.")
        if not chapters:
            raise ValueError("Không tìm thấy danh sách chương tại nguồn.")
        return chapters

    async def get_chapter_content(self, chapter_url: str) -> dict[str, str]:
        html = await self.fetch_html(canonical_url(chapter_url))
        soup = BeautifulSoup(html, "html.parser")
        heading = soup.find("h1")
        title = heading.get_text(" ", strip=True) if heading else ""
        body = soup.select_one("#content, #chaptercontent, .chapter-content")
        if body is None:
            # Older pages place the body between heading/table navigation
            # and the bottom navigation marker, without a content div.
            match = re.search(r'</h1>(.*?)<(?:div\s+class=["\']bottomlink|!--\s*翻页上AD开始)', html, re.S | re.I)
            if not match:
                raise ValueError("Không tìm thấy nội dung chương (content).")
            body = BeautifulSoup(match.group(1), "html.parser")
        for tag in body.find_all(["script", "style", "table", "a"]):
            tag.decompose()
        lines = [line.strip() for line in body.get_text("\n").splitlines() if line.strip()]
        content = "\n\n".join(line for line in lines if not any(
            word in line for word in ("上一章", "下一章", "返回目录", "加入书签", "推荐本书", "飘天文学")))
        if not content:
            raise ValueError("Không tìm thấy nội dung chương (content).")
        return {"title": title, "content": content}
