"""Explicit direct-office-network authorization; never use forwarded client claims."""

import ipaddress
import re
from dataclasses import dataclass

from starlette.datastructures import URL
from starlette.responses import JSONResponse

OFFICE_ACTOR = "Office LAN user (shared access; individual identity unverified)"
VERIFIED = "jobmitra_office_lan_verified"
PRIVATE = tuple(
    map(
        ipaddress.ip_network,
        (
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "127.0.0.0/8",
            "fc00::/7",
            "::1/128",
        ),
    )
)


def address(value):
    if not isinstance(value, str) or "%" in value:
        raise ValueError("Use a direct IP address")
    parsed = ipaddress.ip_address(value)
    return getattr(parsed, "ipv4_mapped", None) or parsed


@dataclass(frozen=True)
class OfficePolicy:
    enabled: bool
    networks: tuple = ()
    hosts: frozenset = frozenset()

    @classmethod
    def from_settings(cls, settings):
        if not settings.office_lan_enabled:
            return cls(False)
        if settings.unified_v12_local_direct_editing:
            raise RuntimeError("Choose Office LAN mode or loopback direct editing, not both.")
        if not (settings.unified_v12_enabled and settings.ats_v2_enabled):
            raise RuntimeError("Office LAN mode requires ATS V2 and Unified V12 enabled.")
        try:
            values = settings.office_lan_cidrs.split(",")
            networks = tuple(ipaddress.ip_network(v.strip(), strict=True) for v in values)
            if not networks or any(
                not any(n.version == p.version and n.subnet_of(p) for p in PRIVATE)
                for n in networks
            ):
                raise ValueError
            hosts = frozenset(
                h.strip().lower() for h in settings.office_lan_hosts.split(",") if h.strip()
            )
            if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", h) for h in hosts):
                raise ValueError
        except ValueError:
            raise RuntimeError(
                "Office LAN mode requires explicit private/loopback CIDRs "
                "and valid optional hostnames."
            ) from None
        return cls(True, networks, hosts)

    def contains(self, value):
        return any(value.version == n.version and value in n for n in self.networks)

    def allows(self, scope):
        try:
            peer = scope.get("client")
            if not peer or not self.contains(address(peer[0])):
                return False
            headers = scope.get("headers", [])
            # Uvicorn may rewrite scope['client'] before application middleware.
            # It retains these headers, so reject them even after such rewriting.
            if any(
                k.lower() in {b"forwarded", b"x-real-ip", b"true-client-ip", b"cf-connecting-ip"}
                or k.lower().startswith(b"x-forwarded-")
                for k, _ in headers
            ):
                return False
            hosts = [v.decode("latin1") for k, v in headers if k.lower() == b"host"]
            if len(hosts) != 1 or any(c in hosts[0] for c in "@/\\"):
                return False
            host = URL(scope=scope).hostname
            if not host:
                return False
            if host.lower() == "localhost":
                return self.contains(address("127.0.0.1")) or self.contains(address("::1"))
            try:
                return self.contains(address(host))
            except ValueError:
                return host.lower() in self.hosts
        except (ValueError, TypeError, UnicodeError):
            return False


class OfficeLANGuard:
    """Apply one boundary to all pages, APIs, static assets and document routes."""

    def __init__(self, app, policy):
        self.app, self.policy = app, policy

    async def __call__(self, scope, receive, send):
        if self.policy.enabled and scope["type"] in {"http", "websocket"}:
            if not self.policy.allows(scope):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                return await JSONResponse(
                    {
                        "detail": "Office LAN access requires a direct connection "
                        "from an allowed office network."
                    },
                    status_code=403,
                )(scope, receive, send)
            scope.setdefault("state", {})[VERIFIED] = True
        await self.app(scope, receive, send)
