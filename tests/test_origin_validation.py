import urllib.parse
import pytest
from starlette.requests import Request
from backend.main import root_redirect
from backend.routers.auth import _validate_trusted_origin


def make_req(headers=None, query_string=""):
    scope = {
        "type": "http",
        "path": "/",
        "query_string": query_string.encode("latin1"),
        "headers": [(k.lower().encode("latin1"), v.encode("latin1")) for k, v in (headers or {}).items()],
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_root_open_redirect_mitigated():
    trusted_hosts = {"localhost", "127.0.0.1", "compass-kappa-nine.vercel.app"}

    # Attack 1: Completely foreign origin
    resp1 = await root_redirect(make_req({"referer": "https://attacker.test"}))
    assert resp1.status_code == 307
    parsed1 = urllib.parse.urlsplit(resp1.headers["location"])
    assert parsed1.hostname != "attacker.test"
    assert parsed1.hostname in trusted_hosts

    # Attack 2: Lookalike subdomain/domain
    resp2 = await root_redirect(make_req({"referer": "https://compass-kappa-nine.vercel.app.attacker.test"}))
    assert resp2.status_code == 307
    parsed2 = urllib.parse.urlsplit(resp2.headers["location"])
    assert parsed2.hostname != "compass-kappa-nine.vercel.app.attacker.test"
    assert parsed2.hostname in trusted_hosts

    # Attack 3: Userinfo lookalike
    resp3 = await root_redirect(make_req({"referer": "http://localhost:5173@attacker.test"}))
    assert resp3.status_code == 307
    parsed3 = urllib.parse.urlsplit(resp3.headers["location"])
    assert parsed3.hostname != "attacker.test"
    assert parsed3.hostname in trusted_hosts

    # Attack 4: Prefix matching spoofing
    resp4 = await root_redirect(make_req({"referer": "http://localhost.attacker.test"}))
    assert resp4.status_code == 307
    parsed4 = urllib.parse.urlsplit(resp4.headers["location"])
    assert parsed4.hostname != "localhost.attacker.test"
    assert parsed4.hostname in trusted_hosts

    # Legitimate origin redirect
    resp_legit = await root_redirect(make_req({"referer": "https://compass-kappa-nine.vercel.app/some/page"}))
    assert resp_legit.status_code == 307
    parsed_legit = urllib.parse.urlsplit(resp_legit.headers["location"])
    assert parsed_legit.scheme == "https"
    assert parsed_legit.hostname == "compass-kappa-nine.vercel.app"


def test_validate_trusted_origin_exact_matching():
    # Attacks that prefix matching would naively allow:
    assert not _validate_trusted_origin(make_req({"origin": "http://localhost:5173.attacker.test"}))
    assert not _validate_trusted_origin(make_req({"origin": "https://compass-kappa-nine.vercel.app.attacker.test"}))
    assert not _validate_trusted_origin(make_req({"origin": "http://localhost:5173@attacker.test"}))
    assert not _validate_trusted_origin(make_req({"origin": "http://localhost.attacker.test"}))
    assert not _validate_trusted_origin(make_req({"origin": "https://compass-farmlytics.vercel.app.phishing.test"}))

    # Legitimate origins:
    assert _validate_trusted_origin(make_req({"origin": "http://localhost:5173"}))
    assert _validate_trusted_origin(make_req({"origin": "https://compass-kappa-nine.vercel.app"}))
    assert _validate_trusted_origin(make_req({"origin": "http://localhost:3000"}))
    assert _validate_trusted_origin(make_req({"origin": "https://compass-backend-qryu.onrender.com"}))

    # Missing origin (CLI / direct requests allowed):
    assert _validate_trusted_origin(make_req({}))
