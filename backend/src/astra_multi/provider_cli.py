"""Configure public provider profiles and keys without command-line secret values."""

import argparse
import getpass
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from astra_multi.credentials import CredentialStoreError
from astra_multi.provider_config import (
    ProviderConfigurationError,
    ProviderManager,
    ProviderProfile,
    ProviderSettingsRepository,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    configure = commands.add_parser("set")
    configure.add_argument("name")
    configure.add_argument(
        "--kind", choices=["openai", "google", "openai-compatible"], required=True
    )
    configure.add_argument("--model", required=True)
    configure.add_argument("--base-url")
    configure.add_argument(
        "--no-json-mode",
        action="store_true",
        help="Use prompt and local validation when the endpoint lacks native JSON mode",
    )
    configure.add_argument(
        "--key-env",
        help="Read a key from this environment variable; never pass its value",
    )
    configure.add_argument(
        "--env-only",
        action="store_true",
        help="Save only a reference to --key-env; skip the OS keyring",
    )
    commands.add_parser("list")
    remove = commands.add_parser("remove")
    remove.add_argument("name")
    args = parser.parse_args()
    manager = ProviderManager(ProviderSettingsRepository(args.config))
    try:
        if args.command == "list":
            for profile in manager.repository.load().effective_profiles():
                print(profile.model_dump_json())
        elif args.command == "remove":
            manager.remove(args.name)
            print("Provider override removed; configured OS credential deleted")
        else:
            if args.env_only and not args.key_env:
                parser.error("--env-only requires --key-env")
            profile = ProviderProfile.model_validate(
                {
                    "name": args.name,
                    "kind": args.kind,
                    "model": args.model,
                    "base_url": args.base_url,
                    "api_key_env": args.key_env,
                    "credential_source": "environment" if args.env_only else "os",
                    "json_mode": not args.no_json_mode,
                }
            )
            if args.env_only:
                manager.configure(profile)
            else:
                if args.key_env:
                    secret = os.environ.get(args.key_env)
                    if secret is None:
                        raise CredentialStoreError(
                            "Selected key environment variable is not set"
                        )
                else:
                    if not sys.stdin.isatty():
                        raise CredentialStoreError(
                            "A terminal is required for hidden key entry; use --key-env for automation"
                        )
                    secret = getpass.getpass("API key (hidden): ")
                manager.configure(profile, secret)
            print(
                f"Configured {profile.name}; API key is not included in provider metadata"
            )
    except ValidationError:
        parser.exit(
            2, "Invalid provider profile; check name, kind, model and base URL\n"
        )
    except (CredentialStoreError, ProviderConfigurationError):
        parser.exit(
            2,
            "Provider configuration failed; unlock the OS keyring or use --env-only with --key-env\n",
        )
    except OSError:
        parser.exit(2, "Could not read/write provider settings\n")


if __name__ == "__main__":
    main()
