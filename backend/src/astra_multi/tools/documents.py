from __future__ import annotations

from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from astra_multi.domain.models import Contract


class DocumentError(ValueError):
    pass


class DocumentPolicy(Contract):
    scopes: tuple[str, ...] = ()
    timeout_seconds: float = 10
    max_bytes: int = 1024 * 1024
    max_redirects: int = 3
    allow_loopback_http: bool = False


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: object, code: int, msg: str,
        headers: object, newurl: str,
    ) -> None:
        return None


class DocumentFetcher:
    def __init__(self, policy: DocumentPolicy) -> None:
        if (
            not 0 < policy.timeout_seconds <= 60
            or not 1 <= policy.max_bytes <= 16 * 1024 * 1024
            or not 0 <= policy.max_redirects <= 5
        ):
            raise DocumentError("invalid document limits")
        self.policy = policy

    def _check(self, url: str) -> None:
        target = urlsplit(url)
        if target.username or target.password or target.fragment or target.query:
            raise DocumentError("URL credentials/query strings/fragments are forbidden")
        if target.scheme != "https" and not (
            self.policy.allow_loopback_http and target.scheme == "http"
            and target.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            raise DocumentError("HTTPS required outside loopback fixture")
        for scope in self.policy.scopes:
            allowed = urlsplit(scope)
            prefix = allowed.path.rstrip("/")
            if (
                (target.scheme, target.hostname, target.port)
                == (allowed.scheme, allowed.hostname, allowed.port)
                and (target.path == prefix or target.path.startswith(prefix + "/"))
                and ".." not in target.path.split("/")
                and "%" not in target.path and "\\" not in target.path
            ):
                return
        raise DocumentError("URL outside configured documentation scope")

    def fetch(self, url: str) -> tuple[str, bytes, str]:
        opener = build_opener(NoRedirect())
        for _ in range(self.policy.max_redirects + 1):
            self._check(url)
            try:
                with opener.open(
                    Request(url, headers={"Accept": "text/plain, text/html, application/json"}),
                    timeout=self.policy.timeout_seconds,
                ) as response:
                    content = response.read(self.policy.max_bytes + 1)
                    if len(content) > self.policy.max_bytes:
                        raise DocumentError("document exceeds byte quota")
                    return url, content, response.headers.get_content_type()
            except HTTPError as error:
                location = error.headers.get("Location")
                if error.code not in {301, 302, 303, 307, 308} or not location:
                    raise DocumentError(f"document HTTP status {error.code}") from None
                url = urljoin(url, location)
                error.close()
        raise DocumentError("documentation redirect limit exceeded")
