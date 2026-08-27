from .base import BaseCrawler
from .piaotia import PiaotiaCrawler
from .biquge import BiqugeCrawler
from .security import PIAOTIA_HOSTS, canonical_url
from urllib.parse import urlsplit

def get_crawler(url: str) -> BaseCrawler:
    host = urlsplit(canonical_url(url)).hostname
    if host in PIAOTIA_HOSTS:
        return PiaotiaCrawler()
    # canonical_url already requires the admin to explicitly allow this host.
    return BiqugeCrawler()
