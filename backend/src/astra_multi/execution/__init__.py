"""Brokered worker execution: scopes, file leases, and post-run diff checks."""

from .errors import (
    DiffScopeViolation,
    FileLeaseConflict,
    FileScopeDenied,
    StepExecutionDenied,
    StepExecutionError,
    WorkerFileScopeDenied,
)
from .file_broker import DiffReport, FileBroker
from .file_scope import FileScopeBroker
from .leases import FileLeaseManager
from .paths import RepoPath, canonicalize_repo_path
from .step_executor import StepExecutionResult, StepExecutor

__all__ = [
    "DiffReport",
    "DiffScopeViolation",
    "FileBroker",
    "FileLeaseConflict",
    "FileLeaseManager",
    "FileScopeBroker",
    "FileScopeDenied",
    "RepoPath",
    "StepExecutionDenied",
    "StepExecutionError",
    "StepExecutionResult",
    "StepExecutor",
    "WorkerFileScopeDenied",
    "canonicalize_repo_path",
]
