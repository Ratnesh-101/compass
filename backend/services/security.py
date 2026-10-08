"""
Compass — Security Services & Validation Helpers.

Provides:
  - SSRF (Server-Side Request Forgery) protection for web ingestion/search.
  - DNS-rebinding safe HTTP fetching.
  - Safe client IP resolution with configurable proxy hops preventing spoofing.
  - Constant-time secret verification.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import urllib.parse
from typing import Any, Dict, Optional, Tuple, Union
from fastapi import Request
import httpx

logger = logging.getLogger("compass.security")

BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "instance-data",
}


def _is_ip_blocked(ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address]) -> bool:
    """Check if an IP address belongs to any blocked non-global networks, unwrapping IPv4-mapped IPv6."""
    if getattr(ip, "ipv4_mapped", None):
        mapped = ip.ipv4_mapped
        if mapped is not None:
            ip = mapped
    if not getattr(ip, "is_global", False):
        return True
    if str(ip) in ("0.0.0.0", "::", "::1", "127.0.0.1"):  # nosec B104 - SSRF filter, not a socket bind
        return True
    return False


def is_valid_ip(ip_str: str) -> bool:
    """Validate whether a string is a valid IPv4 or IPv6 address literal."""
    if not ip_str or not isinstance(ip_str, str):
        return False
    try:
        ipaddress.ip_address(ip_str.strip())
        return True
    except (ValueError, AttributeError):
        return False



def is_safe_url(url: str) -> Tuple[bool, str]:
    """Validate that a URL is safe to fetch and not pointing to private/internal infrastructure (SSRF defense).

    Detects:
      - Raw IP literals (IPv4 & IPv6)
      - IPv6-mapped IPv4 addresses (::ffff:127.0.0.1)
      - Decimal and Hex encoded IPs (e.g. 2130706433 or 0x7f000001)
      - Octal dotted IPs (e.g. 0177.0.0.1)
      - Abbreviated IPv4 (e.g. 127.1)
      - Loopback, Link-Local, RFC1918 Private, Carrier-Grade NAT (100.64.0.0/10), Multicast
      - 0.0.0.0 and unspecified IPs
      - Cloud metadata hosts (169.254.169.254, metadata.google.internal)

    Returns (is_safe, error_reason).
    """
    if not url or not isinstance(url, str):
        return False, "URL must be a non-empty string"

    parsed = urllib.parse.urlsplit(url.strip())

    # Scheme validation: strictly http or https
    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Unsupported URL scheme '{parsed.scheme}'. Only http and https are allowed."

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False, "Invalid URL: missing hostname"

    # Strip bracket notation from IPv6 if present
    if hostname.startswith("[") and hostname.endswith("]"):
        hostname = hostname[1:-1].strip()

    if hostname in BLOCKED_HOSTNAMES:
        return False, f"Access to blocked internal hostname '{hostname}' is forbidden."

    # Prevent loopback/cloud metadata disguised as decimal or hex integer
    if hostname.isdigit() or hostname.startswith("0x"):
        try:
            val = int(hostname, 0)
        except ValueError:
            return False, f"Invalid numeric hostname encoding '{hostname}'."
        if 0 <= val <= 0xFFFFFFFF:
            ip = ipaddress.IPv4Address(val)
            if _is_ip_blocked(ip):
                return False, f"Access to non-global IP address '{ip}' is forbidden."
            return True, ""
        else:
            return False, f"Numeric IP value out of range '{hostname}'."

    # Prevent octal dotted notation or abbreviated IPv4 (e.g. 0177.0.0.1 or 127.1)
    parts = hostname.split(".")
    if 1 <= len(parts) <= 4 and all(p.isdigit() or p.startswith("0x") for p in parts if p):
        try:
            packed = socket.inet_aton(hostname)
            ip_from_aton = ipaddress.IPv4Address(packed)
            if _is_ip_blocked(ip_from_aton):
                return False, f"Access to non-global IP address '{ip_from_aton}' is forbidden."
            return True, ""
        except (socket.error, OSError):
            return False, f"Invalid IP literal format '{hostname}'."

    try:
        # Check if hostname is directly an IP literal
        ip = ipaddress.ip_address(hostname)
        if _is_ip_blocked(ip):
            return False, f"Access to non-global IP address '{ip}' is forbidden."
    except ValueError:
        # Hostname is a domain name, resolve via DNS
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for item in addr_info:
                ip_str = item[4][0]
                ip = ipaddress.ip_address(ip_str)
                if _is_ip_blocked(ip):
                    return False, f"Hostname '{hostname}' resolves to non-global IP '{ip_str}'."
        except socket.gaierror:
            return False, f"Could not resolve hostname '{hostname}'."
        except Exception as e:
            return False, f"DNS resolution failed for '{hostname}': {e}"

    # Port restriction: standard HTTP/HTTPS ports only
    port = parsed.port
    if port and port not in (80, 443, 8080, 8443):
        return False, f"Access to port {port} is not permitted for web ingestion."

    return True, ""


def is_safe_redirect(source_url: str, location: str) -> Tuple[bool, str, str]:
    """Validate a redirect target from a given source URL.

    Resolves relative redirects against source_url and ensures the destination
    is not targeting internal/private addresses (SSRF defense).
    Returns (is_safe, resolved_url, error_reason).
    """
    if not location or not isinstance(location, str):
        return False, "", "Redirect location must be a non-empty string"
    resolved_url = urllib.parse.urljoin(source_url.strip(), location.strip())
    safe, reason = is_safe_url(resolved_url)
    if not safe:
        return False, resolved_url, f"Redirect destination rejected: {reason}"
    return True, resolved_url, ""


async def safe_http_get(
    url: str,
    max_redirects: int = 3,
    timeout: float = 10.0,
    headers: Optional[dict] = None,
) -> Tuple[int, str, dict]:
    """Execute an outbound HTTP GET with strict SSRF validation and DNS rebinding protection.

    Pins the connection to the pre-validated IP so DNS cannot change between check and fetch.
    Uses non-blocking loop.getaddrinfo, keeps TLS verification ON, and passes sni_hostname.
    Returns (status_code, text, response_headers).
    """
    current_url = url
    loop = asyncio.get_running_loop()

    for hop in range(max_redirects + 1):
        safe, reason = is_safe_url(current_url)
        if not safe:
            raise ValueError(f"SSRF blocked on hop {hop}: {reason}")

        parsed = urllib.parse.urlsplit(current_url)
        hostname = (parsed.hostname or "").strip()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        # Non-blocking async DNS resolution to pre-validated IP
        try:
            addr_info = await loop.getaddrinfo(hostname, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
            if not addr_info:
                raise ValueError(f"Could not resolve hostname '{hostname}'")
            resolved_ip = addr_info[0][4][0]
            ip_obj = ipaddress.ip_address(resolved_ip)
            if _is_ip_blocked(ip_obj):
                raise ValueError(f"DNS rebinding blocked: '{hostname}' resolved to non-global IP '{resolved_ip}'")
        except socket.gaierror as e:
            raise ValueError(f"Could not resolve hostname '{hostname}': {e}")

        req_headers = dict(headers or {})
        req_headers["Host"] = hostname

        path_query = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")

        # Pinned-IP transport: connect directly to resolved_ip with TLS SNI verification
        resolved_ip_str = str(resolved_ip)
        target_ip = f"[{resolved_ip_str}]" if ":" in resolved_ip_str else resolved_ip_str
        pinned_target = f"{parsed.scheme}://{target_ip}:{port}{path_query}"

        async with httpx.AsyncClient(timeout=timeout, verify=True, follow_redirects=False) as client:
            extensions: Dict[str, Any] = {}
            if parsed.scheme == "https":
                extensions["sni_hostname"] = hostname.encode("ascii")

            req = client.build_request("GET", pinned_target, headers=req_headers, extensions=extensions)
            resp = await client.send(req)

            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location")
                if not loc:
                    return resp.status_code, resp.text, dict(resp.headers)
                redir_safe, next_url, redir_err = is_safe_redirect(current_url, loc)
                if not redir_safe:
                    raise ValueError(f"SSRF redirect blocked: {redir_err}")
                current_url = next_url
                continue
            return resp.status_code, resp.text, dict(resp.headers)

    raise ValueError(f"Too many redirects ({max_redirects})")


import hmac
import hashlib
import time


def verify_edge_signature(sig_header: Optional[str], secret: str, max_age_seconds: int = 300) -> bool:
    """Verify HMAC SHA-256 edge signature.
    Supports:
      1. 'client_ip|timestamp|signature' (over 'client_ip|timestamp')
      2. '<timestamp>.<signature>' (over '<timestamp>')
    """
    if not sig_header or not secret:
        return False
    try:
        if "|" in sig_header:
            parts = sig_header.split("|")
            if len(parts) == 3:
                client_ip, ts_str, expected_hmac = parts
                ts = int(ts_str)
                now = int(time.time())
                if abs(now - ts) > max_age_seconds:
                    return False
                if not is_valid_ip(client_ip):
                    return False
                payload = f"{client_ip}|{ts_str}"
                computed = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
                return hmac.compare_digest(computed, expected_hmac)
    except Exception:
        return False
    return False


def extract_signed_edge_client_ip(sig_header: Optional[str], secret: str, max_age_seconds: int = 300) -> Optional[str]:
    """If sig_header is a valid 'client_ip|timestamp|signature', return the validated client_ip."""
    if not sig_header or not secret or "|" not in sig_header:
        return None
    try:
        parts = sig_header.split("|")
        if len(parts) == 3:
            client_ip, ts_str, expected_hmac = parts
            ts = int(ts_str)
            now = int(time.time())
            if abs(now - ts) > max_age_seconds:
                return None
            if not is_valid_ip(client_ip):
                return None
            payload = f"{client_ip}|{ts_str}"
            computed = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
            if hmac.compare_digest(computed, expected_hmac):
                return client_ip
    except Exception:
        return None
    return None


def get_client_ip(request: Request) -> str:
    """Safely extract client IP address behind trusted reverse proxies (Render / Cloudflare / Vercel).

    Prevents header spoofing attacks:
    - If TRUST_CF_CONNECTING_IP is True, checks cf-connecting-ip.
    - If valid edge signature header is present ('client_ip|timestamp|signature' signed with EDGE_HMAC_SECRET),
      the backend trusts that signed client_ip.
    - If valid edge signature over timestamp only is present (legacy), trusts parts[-2] in XFF.
    - Evaluates TRUSTED_PROXY_HOPS: extracts parts[-hops] if len(parts) >= hops, otherwise falls back to TCP peer.
    - If direct connection without valid proxy chain/signature, uses TCP peer address.
    """
    from backend.config import get_settings
    settings = get_settings()

    # 0. Cloudflare connecting IP (only if explicitly trusted)
    if getattr(settings, "TRUST_CF_CONNECTING_IP", False):
        cf_ip = request.headers.get("cf-connecting-ip")
        if cf_ip and is_valid_ip(cf_ip.strip()):
            return cf_ip.strip()

    # 1. Edge Signature Validation (Vercel Edge Middleware -> Backend)
    edge_sig = request.headers.get("x-compass-edge-sig") or request.headers.get("x-vercel-edge-sig")
    edge_secret = (getattr(settings, "EDGE_HMAC_SECRET", "") or getattr(settings, "VERCEL_EDGE_SECRET", "") or "").strip()

    if edge_sig and edge_secret:
        # Check signed client_ip format: client_ip|timestamp|signature
        signed_ip = extract_signed_edge_client_ip(edge_sig, edge_secret)
        if signed_ip:
            return signed_ip

    # 2. Configurable Trusted Proxy Hops (Nth-from-right extraction)
    hops = int(getattr(settings, "TRUSTED_PROXY_HOPS", 1))
    xff = request.headers.get("x-forwarded-for")
    if xff and xff.strip():
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if len(parts) >= hops:
            target_ip = parts[-hops]
            if is_valid_ip(target_ip):
                return target_ip
        else:
            # Chain is shorter than expected trusted proxy hops -> spoof/tamper fallback to TCP peer
            if request.client and request.client.host and is_valid_ip(request.client.host):
                return request.client.host

    # 3. Direct TCP peer address
    if request.client and request.client.host and is_valid_ip(request.client.host):
        return request.client.host

    return "127.0.0.1"


def is_edge_ip_trusted(request: Request) -> bool:
    """Determine whether the client IP in this request has been cryptographically verified.
    
    Returns True if:
      - Valid edge HMAC signature is present and validated against EDGE_HMAC_SECRET (or VERCEL_EDGE_SECRET).
      - Or TRUST_CF_CONNECTING_IP is True and cf-connecting-ip is present.
    Returns False when behind a reverse proxy (e.g. Vercel) without a verified signature,
    meaning all users share the proxy IP and IP-based rate limiting would pool all users together.
    """
    from backend.config import get_settings
    settings = get_settings()

    if getattr(settings, "TRUST_CF_CONNECTING_IP", False):
        cf_ip = request.headers.get("cf-connecting-ip")
        if cf_ip and is_valid_ip(cf_ip.strip()):
            return True

    edge_sig = request.headers.get("x-compass-edge-sig") or request.headers.get("x-vercel-edge-sig")
    edge_secret = (getattr(settings, "EDGE_HMAC_SECRET", "") or getattr(settings, "VERCEL_EDGE_SECRET", "") or "").strip()
    if edge_sig and edge_secret:
        signed_ip = extract_signed_edge_client_ip(edge_sig, edge_secret)
        if signed_ip:
            return True

    # If there is no proxy header at all (direct connection, not proxied), consider peer IP trusted
    xff = request.headers.get("x-forwarded-for")
    if not xff:
        return True

    return False

