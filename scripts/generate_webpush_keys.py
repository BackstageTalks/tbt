#!/usr/bin/env python3
"""Generate a VAPID key pair for BlinQ Web Push environment variables.

Run locally once, then store the PRIVATE value only in deployment secrets.
"""
from __future__ import annotations

import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


key = ec.generate_private_key(ec.SECP256R1())
private_der = key.private_bytes(
    encoding=serialization.Encoding.DER,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
public = key.public_key().public_bytes(
    encoding=serialization.Encoding.X962,
    format=serialization.PublicFormat.UncompressedPoint,
)
print("BLINQ_WEBPUSH_PUBLIC_KEY=" + b64url(public))
print("BLINQ_WEBPUSH_PRIVATE_KEY=" + base64.urlsafe_b64encode(private_der).decode("ascii"))
print("BLINQ_WEBPUSH_SUBJECT=mailto:CHANGE_ME")
