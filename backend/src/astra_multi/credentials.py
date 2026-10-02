"""API credentials stay in the operating system's secure credential store."""

from typing import Protocol

import keyring
from keyring.backend import KeyringBackend
from keyring.backends.chainer import ChainerBackend
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE = "AstraMulti/provider-api-key"
SECURE_BACKENDS = {
    "keyring.backends.Windows",
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
    "keyring.backends.kwallet",
}


class CredentialStoreError(RuntimeError):
    pass


class CredentialStore(Protocol):
    def read(self, profile: str) -> str | None: ...
    def write(self, profile: str, secret: str) -> None: ...
    def delete(self, profile: str) -> None: ...


def validate_secret(secret: str) -> str:
    secret = secret.strip()
    if not secret or any(ord(char) < 32 or ord(char) == 127 for char in secret):
        raise CredentialStoreError(
            "API key must be nonempty and contain no control characters"
        )
    return secret


class OSCredentialStore:
    def __init__(self, backend: KeyringBackend | None = None) -> None:
        selected = backend if backend is not None else keyring.get_keyring()
        candidates = (
            selected.backends if isinstance(selected, ChainerBackend) else [selected]
        )
        secure = [
            item for item in candidates if type(item).__module__ in SECURE_BACKENDS
        ]
        if not secure:
            raise CredentialStoreError(
                "Secure OS keyring unavailable; unlock/configure it or use an environment-only profile"
            )
        self.backend = secure[0]

    def read(self, profile: str) -> str | None:
        try:
            value: object = self.backend.get_password(SERVICE, profile)
            if value is None or isinstance(value, str):
                return value
            raise CredentialStoreError("Invalid response from OS credential store")
        except (KeyringError, RuntimeError):
            raise CredentialStoreError("Could not read OS credential store") from None

    def write(self, profile: str, secret: str) -> None:
        secret = validate_secret(secret)
        try:
            self.backend.set_password(SERVICE, profile, secret)
        except (KeyringError, RuntimeError):
            raise CredentialStoreError(
                "Could not save API key in OS credential store"
            ) from None

    def delete(self, profile: str) -> None:
        try:
            self.backend.delete_password(SERVICE, profile)
        except PasswordDeleteError:
            pass
        except (KeyringError, RuntimeError):
            raise CredentialStoreError(
                "Could not remove API key from OS credential store"
            ) from None
