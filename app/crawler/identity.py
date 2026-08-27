"""Cross-platform novel identity.

The same Chinese web novel is mirrored across Piaotia, Biquge and their many
clones, each with its own catalog URL. Deduplicating on ``source_url`` alone
therefore imports the same book once per platform. These helpers reduce a
title/author pair to a stable fingerprint that survives the cosmetic
differences between mirrors (full-width punctuation, decorative brackets,
"latest chapter" suffixes, serialization status tags).
"""
import hashlib
import re
import unicodedata

# Mirrors append promotional text to <title> and to the author cell.
_TITLE_NOISE = (
    "最新章节", "最新更新", "全文阅读", "无弹窗", "免费阅读", "在线阅读", "章节目录",
    "txt下载", "小说阅读", "笔趣阁", "飘天文学网", "飘天文学", "顶点小说",
    "全文免费阅读", "无广告", "免费下载", "小说", "正文",
)
_AUTHOR_NOISE = ("编著", "原著", "著作", "作品", "著")
# Decorative wrappers: CJK brackets, quotes, parens, and separator runs.
_PUNCTUATION = re.compile(r"[《》〈〉「」『』【】〔〕（）()\[\]{}<>\"'“”‘’·・,，.。、;；:：!！?？~～\-—_/\\|*#@+=]+")
_WHITESPACE = re.compile(r"\s+")


def _fold(value: str) -> str:
    """NFKC folds full-width forms and compatibility variants onto one shape."""
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKC", value)
    text = text.replace("　", " ").replace("\xa0", " ")
    return _WHITESPACE.sub(" ", text).strip()


def normalize_title(title: str) -> str:
    text = _fold(title)
    # A mirror may separate the book name from its noise with _ or | .
    text = re.split(r"[_|]", text)[0]
    for noise in _TITLE_NOISE:
        text = text.replace(noise, "")
    text = _PUNCTUATION.sub("", text)
    return _WHITESPACE.sub("", text).casefold()


def normalize_author(author: str) -> str:
    text = _fold(author)
    for noise in _AUTHOR_NOISE:
        text = text.replace(noise, "")
    text = _PUNCTUATION.sub("", text)
    return _WHITESPACE.sub("", text).casefold()


def work_key(title: str, author: str) -> str:
    """Identity of the work itself, shared by every mirror that carries it.

    Empty when the title normalizes away, so an unparsed page never collides
    with another unparsed page and silently merges two unrelated books.
    """
    normalized_title = normalize_title(title)
    if not normalized_title:
        return ""
    payload = f"{normalized_title}|{normalize_author(author)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def title_key(title: str) -> str:
    """Weaker identity used only to warn when the author is missing or differs."""
    normalized_title = normalize_title(title)
    if not normalized_title:
        return ""
    return hashlib.sha256(normalized_title.encode("utf-8")).hexdigest()
