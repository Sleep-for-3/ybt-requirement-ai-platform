#!/usr/bin/env python3
"""Loopback-only HTTP CONNECT proxy over a reverse SSH tunnel.

The proxy forwards encrypted HTTPS bytes and does not inspect API requests.
It is intended for a server whose SSH client can reach this workstation while
the server itself cannot reach the provider directly.
"""

from __future__ import annotations

import argparse
import logging
import select
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import paramiko


def parse_credentials(path: Path) -> tuple[str, int, str, str]:
    text = path.read_text(encoding="utf-8-sig").strip()
    fields = text.split()
    if len(fields) < 2:
        raise ValueError("credential file must contain host:port and user/password")
    host, port_text = fields[0].rsplit(":", 1)
    user, password = fields[1].split("/", 1)
    return host, int(port_text), user, password


def close_quietly(sock: object) -> None:
    try:
        sock.close()  # type: ignore[attr-defined]
    except Exception:
        pass


def bridge(left: object, right: object) -> None:
    sockets = [left, right]
    try:
        while True:
            readable, _, _ = select.select(sockets, [], [], 60)
            if not readable:
                continue
            for source in readable:
                data = source.recv(65536)  # type: ignore[attr-defined]
                if not data:
                    return
                target = right if source is left else left
                target.sendall(data)  # type: ignore[attr-defined]
    except (OSError, EOFError, paramiko.SSHException):
        return
    finally:
        close_quietly(left)
        close_quietly(right)


class ConnectProxy:
    def __init__(
        self,
        host: str,
        port: int,
        upstream_proxy: tuple[str, int] | None,
    ) -> None:
        self.host = host
        self.port = port
        self.upstream_proxy = upstream_proxy
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind((host, port))
        self.listener.listen(32)
        self.listener.settimeout(1)

    def close(self) -> None:
        close_quietly(self.listener)

    def serve_forever(self) -> None:
        logging.info("local CONNECT proxy listening on %s:%d", self.host, self.port)
        while True:
            try:
                client, address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(
                target=self.handle_client,
                args=(client, address),
                daemon=True,
            ).start()

    def connect_target(self, target_host: str, target_port: int) -> socket.socket:
        if self.upstream_proxy is None:
            return socket.create_connection((target_host, target_port), timeout=12)

        proxy_host, proxy_port = self.upstream_proxy
        upstream = socket.create_connection((proxy_host, proxy_port), timeout=12)
        upstream.settimeout(15)
        connect_host = f"[{target_host}]" if ":" in target_host else target_host
        request = (
            f"CONNECT {connect_host}:{target_port} HTTP/1.1\r\n"
            f"Host: {connect_host}:{target_port}\r\n"
            "Proxy-Connection: Keep-Alive\r\n"
            "\r\n"
        ).encode("ascii")
        try:
            upstream.sendall(request)
            response = b""
            while b"\r\n\r\n" not in response and len(response) < 8192:
                chunk = upstream.recv(4096)
                if not chunk:
                    raise OSError("upstream proxy closed during CONNECT")
                response += chunk
            status_line = response.split(b"\r\n", 1)[0].decode("ascii", "replace")
            status_parts = status_line.split()
            if len(status_parts) < 2 or status_parts[1] != "200":
                raise OSError(f"upstream proxy CONNECT failed: {status_line}")
            return upstream
        except Exception:
            close_quietly(upstream)
            raise

    def handle_client(self, client: socket.socket, address: object) -> None:
        upstream: socket.socket | None = None
        try:
            client.settimeout(15)
            request = b""
            while b"\r\n\r\n" not in request and len(request) < 16384:
                chunk = client.recv(4096)
                if not chunk:
                    return
                request += chunk
            first_line = request.split(b"\r\n", 1)[0].decode("ascii", "replace")
            parts = first_line.split()
            if len(parts) != 3 or parts[0].upper() != "CONNECT":
                client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n")
                return
            target = parts[1]
            if ":" in target and target.rsplit(":", 1)[1].isdigit():
                target_host, target_port_text = target.rsplit(":", 1)
                target_port = int(target_port_text)
            else:
                target_host, target_port = target, 443
            upstream = self.connect_target(target_host, target_port)
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            bridge(client, upstream)
        except (OSError, ValueError) as error:
            logging.warning("proxy connection %s failed: %s", address, error)
            try:
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
        finally:
            close_quietly(client)
            close_quietly(upstream)


def run_tunnel(
    credentials: Path,
    remote_port: int,
    local_proxy_port: int,
    reconnect_seconds: int,
    upstream_proxy: tuple[str, int] | None,
) -> None:
    proxy = ConnectProxy("127.0.0.1", local_proxy_port, upstream_proxy)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()

    remote_host, remote_ssh_port, username, password = parse_credentials(credentials)
    logging.info("reverse tunnel target: %s:%d -> local proxy 127.0.0.1:%d", remote_host, remote_port, local_proxy_port)
    if upstream_proxy:
        logging.info("local outbound proxy: %s:%d", *upstream_proxy)

    try:
        while True:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(
                    remote_host,
                    port=remote_ssh_port,
                    username=username,
                    password=password,
                    timeout=20,
                    auth_timeout=20,
                    banner_timeout=20,
                    look_for_keys=False,
                    allow_agent=False,
                )
                transport = client.get_transport()
                if transport is None or not transport.is_active():
                    raise RuntimeError("SSH transport is not active")

                def handle_channel(channel: paramiko.Channel, origin: object, server: object) -> None:
                    try:
                        local = socket.create_connection(("127.0.0.1", local_proxy_port), timeout=12)
                        bridge(channel, local)
                    except OSError as error:
                        logging.debug("reverse channel failed: %s", error)
                        close_quietly(channel)

                transport.request_port_forward("127.0.0.1", remote_port)
                logging.info("reverse SSH tunnel is active")
                while transport.is_active():
                    channel = transport.accept(1)
                    if channel is not None:
                        logging.info("received reverse connection from server")
                        threading.Thread(
                            target=handle_channel,
                            args=(channel, None, None),
                            daemon=True,
                        ).start()
                    time.sleep(2)
            except Exception as error:
                logging.warning("tunnel disconnected: %s", error)
            finally:
                client.close()
            time.sleep(reconnect_seconds)
    finally:
        proxy.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--remote-port", type=int, default=18080)
    parser.add_argument("--local-proxy-port", type=int, default=18081)
    parser.add_argument("--reconnect-seconds", type=int, default=5)
    parser.add_argument("--upstream-proxy", help="HTTP CONNECT proxy, e.g. http://127.0.0.1:7897")
    parser.add_argument("--log-file", type=Path)
    args = parser.parse_args()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    upstream_proxy = None
    if args.upstream_proxy:
        parsed_proxy = urlsplit(args.upstream_proxy)
        if parsed_proxy.scheme not in {"http", "https"} or not parsed_proxy.hostname or not parsed_proxy.port:
            parser.error("--upstream-proxy must be an HTTP proxy URL with host and port")
        if parsed_proxy.username or parsed_proxy.password:
            parser.error("proxy authentication in URL is not supported")
        upstream_proxy = (parsed_proxy.hostname, parsed_proxy.port)
    run_tunnel(args.credentials, args.remote_port, args.local_proxy_port, args.reconnect_seconds, upstream_proxy)


if __name__ == "__main__":
    main()
