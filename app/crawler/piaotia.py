import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .base import BaseCrawler
from .security import MAX_CATALOG_CHAPTERS, canonical_url, same_source_url


# The source publishes its own popularity counters on the info page. Labels
# carry stray spaces and non-breaking spaces ("收 藏 数"), so every pattern is
# matched against a whitespace-free copy of the page text.
_STAT_PATTERNS = {
    "source_word_count": r"全文长度[:：](\d+)",
    "source_favorites": r"收藏数[:：](\d+)",
    "source_recommends": r"总推荐数[:：](\d+)",
    "source_monthly_recommends": r"本月推荐[:：](\d+)",
}
_DONE_TOKENS = ("已完成", "已完结", "完本", "全本")


def parse_source_stats(page_text: str) -> dict:
    compact = re.sub(r"\s+", "", page_text or "")
    stats = {}
    for field, pattern in _STAT_PATTERNS.items():
        match = re.search(pattern, compact)
        if match:
            # A malformed page must not poison a sort column.
            stats[field] = min(int(match.group(1)), 2_000_000_000)
    status = re.search(r"文章状态[:：](已完成|已完结|完本|全本|连载中|连载)", compact)
    if status:
        stats["source_status"] = "completed" if status.group(1) in _DONE_TOKENS else "ongoing"
    return stats


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
        for tag in soup.find_all("td"):
            text = tag.get_text(" ", strip=True).replace("\xa0", " ")
            match = re.search(r"作\s*者[：:\s]*([^\s]+)", text)
            if match and match.group(1) not in ("书名", "类别", "状态", "字数"):
                author = match.group(1).strip()
                break
        if not author:
            for tag in soup.find_all(["span", "div", "p"]):
                text = tag.get_text(" ", strip=True).replace("\xa0", " ")
                match = re.search(r"作\s*者[：:\s]*([^\s]+)", text)
                if match and match.group(1) not in ("书名", "类别", "状态", "字数"):
                    author = match.group(1).strip()
                    break

        description = ""
        for tag in soup.find_all("td"):
            text = tag.get_text(" ", strip=True)
            if "内容简介" in text:
                parts = text.split("内容简介", 1)
                if len(parts) > 1:
                    description = parts[1].lstrip("：: ").strip()
                    break
        if not description:
            desc_tag = soup.select_one("span.hottext, td.v_content, div#content")
            if desc_tag:
                description = desc_tag.get_text(" ", strip=True)

        parsed_info = urlsplit(info_url)
        match_info = re.search(r"/(\d+)/(\d+)", parsed_info.path)
        if match_info:
            f_id, s_id = match_info.groups()
            image = soup.find("img", src=re.compile(rf"/files/article/image/{f_id}/{s_id}/"))
        else:
            image = None
        if not image:
            image = soup.find("img", src=re.compile(r"/files/article/image/"))
        cover = ""
        if image and image.get("src"):
            try:
                cover = same_source_url(info_url, image.get("src", ""))
            except ValueError:
                pass  # An untrusted optional image is omitted, never fetched.
        return {"title": title, "author": author,
                "description": description or "",
                "cover_url": cover, "source_url": catalog_url,
                "source_name": "piaotia", "catalog_url": catalog_url,
                **parse_source_stats(soup.get_text(" ", strip=True))}

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
