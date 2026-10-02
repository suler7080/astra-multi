from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from astra_multi.domain.models import ArtifactRef


class FileArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, content: bytes) -> ArtifactRef:
        ref = ArtifactRef(
            content_hash=hashlib.sha256(content).hexdigest(), size=len(content)
        )
        target = self.root / ref.content_hash
        if target.exists():
            self.read(ref)
            return ref
        descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=self.root)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            if os.name != "nt":
                directory = os.open(self.root, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return ref

    def read(self, ref: ArtifactRef) -> bytes:
        ref = ArtifactRef.model_validate(ref.model_dump())
        content = (self.root / ref.content_hash).read_bytes()
        if (
            len(content) != ref.size
            or hashlib.sha256(content).hexdigest() != ref.content_hash
        ):
            raise ValueError("artifact hash or size mismatch")
        return content
