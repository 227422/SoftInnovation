"""Provider-neutral values for public notice text and precise evidence locations."""

import hashlib
import json
import re
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator


NonBlankText = Annotated[str, Field(pattern=r'\S')]
Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
Page = Annotated[int, Field(ge=1)]
BodyStatus = Literal['full', 'partial', 'title_only', 'unavailable']


def _public_url(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username is not None or any(char.isspace() for char in value)):
        raise ValueError('expected an HTTP(S) source URL without credentials')
    return value


PublicURL = Annotated[NonBlankText, AfterValidator(_public_url)]


def _array(value):
    # JSON arrays remain arrays on the wire. A tuple also keeps accepted data immutable.
    return tuple(value) if isinstance(value, list) else value


type Array[T] = Annotated[tuple[T, ...], BeforeValidator(_array)]


class PublicValue(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid', allow_inf_nan=False)


def stable_digest(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


class DocumentAsset(PublicValue):
    asset_id: NonBlankText
    asset_hash: Digest | None = None


def validated_table_merges(values, location: str) -> tuple[str, ...]:
    """Validate row-local provenance of explicitly merged spreadsheet cells."""
    row = re.fullmatch(r'sheet:.+/row:([1-9]\d*)', location)
    if not isinstance(values, (list, tuple)) or not row:
        raise ValueError('table merge requires a spreadsheet row')
    for value in values:
        match = re.fullmatch(r'[A-Z]{1,3}([1-9]\d*):[A-Z]{1,3}([1-9]\d*)', value) if isinstance(value, str) else None
        if not match or not int(match[1]) <= int(row[1]) <= int(match[2]):
            raise ValueError('table merge does not cover its row')
    if len(set(values)) != len(values):
        raise ValueError('duplicate table merge')
    return tuple(values)


class DocumentSegment(PublicValue):
    id: NonBlankText
    kind: Literal['title', 'body', 'attachment']
    text: NonBlankText
    location: NonBlankText
    page: Page | None = None
    asset_id: NonBlankText | None = None
    asset_hash: Digest | None = None
    method: NonBlankText | None = None
    table_merges: Array[NonBlankText] = Field(default=(), exclude_if=lambda ranges: not ranges)

    @model_validator(mode='after')
    def location_matches_source(self) -> Self:
        if self.table_merges:
            if self.kind != 'attachment':
                raise ValueError('table merge requires an attachment')
            validated_table_merges(self.table_merges, self.location)
        if self.kind == 'attachment':
            if self.asset_id is None:
                raise ValueError('attachment segment requires an asset ID')
        elif self.asset_id is not None or self.asset_hash is not None or self.page is not None:
            raise ValueError('title and body segments cannot use attachment locators')
        return self


class DocumentBundle(PublicValue):
    notice_id: NonBlankText
    content_version: NonBlankText
    title: NonBlankText
    school_id: NonBlankText | None = None
    source_id: NonBlankText | None = None
    source_name: NonBlankText | None = None
    source_url: PublicURL
    published_at: NonBlankText | None = None
    body_status: BodyStatus
    segments: Array[DocumentSegment]
    assets: Array[DocumentAsset] = ()
    primary_asset_ids: Array[NonBlankText] = Field(default=(), exclude_if=lambda ids: not ids)
    gaps: Array[NonBlankText] = ()
    input_fingerprint: Digest

    @model_validator(mode='after')
    def body_matches_segments(self) -> Self:
        if (not self.segments or self.segments[0].id != 'title' or self.segments[0].kind != 'title'
                or self.segments[0].text != self.title or any(seg.kind == 'title' for seg in self.segments[1:])):
            raise ValueError('document must begin with its distinct title segment')
        if self.body_status in ('title_only', 'unavailable') and len(self.segments) != 1:
            raise ValueError('unavailable body cannot contain readable segments')
        if len({seg.id for seg in self.segments}) != len(self.segments):
            raise ValueError('duplicate segment ID')
        if len({asset.asset_id for asset in self.assets}) != len(self.assets):
            raise ValueError('duplicate asset ID')
        located_assets = {(seg.asset_id, seg.asset_hash) for seg in self.segments
                          if seg.kind == 'attachment' and seg.page is not None}
        valid_primary_ids = {asset.asset_id for asset in self.assets if asset.asset_hash
                             and (asset.asset_id, asset.asset_hash) in located_assets}
        if (len(set(self.primary_asset_ids)) != len(self.primary_asset_ids)
                or not set(self.primary_asset_ids).issubset(valid_primary_ids)):
            raise ValueError('primary PDF requires a matching hashed asset and readable page')
        return self


class EvidenceLocator(PublicValue):
    segment_id: NonBlankText | None = None
    page: Page | None = None
    clause: NonBlankText | None = None


class EvidenceRef(PublicValue):
    evidence_id: NonBlankText
    source_kind: Literal['notice', 'policy']
    source_id: NonBlankText
    source_content_version: NonBlankText
    source_url: PublicURL
    asset_id: NonBlankText | None = None
    asset_hash: Digest | None = None
    locator: EvidenceLocator
    quote: NonBlankText
