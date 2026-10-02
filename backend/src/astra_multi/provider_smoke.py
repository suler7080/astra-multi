"""Small opt-in live smoke; reports contain no credentials or failed response bodies."""

import argparse
import json
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from astra_multi.provider_config import ProviderSettingsRepository
from astra_multi.providers import ProviderError, generate


class SmokePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["ok"]
    message: Literal["hello"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--model", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    repository = ProviderSettingsRepository(args.config)
    profile = repository.load().profile(args.profile)
    models: list[str] = args.model or [profile.model]
    results: list[JsonValue] = []
    for model in models:
        for scenario in ("plain_text", "json_schema"):
            record: dict[str, JsonValue] = {
                "model": model,
                "scenario": scenario,
                "verdict": "FAIL",
            }
            started = time.perf_counter()
            try:
                result = generate(
                    profile.name,
                    "planner",
                    [
                        {
                            "role": "user",
                            "content": "Reply with exactly hello, no punctuation."
                            if scenario == "plain_text"
                            else 'Return exactly {"status":"ok","message":"hello"}.',
                        }
                    ],
                    output_schema=SmokePayload if scenario == "json_schema" else None,
                    limits={"model": model, "timeout": 30, "max_retries": 0},
                    settings=repository,
                )
                valid = (
                    result.content == {"status": "ok", "message": "hello"}
                    if scenario == "json_schema"
                    else (
                        isinstance(result.content, str)
                        and result.content.strip().lower() == "hello"
                    )
                )
                record.update(
                    verdict="PASS" if valid else "FAIL",
                    response_model=result.model_id,
                    provider=result.provider,
                    usage=None
                    if result.usage is None
                    else {name: value for name, value in result.usage.items()},
                    latency_seconds=result.latency_seconds,
                    attempts=result.attempts,
                )
                if valid:
                    record["response"] = (
                        {"status": "ok", "message": "hello"}
                        if scenario == "json_schema"
                        else "hello"
                    )
            except ProviderError as error:
                record["error_code"] = error.code
            record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
            results.append(record)
    report = {
        "profile": profile.model_dump(mode="json"),
        "results": results,
        "verdict": "PASS"
        if all(
            isinstance(record, dict) and record["verdict"] == "PASS"
            for record in results
        )
        else "FAIL",
        "scope": "Opt-in text and strict JSON smoke, not production workflow evaluation; usage can be unknown",
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    if report["verdict"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
