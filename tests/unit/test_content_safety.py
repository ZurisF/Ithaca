import pytest

from content_safety import ContentRejected, filter_text


def test_secret_is_removed_before_snapshot_storage_or_model_use() -> None:
    raw = "# 项目\napi_key = 'sk-123456789012345678901234'\n普通说明。"
    result = filter_text(raw)
    assert "sk-123456789012345678901234" not in result.text
    assert "[已脱敏]" in result.text
    assert result.changed
    assert [(hit.kind, hit.line) for hit in result.hits] == [("credential_assignment", 2)]


def test_private_key_and_bearer_are_removed() -> None:
    raw = (
        "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n"
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz"
    )
    result = filter_text(raw)
    assert "abc" not in result.text
    assert "abcdefghijklmnopqrstuvwxyz" not in result.text
    assert [(hit.kind, hit.line) for hit in result.hits] == [
        ("private_key", 1),
        ("bearer_token", 4),
    ]


@pytest.mark.parametrize("raw", ["", "\x00bad", "a" * 21])
def test_reject_empty_controls_and_length(raw: str) -> None:
    with pytest.raises(ContentRejected):
        filter_text(raw, max_chars=20)
