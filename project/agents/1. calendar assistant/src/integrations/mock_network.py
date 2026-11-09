"""Reject external networking in the explicitly selected offline agent process."""

import ipaddress
import socket


def install_mock_network_guard():
    if getattr(socket, "_calendar_mock_guard", False):
        return
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_resolve = socket.getaddrinfo

    def check(host):
        if host in {None, "localhost"}:
            return
        try:
            allowed = ipaddress.ip_address(host).is_loopback
        except ValueError:
            allowed = False
        if not allowed:
            raise RuntimeError("La demo mock bloquea las conexiones externas.")

    def connect(sock, address):
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            check(address[0])
        return original_connect(sock, address)

    def connect_ex(sock, address):
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            check(address[0])
        return original_connect_ex(sock, address)

    def resolve(host, *args, **kwargs):
        check(host)
        return original_resolve(host, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = resolve
    socket._calendar_mock_guard = True
