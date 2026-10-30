"""Stable release parsing and bounded public GitHub transport."""

import io
import json
from urllib.error import HTTPError

import pytest

from app.services import releases


@pytest.mark.parametrize("tag", ["0.1.0", "v0.1.0", "1.10.2"])
def test_stable_tags(tag: str) -> None:
    """Accept stable numeric triplets, including the optional GitHub v prefix."""
    assert releases.stable_version(tag) is not None


@pytest.mark.parametrize("tag", ["0.1", "01.1.0", "1.0.0-beta", "garbage"])
def test_invalid_tags(tag: str) -> None:
    """Do not advertise development or malformed releases as stable updates."""
    assert releases.stable_version(tag) is None


def test_release_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """Derive a trusted release link rather than forwarding arbitrary response URLs."""
    def transport(request: object, timeout: int) -> io.BytesIO:
        """Return a bounded synthetic public release response."""
        assert timeout == 4
        return io.BytesIO(json.dumps({
            "tag_name": "v0.2.0", "draft": False, "prerelease": False,
            "html_url": "https://untrusted.invalid",
        }).encode())

    monkeypatch.setattr(releases, "urlopen", transport)
    assert releases.fetch_release() == (
        "0.2.0", "https://github.com/Xharos/sophikron/releases/tag/v0.2.0"
    )


def test_no_release(monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat the GitHub no-release response as a successful empty lookup."""
    def transport(*args: object, **kwargs: object) -> None:
        """Simulate the public repository without a published release."""
        raise HTTPError(releases.API_URL, 404, "Not Found", {}, None)

    monkeypatch.setattr(releases, "urlopen", transport)
    assert releases.fetch_release() is None


@pytest.mark.parametrize("body", [b"x" * 262145, b"{}", b"not json"],
                         ids=["oversized", "missing-fields", "invalid-json"])
def test_invalid_response(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    """Reject oversized or malformed responses without retaining external content."""
    monkeypatch.setattr(releases, "urlopen", lambda *a, **kw: io.BytesIO(body))
    with pytest.raises(ValueError):
        releases.fetch_release()
