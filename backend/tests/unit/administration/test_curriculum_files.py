"""Portable graph validation without filesystem access or code execution."""

import json

import pytest

from app.schemas.curricula import CompetencyImport
from app.services.curriculum_files import REQUEST_LIMIT, parse_import
from app.services.errors import AuthError


def document(nodes: list[dict]) -> dict:
    """Wrap local nodes in the supported file format."""
    return {"format": "sophikron.competencies", "version": 1, "subject_name": "SII", "nodes": nodes}


def parse(nodes: list[dict]) -> CompetencyImport:
    """Exercise the raw file string carried inside the authenticated request."""
    return parse_import(
        json.dumps({"expected_version": 0, "document": json.dumps(document(nodes))}).encode()
    )


def test_portable_content_remains_inert_and_shared_nodes_remain_unique() -> None:
    """Keep teaching text verbatim, including strings that resemble source code."""
    result = parse(
        [
            {"id": 1, "name": "A", "knowledge": "<script>alert(1)</script>"},
            {"id": 2, "name": "B"},
            {"id": 3, "name": "C", "parent_ids": [1, 2]},
        ]
    )
    assert result.document.nodes[0].knowledge == "<script>alert(1)</script>"
    assert result.document.nodes[2].parent_ids == [1, 2]


@pytest.mark.parametrize(
    "nodes",
    [
        [{"id": 1, "name": "A", "parent_ids": [1]}],
        [{"id": 1, "name": "A", "parent_ids": [2]}, {"id": 2, "name": "B", "parent_ids": [1]}],
        [{"id": 1, "name": "A", "parent_ids": [9]}],
        [{"id": 1, "name": "A"}, {"id": 1, "name": "B"}],
        [{"id": 1, "name": "A", "color": "javascript:alert(1)"}],
        [{"id": 1, "name": "A", "semester": 5}],
        [{"id": 1, "name": "A", "execute": "dangerous()"}],
        [{"id": 1, "name": "A", "parent_ids": [2, 2]}, {"id": 2, "name": "B"}],
        [{"id": i, "name": "A", "parent_ids": [i - 1] if i > 1 else []} for i in range(1, 130)],
    ],
)
def test_invalid_graphs_fail_without_recursion(nodes: list[dict]) -> None:
    """Reject invalid identities, fields, cycles and excessive depth."""
    with pytest.raises(AuthError) as error:
        parse(nodes)
    assert error.value.status == 422


@pytest.mark.parametrize(
    "body",
    [
        b'{"expected_version":0,"expected_version":1}',
        b'{"__proto__":{}}',
        b"not json",
        ("[" * 2000 + "]" * 2000).encode(),
        json.dumps({"expected_version": 0, "document": '{"format":"a","format":"b"}'}).encode(),
    ],
)
def test_bad_json_is_rejected(body: bytes) -> None:
    """Bound malformed or ambiguous JSON before model validation."""
    with pytest.raises(AuthError):
        parse_import(body)


def test_oversized_json_is_rejected() -> None:
    """Reject oversized bodies before invoking the JSON parser."""
    with pytest.raises(AuthError) as error:
        parse_import(b" " * (REQUEST_LIMIT + 1))
    assert error.value.status == 413
