"""Crea una CA de prueba y el certificado del servidor gRPC (clase 7) en /certs.

Si los archivos ya existen, no hace nada (para regenerarlos: borrar el volumen `certs`).
En producción los emitiría una CA interna o cert-manager, y se renovarían solos.
"""

import datetime
import ipaddress
import logging
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

logging.basicConfig(level=logging.INFO, format="%(asctime)s [certificados] %(message)s")
log = logging.getLogger("certificados")

DESTINO = Path("/certs")
NOMBRES = ["grpc", "localhost"]
IPS = ["127.0.0.1"]


def _certificado(cn, clave, ca_cert=None, ca_clave=None, es_ca=False, san=None, uso=None):
    ahora = datetime.datetime.now(datetime.timezone.utc)
    sujeto = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    b = (x509.CertificateBuilder().subject_name(sujeto)
         .issuer_name(ca_cert.subject if ca_cert else sujeto)
         .public_key(clave.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(ahora - datetime.timedelta(minutes=5))
         .not_valid_after(ahora + datetime.timedelta(days=365))
         .add_extension(x509.BasicConstraints(ca=es_ca, path_length=None), critical=True))
    if es_ca:
        b = b.add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                          content_commitment=False, key_encipherment=False,
                                          data_encipherment=False, key_agreement=False,
                                          encipher_only=False, decipher_only=False), critical=True)
    if san:
        b = b.add_extension(x509.SubjectAlternativeName(san), critical=False)
    if uso:
        b = b.add_extension(x509.ExtendedKeyUsage(uso), critical=False)
    return b.sign(ca_clave or clave, hashes.SHA256())


def _pem_clave(k):
    return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                           serialization.NoEncryption())


def main():
    archivos = [DESTINO / n for n in ("ca.crt", "servidor.crt", "servidor.key")]
    if all(a.exists() for a in archivos):
        log.info("Los certificados ya existen en %s: no se regeneran.", DESTINO)
        return
    DESTINO.mkdir(parents=True, exist_ok=True)
    ca_clave = ec.generate_private_key(ec.SECP256R1())
    ca_cert = _certificado("mlops2-ca-de-prueba", ca_clave, es_ca=True)
    srv_clave = ec.generate_private_key(ec.SECP256R1())
    san = [x509.DNSName(n) for n in NOMBRES] + [x509.IPAddress(ipaddress.ip_address(i)) for i in IPS]
    srv_cert = _certificado("grpc", srv_clave, ca_cert, ca_clave, san=san, uso=[ExtendedKeyUsageOID.SERVER_AUTH])
    pem = lambda c: c.public_bytes(serialization.Encoding.PEM)  # noqa: E731
    (DESTINO / "ca.crt").write_bytes(pem(ca_cert))
    (DESTINO / "servidor.crt").write_bytes(pem(srv_cert))
    (DESTINO / "servidor.key").write_bytes(_pem_clave(srv_clave))
    (DESTINO / "servidor.key").chmod(0o640)
    log.info("CA y certificado del servidor gRPC creados en %s (válidos 1 año, SAN %s %s)", DESTINO, NOMBRES, IPS)


if __name__ == "__main__":
    main()
