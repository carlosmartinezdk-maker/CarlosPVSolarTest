"""Acceptance tests 24, 29, 32 (Section 10) against the standalone S2 script.

s2_nsrdb.py deliberately has no dependency on the rest of the repo, so it's
imported directly by path here rather than as a package member.
"""
import importlib.util
import io
import re
import sys
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
S2_PATH = REPO_ROOT / "s2_nsrdb.py"

spec = importlib.util.spec_from_file_location("s2_nsrdb", S2_PATH)
s2 = importlib.util.module_from_spec(spec)
sys.modules["s2_nsrdb"] = s2  # dataclass() needs the module registered to resolve type hints
spec.loader.exec_module(s2)


def _http_error(code, headers=None, body=b""):
    return urllib.error.HTTPError(
        url="https://developer.nlr.gov/api/nsrdb/v2/solar/x",
        code=code,
        msg="error",
        hdrs=headers or {},
        fp=io.BytesIO(body),
    )


def test_proxy_denial_classified_distinctly_from_auth_failure():
    """Acceptance test 29: with an unreachable host, S2 names the cause as
    a proxy denial rather than an auth failure."""
    proxy_403 = _http_error(403, headers={"x-deny-reason": "host_not_allowed"})
    result = s2.classify_error(proxy_403)
    assert result.outcome == "proxy_denial"

    auth_403 = _http_error(403, body=b'{"errors": ["Invalid API key"]}')
    result2 = s2.classify_error(auth_403)
    assert result2.outcome == "auth_failure"

    assert result.outcome != result2.outcome


def test_connect_tunnel_403_classified_as_proxy_denial():
    """Regression test: urllib raises URLError (not HTTPError) when a
    forward proxy rejects the CONNECT tunnel itself -- observed directly
    against this sandbox's egress proxy denying developer.nlr.gov. Must
    not be lumped into 'other_error'."""
    tunnel_err = urllib.error.URLError("Tunnel connection failed: 403 Forbidden")
    result = s2.classify_error(tunnel_err)
    assert result.outcome == "proxy_denial"


def test_dns_failure_classified():
    dns_err = urllib.error.URLError(OSError("getaddrinfo failed: Name or service not known"))
    result = s2.classify_error(dns_err)
    assert result.outcome == "dns_failure"


def test_410_gone_is_flagged_as_own_bug_not_transient():
    err = _http_error(410)
    result = s2.classify_error(err)
    assert result.outcome == "other_error"
    assert "bug" in result.detail.lower()


def test_rate_limit_classified():
    err = _http_error(429)
    result = s2.classify_error(err)
    assert result.outcome == "rate_limited"


def test_base_url_points_at_nlr_not_retired_nrel():
    """Acceptance test 24: the live request target must be developer.nlr.gov.
    developer.nrel.gov does not resolve as of 29 May 2026 (brief Section 5)."""
    assert s2.BASE_URL == "https://developer.nlr.gov"
    assert "nrel.gov" not in s2.BASE_URL


def test_nrel_gov_mentions_are_diagnostic_text_only_never_a_request_target():
    """Every remaining 'nrel.gov' string in the module must be inside an
    error/diagnostic message (flagged by the word 'retired' nearby), never
    assigned to a URL, host, or endpoint constant used for a live request."""
    text = S2_PATH.read_text()
    for i, line in enumerate(text.splitlines(), 1):
        if "nrel.gov" in line.lower():
            assert "retired" in line.lower(), (
                f"s2_nsrdb.py:{i} references nrel.gov outside a 'retired' "
                f"diagnostic message -- check it isn't being used as a live "
                f"request target: {line.strip()}"
            )


def test_build_url_targets_nlr(monkeypatch):
    monkeypatch.setenv("NLR_API_KEY", "sk-totally-fake-test-key-do-not-use")
    live_url = s2.build_url(39.74, -105.17, 2023, "test@example.invalid")
    assert "nrel.gov" not in live_url
    assert "developer.nlr.gov" in live_url


def test_no_secrets_in_source(monkeypatch):
    """Acceptance test 32 (source-level slice): the key is read from env,
    never assigned as a literal."""
    monkeypatch.setenv("NLR_API_KEY", "sk-totally-fake-test-key-do-not-use")
    assert s2.api_key() == "sk-totally-fake-test-key-do-not-use"
    source = S2_PATH.read_text()
    assert "sk-totally-fake-test-key-do-not-use" not in source
    assert re.search(r'api_key\s*=\s*["\'][A-Za-z0-9]{10,}', source) is None


def test_api_key_missing_exits_nonzero(monkeypatch, capsys):
    monkeypatch.delenv("NLR_API_KEY", raising=False)
    monkeypatch.delenv("NREL_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        s2.api_key()
    assert exc_info.value.code == 2


def test_snap_to_grid_dedupes_nearby_points():
    a = s2.snap_to_grid(39.7392, -104.9903)  # Denver
    b = s2.snap_to_grid(39.7395, -104.9905)  # a few meters away
    assert a == b


def test_parse_years_rejects_2026():
    with pytest.raises(SystemExit):
        s2.parse_years("2019-2026")


def test_parse_years_accepts_full_available_range():
    years = s2.parse_years("2019-2025")
    assert years == list(range(2019, 2026))


def test_cache_path_does_not_embed_api_key():
    p = s2.cache_path(Path("/tmp/cache"), 39.74, -105.17, 2023)
    assert "sk-" not in str(p)
    assert str(p).endswith("grid_lat=39.74/grid_lon=-105.17/year=2023/data.csv")
