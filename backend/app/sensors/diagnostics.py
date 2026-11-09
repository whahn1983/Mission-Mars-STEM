"""Read-only network diagnostics for the EVB Lite discovery phase.

Every check here is passive: DNS lookup, TCP connect, and HTTP GET. No
request modifies the device. Probe responses are saved under
``<data_dir>/discovery`` so they can be quoted in
docs/evb-lite-integration.md.
"""

from __future__ import annotations

import asyncio
import base64
import re
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

MAX_BODY_BYTES = 256 * 1024


def _hints_for(error: str, host: str) -> list[str]:
    hints: list[str] = []
    e = error.lower()
    if host.endswith(".local"):
        hints.append(
            "'.local' names use mDNS, which usually does not resolve inside Docker containers. "
            "Use the sensor's IP address from the UniFi client list instead."
        )
    if "name or service not known" in e or "nodename" in e or "getaddrinfo" in e or "resolve" in e:
        hints.append("The hostname could not be resolved. Use the numeric IP address.")
    if "timed out" in e or "timeout" in e:
        hints.extend(
            [
                "Timeout: confirm the laptop and sensor are on the same network/VLAN.",
                "Check that UniFi 'Client Device Isolation' is OFF for this Wi-Fi network.",
                "The sensor must be on 2.4 GHz Wi-Fi; check it is powered and shows as connected in UniFi.",
            ]
        )
    if "refused" in e:
        hints.append("Connection refused: the device is reachable but nothing is listening on that port.")
    if "unreachable" in e or "no route" in e:
        hints.append("Network unreachable: Docker Desktop may not be routing to the LAN; restart Docker Desktop.")
    return hints


async def run_diagnostics(host: str, port: int = 80, timeout_s: float = 5.0, extra_paths: list[str] | None = None) -> dict:
    host = host.strip()
    report: dict = {
        "host": host,
        "port": port,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps": [],
        "hints": [],
        "ok": False,
    }
    if not host:
        report["steps"].append({"name": "config", "ok": False, "detail": "No sensor address configured."})
        report["hints"].append("Enter the sensor's IP address (find it in the UniFi client list / DHCP leases).")
        return report

    # 1. DNS
    t0 = time.monotonic()
    try:
        infos = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout=timeout_s
        )
        addrs = sorted({i[4][0] for i in infos})
        report["steps"].append({"name": "resolve", "ok": True, "detail": ", ".join(addrs),
                                "ms": round((time.monotonic() - t0) * 1000, 1)})
    except Exception as exc:  # noqa: BLE001 — report every failure mode
        msg = f"{type(exc).__name__}: {exc}"
        report["steps"].append({"name": "resolve", "ok": False, "detail": msg})
        report["hints"].extend(_hints_for(msg or "resolve", host))
        return report

    # 2. TCP
    t0 = time.monotonic()
    try:
        _r, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout_s)
        w.close()
        try:
            await w.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        report["steps"].append({"name": "tcp_connect", "ok": True, "detail": f"port {port} open",
                                "ms": round((time.monotonic() - t0) * 1000, 1)})
    except Exception as exc:  # noqa: BLE001
        msg = f"{type(exc).__name__}: {exc}" if str(exc) else f"{type(exc).__name__}: timed out"
        report["steps"].append({"name": "tcp_connect", "ok": False, "detail": msg})
        report["hints"].extend(_hints_for(msg, host))
        return report

    # 3. HTTP GET of the web portal root and any extra (read-only) paths.
    for path in ["/"] + list(extra_paths or []):
        res = await http_probe(host, port, path, timeout_s=timeout_s)
        step = {"name": f"http_get {path}", "ok": res.get("status") is not None, "detail": res.get("summary"),
                "ms": res.get("elapsed_ms")}
        report["steps"].append(step)
        if res.get("error"):
            report["hints"].extend(_hints_for(res["error"], host))
    report["ok"] = all(s["ok"] for s in report["steps"])
    report["hints"] = list(dict.fromkeys(report["hints"]))
    return report


async def http_probe(host: str, port: int, path: str, *, timeout_s: float = 5.0, save_dir: Path | None = None) -> dict:
    """HTTP GET only. Returns status, headers and (truncated) body."""
    if not path.startswith("/"):
        path = "/" + path
    h = f"[{host}]" if ":" in host and not host.startswith("[") else host
    url = f"http://{h}{'' if port == 80 else f':{port}'}{path}"
    t0 = time.monotonic()
    out: dict = {"url": url, "method": "GET"}
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False, trust_env=False) as client:
            resp = await client.get(url, headers={"User-Agent": "MissionMarsLab/1.0 (diagnostics)"})
    except httpx.HTTPError as exc:
        out["error"] = f"{type(exc).__name__}: {exc}" or type(exc).__name__
        out["summary"] = out["error"]
        out["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
        return out
    body = resp.content[:MAX_BODY_BYTES]
    ctype = resp.headers.get("content-type", "")
    out.update(
        {
            "status": resp.status_code,
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
            "headers": dict(resp.headers),
            "content_type": ctype,
            "length": len(resp.content),
            "truncated": len(resp.content) > MAX_BODY_BYTES,
        }
    )
    try:
        text = body.decode("utf-8")
        out["body_text"] = text
        m = re.search(r"<title>(.*?)</title>", text, re.I | re.S)
        if m:
            out["html_title"] = m.group(1).strip()[:200]
    except UnicodeDecodeError:
        out["body_base64"] = base64.b64encode(body).decode()
    out["summary"] = f"HTTP {resp.status_code} {ctype or 'no content-type'} {len(resp.content)} bytes" + (
        f" — title '{out['html_title']}'" if out.get("html_title") else ""
    )
    if save_dir is not None:
        save_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", path.strip("/")) or "root"
        fn = save_dir / f"{stamp}_{safe}.txt"
        header = "\n".join(f"{k}: {v}" for k, v in resp.headers.items())
        fn.write_bytes(
            f"GET {url}\nHTTP {resp.status_code}\n{header}\n\n".encode() + resp.content[: 4 * MAX_BODY_BYTES]
        )
        out["saved_to"] = str(fn)
    return out
