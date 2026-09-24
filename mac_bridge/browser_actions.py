"""Bounded common browser actions. No posting workflow or credential extraction."""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field
from .policy import MacError

MAX_UPLOAD_FILES = 20
MAX_UPLOAD_BYTES = 32 * 1024 ** 3
MAX_FORM_FIELDS = 20
MAX_FORM_CHARS = 32000


class FormField(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target: Annotated[str, Field(pattern=r'^(f\d+)?e\d+$', max_length=40)]
    name: Annotated[str, Field(min_length=1, max_length=160)]
    type: Literal['textbox', 'checkbox', 'radio', 'combobox', 'slider']
    value: Annotated[str, Field(max_length=8000)]


def form_fields(fields) -> list[dict]:
    if not isinstance(fields, list) or not 1 <= len(fields) <= MAX_FORM_FIELDS:
        raise MacError('Fill 1..20 observed form fields per call.')
    try:
        values = [FormField.model_validate(f).model_dump() for f in fields]
    except ValueError as exc:
        raise MacError('Invalid form fields. Use observed target, name, type and value.') from exc
    if sum(len(f['value']) for f in values) > MAX_FORM_CHARS:
        raise MacError('Combined form content exceeds 32000 characters.')
    if len({f['target'] for f in values}) != len(values):
        raise MacError('A field may appear only once per batch.')
    for f in values:
        if f['type'] in {'checkbox', 'radio'} and f['value'] not in {'true', 'false'}:
            raise MacError('Checkbox/radio values must be true or false.')
    return values


def upload_files(policy, paths: list[str]) -> list[dict]:
    if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_UPLOAD_FILES:
        raise MacError('Select 1..20 explicitly requested files; directories are not supported.')
    files = []
    for value in paths:
        if not isinstance(value, str) or not 1 <= len(value) <= 4096:
            raise MacError('Invalid upload file path.')
        path = policy.path(value, file_only=True)
        if not path.is_file():
            raise MacError('Upload file does not exist.')
        st = path.stat()
        if st.st_nlink != 1:
            raise MacError('Hard-linked files are not accepted for upload.')
        files.append({'path': str(path), 'identity': (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)})
    if len({f['path'] for f in files}) != len(files):
        raise MacError('Duplicate upload file.')
    if sum(f['identity'][2] for f in files) > MAX_UPLOAD_BYTES:
        raise MacError('Combined upload selection exceeds 32 GiB. Split the selection.')
    return files


def check_upload_unchanged(policy, expected: list[dict]) -> list[str]:
    actual = upload_files(policy, [f['path'] for f in expected])
    if actual != expected:
        raise MacError('Upload source changed before attachment. Review it and retry.')
    return [f['path'] for f in actual]
