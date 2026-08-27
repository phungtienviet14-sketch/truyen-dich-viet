from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from .security import fetch_html

class BaseCrawler(ABC):
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.piaotia.com/",
        }

    async def fetch_html(self, url: str) -> str:
        return await fetch_html(url, self.headers, getattr(self, "encoding", "utf-8"))

    @abstractmethod
    async def get_novel_info(self, url: str) -> Dict[str, Any]:
        """
        Extracts novel details: title, author, description, cover_url, catalog_url
        """
        pass

    @abstractmethod
    async def get_chapter_list(self, catalog_url: str) -> List[Dict[str, Any]]:
        """
        Extracts all chapters: [{"title": str, "url": str, "index": int}]
        """
        pass

    @abstractmethod
    async def get_chapter_content(self, chapter_url: str) -> Dict[str, str]:
        """
        Extracts chapter text: {"title": str, "content": str}
        """
        pass
