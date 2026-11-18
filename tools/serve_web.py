"""Serve the phone's web page over HTTPS on the local network, to try PhoneDeck with a second phone.

Web Bluetooth and WebCrypto only work on a secure page: https, or localhost. A plain
http://192.168.x.x address does not count. So this serves web/ over https with a self-signed
certificate, made for this computer's addresses. The phone's browser warns once ("Your connection
is not private"): choose Advanced, then continue to the address. It is your own computer.

    python tools/serve_web.py
    python -m phonedeck --web-url https://192.168.x.x:8443/     (the address this prints)

The certificate and its key are kept in ~/.phonedeck, never in the repository.
"""

import argparse
import contextlib
import datetime
import functools
import http.server
import ipaddress
import socket
import ssl
import threading
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
CERT_DIR = Path.home() / ".phonedeck"
CERT_FILE = CERT_DIR / "dev-cert.pem"
KEY_FILE = CERT_DIR / "dev-key.pem"
VALID_DAYS = 30


def lan_addresses() -> list[str]:
    """This computer's IPv4 addresses on the network (not 127.x)."""
    addresses: set[str] = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))  # sends nothing; it only picks the interface
            addresses.add(probe.getsockname()[0])
    except OSError:
        pass
    with contextlib.suppress(OSError):
        addresses.update(socket.gethostbyname_ex(socket.gethostname())[2])
    return sorted(address for address in addresses if not address.startswith("127."))


def certificate_is_good(addresses: list[str]) -> bool:
    """True if the saved certificate exists, covers all addresses, and is valid for a while."""
    if not (CERT_FILE.exists() and KEY_FILE.exists()):
        return False
    try:
        certificate = x509.load_pem_x509_certificate(CERT_FILE.read_bytes())
        names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except (ValueError, x509.ExtensionNotFound):
        return False
    covered = {str(ip) for ip in names.value.get_values_for_type(x509.IPAddress)}
    soon = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=2)
    return set(addresses) <= covered and certificate.not_valid_after_utc > soon


def make_certificate(addresses: list[str]) -> None:
    """Make a self-signed certificate for localhost and the addresses, and save it."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PhoneDeck development")])
    names = x509.SubjectAlternativeName(
        [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(a)) for a in addresses]
    )
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
        .add_extension(names, critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    CERT_FILE.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    KEY_FILE.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the web page over https on the network.")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--seconds", type=float, help="stop by itself after this many seconds")
    arguments = parser.parse_args()

    addresses = lan_addresses()
    if not certificate_is_good(addresses):
        make_certificate(addresses)
        print(f"Made a new certificate for {', '.join(addresses)} in {CERT_DIR}")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(WEB_DIR))
    server = http.server.ThreadingHTTPServer(("0.0.0.0", arguments.port), handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(CERT_FILE, KEY_FILE)
    server.socket = context.wrap_socket(server.socket, server_side=True)

    for address in addresses:
        print(f"Serving {WEB_DIR} at https://{address}:{arguments.port}/")
    if arguments.seconds:
        threading.Timer(arguments.seconds, server.shutdown).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
