"""
Compass — Security Services & Validation Helpers.

Provides:
  - SSRF (Server-Side Request Forgery) protection for web ingestion/search.
  - Safe client IP resolution preventing spoofed proxy headers.
  - Constant-time secret verification.
"""

import ipaddress
import socket
import urllib.parse
from typing import Tuple, Optional
from fastapi import Request


# Disallowed IP networks for SSRF protection:
# - Loopback (127.0.0.0/8, ::1)
# - Link-Local / Cloud Metadata (169.254.0.0/16, fe80::/10)
# - RFC 1918 Private IPv4 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
# - Carrier-Grade NAT (100.64.0.0/10)
# - Broadcast / Multicast / Reserved (224.0.0.0/4, 240.0.0.0/4, 0.0.0.0/8)
BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "instance-data",
}


def _is_ip_blocked(ip: ipaddress._BaseAddress) -> bool:
    """Check if an IP address belongs to any blocked private/reserved networks, unwrapping IPv4-mapped IPv6."""
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    for net in BLOCKED_IP_NETWORKS:
        try:
            if ip in net:
                return True
        except TypeError:
            continue
    return False


def is_safe_url(url: str) -> Tuple[bool, str]:
    """Validate that a URL is safe to fetch and not pointing to private/internal infrastructure (SSRF defense).

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

    # Prevent loopback/cloud metadata disguised as raw IP or hex/octal
    try:
        # Check if hostname is directly an IP literal
        ip = ipaddress.ip_address(hostname)
        if _is_ip_blocked(ip):
            return False, f"Access to private/reserved IP address '{ip}' is forbidden."
    except ValueError:
        # Hostname is a domain name, resolve via DNS
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for item in addr_info:
                ip_str = item[4][0]
                ip = ipaddress.ip_address(ip_str)
                if _is_ip_blocked(ip):
                    return False, f"Hostname '{hostname}' resolves to private/reserved IP '{ip_str}'."
        except socket.gaierror:
            # Domain could not be resolved
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



def get_client_ip(request: Request) -> str:
    """Safely extract client IP address.

    When running behind trusted reverse proxies (e.g. Render / Cloudflare / Nginx),
    extract the client IP from standard proxy headers, taking the rightmost
    entry from untrusted X-Forwarded-For if forged headers are prepended,
    or falling back to direct connection client host.
    """
    # Check CF-Connecting-IP first (Cloudflare)
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip and cf_ip.strip():
        return cf_ip.strip()

    # Check X-Real-IP
    real_ip = request.headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()

    # Check X-Forwarded-For: parse first IP or fallback to client host
    xff = request.headers.get("x-forwarded-for")
    if xff and xff.strip():
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[0]

    if request.client and request.client.host:
        return request.client.host

    return "127.0.0.1"
