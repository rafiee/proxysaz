"""Parse and normalize Telegram proxy links.

Accepted inputs (admin just pastes one):
  - https://t.me/proxy?server=1.2.3.4&port=443&secret=ee...
  - tg://proxy?server=1.2.3.4&port=443&secret=ee...
  - https://t.me/socks?server=1.2.3.4&port=1080&user=u&pass=p
  - tg://socks?server=...&port=...
  - raw  host:port:secret          (mtproto)
  - raw  host:port:user:pass       (socks)

Output: canonical https://t.me/... link + parsed parts.
"""
from urllib.parse import urlsplit, parse_qs, urlencode


class ProxyParseError(ValueError):
    pass


def _canonical(kind: str, params: dict) -> str:
    base = "https://t.me/proxy" if kind == "mtproto" else "https://t.me/socks"
    return base + "?" + urlencode(params)


def parse_proxy_link(raw: str) -> dict:
    """Return dict: type, server, port, secret, user, password, link.

    Raises ProxyParseError on invalid input.
    """
    if not raw:
        raise ProxyParseError("empty input")
    raw = raw.strip()

    # URL forms
    if "proxy" in raw.lower() or "socks" in raw.lower() or "://" in raw:
        parts = urlsplit(raw)
        path = (parts.path or "").lower()
        host_tag = (parts.netloc or "").lower()
        is_socks = "socks" in path or "socks" in host_tag
        q = parse_qs(parts.query)

        def g(key):
            v = q.get(key, [None])[0]
            return v

        server = g("server")
        port = g("port")
        if not server or not port:
            raise ProxyParseError("missing server/port in link")
        try:
            port_i = int(port)
        except ValueError:
            raise ProxyParseError("port is not a number")

        if is_socks:
            params = {"server": server, "port": port_i}
            user = g("user")
            pw = g("pass")
            if user:
                params["user"] = user
            if pw:
                params["pass"] = pw
            return {
                "type": "socks", "server": server, "port": port_i,
                "secret": None, "user": user, "password": pw,
                "link": _canonical("socks", params),
            }
        else:
            secret = g("secret")
            if not secret:
                raise ProxyParseError("missing secret in mtproto link")
            params = {"server": server, "port": port_i, "secret": secret}
            return {
                "type": "mtproto", "server": server, "port": port_i,
                "secret": secret, "user": None, "password": None,
                "link": _canonical("mtproto", params),
            }

    # Raw colon forms
    bits = raw.split(":")
    if len(bits) == 3:
        server, port, secret = bits
        try:
            port_i = int(port)
        except ValueError:
            raise ProxyParseError("port is not a number")
        params = {"server": server, "port": port_i, "secret": secret}
        return {
            "type": "mtproto", "server": server, "port": port_i,
            "secret": secret, "user": None, "password": None,
            "link": _canonical("mtproto", params),
        }
    if len(bits) == 4:
        server, port, user, pw = bits
        try:
            port_i = int(port)
        except ValueError:
            raise ProxyParseError("port is not a number")
        params = {"server": server, "port": port_i, "user": user, "pass": pw}
        return {
            "type": "socks", "server": server, "port": port_i,
            "secret": None, "user": user, "password": pw,
            "link": _canonical("socks", params),
        }

    raise ProxyParseError("unrecognized proxy format")
