from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import MAX_CONCURRENT_TRANSLATIONS


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CrawlRequest(InputModel):
    url: str = Field(min_length=1, max_length=2000)
    title_vi: str | None = Field(default=None, min_length=1, max_length=255)
    # Opt out of cross-platform dedup to keep a second mirror on purpose.
    allow_duplicate: bool = False


class TranslateRequest(InputModel):
    start_chapter: int = Field(default=1, ge=1)
    end_chapter: int | None = Field(default=None, ge=1)
    concurrency: int = Field(default=MAX_CONCURRENT_TRANSLATIONS, ge=1, le=MAX_CONCURRENT_TRANSLATIONS)
    retranslate_completed: bool = False

    @model_validator(mode="after")
    def valid_range(self):
        if self.end_chapter is not None and self.end_chapter < self.start_chapter:
            raise ValueError("Chương cuối phải lớn hơn hoặc bằng chương đầu")
        return self


class BatchTranslateRequest(InputModel):
    novel_ids: list[int] | None = Field(default=None, max_length=100)
    policy: Literal["request_priority", "all_pending", "round_robin"] = "request_priority"
    concurrency: int = Field(default=MAX_CONCURRENT_TRANSLATIONS, ge=1, le=MAX_CONCURRENT_TRANSLATIONS)
    chapters_per_novel: int | None = Field(default=None, ge=1, le=500)


class SyncConfigRequest(InputModel):
    interval_minutes: int = Field(default=30, ge=5, le=1440)
    auto_translate: bool = False


class GlossaryCreate(InputModel):
    original_term: str = Field(min_length=1, max_length=255)
    translated_term: str = Field(min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=255)


class DiscoverHotRequest(InputModel):
    category: Literal["0", "1", "2"] = "2"
    count: int = Field(default=10, ge=1, le=20)


class CommentCreate(InputModel):
    user_name: str = Field(default="Đạo Hữu Vô Danh", min_length=1, max_length=100)
    user_avatar: Literal["🧙‍♂️", "⚔️", "🐉", "🌸", "🔥", "📜", "⚡"] = "🧙‍♂️"
    content: str = Field(min_length=1, max_length=5000)
    chapter_index: int | None = Field(default=None, ge=1)
