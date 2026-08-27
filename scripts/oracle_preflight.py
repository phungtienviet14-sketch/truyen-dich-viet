"""Read-only OCI profile/region/limits checks. Never authenticates or provisions."""

import argparse
import configparser
import json
import re
import shutil
import subprocess
from pathlib import Path

READ_COMMANDS = frozenset({
    ("iam", "region-subscription", "list"),
    ("limits", "value", "list"),
    ("compute", "instance", "list"),
})


def read_profile(config_file: Path, profile: str) -> dict[str, str]:
    config = configparser.ConfigParser(interpolation=None)
    if not config.read(config_file, encoding="utf-8"):
        raise ValueError("OCI config missing; authenticate interactively first")
    if profile not in config:
        raise ValueError("OCI profile missing; choose the profile used for login")
    values = {key: config[profile].get(key, "") for key in ("region", "tenancy")}
    if not re.fullmatch(r"[a-z0-9-]+", values["region"]):
        raise ValueError("OCI profile region is invalid")
    if not re.fullmatch(r"ocid1\.tenancy\.[a-zA-Z0-9._-]+", values["tenancy"]):
        raise ValueError("OCI profile tenancy is invalid")
    return values


def run_readonly(cli: str, config: Path, profile: str, args: list[str]):
    if tuple(args[:3]) not in READ_COMMANDS:
        raise ValueError("Only allowlisted read-only OCI commands are permitted")
    command = [cli, *args, "--config-file", str(config), "--profile", profile,
               "--auth", "security_token", "--output", "json"]
    try:
        result = subprocess.run(command, check=True, capture_output=True,
                                text=True, timeout=60, shell=False)
        return json.loads(result.stdout)["data"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
        raise RuntimeError("OCI read failed. Check session expiry, region and IAM permissions locally.") from error


def inspect_account(cli: str, config: Path, profile: str) -> None:
    settings = read_profile(config, profile)
    tenancy = settings["tenancy"]
    regions = run_readonly(cli, config, profile, [
        "iam", "region-subscription", "list", "--tenancy-id", tenancy, "--all"])
    home = next((entry["region-name"] for entry in regions if entry.get("is-home-region")), None)
    print(f"Configured region: {settings['region']}; home region: {home}")
    if not home or home != settings["region"]:
        raise ValueError("Stop: configure the tenancy home region for Always Free compute")
    for service in ("compute", "block-storage"):
        limits = run_readonly(cli, config, profile, [
            "limits", "value", "list", "--compartment-id", tenancy,
            "--service-name", service, "--all", "--region", home])
        relevant = [item for item in limits if service != "compute" or "a1" in item.get("name", "")]
        print(f"{service} limits (entitlement only, NOT a free-cost guarantee):")
        for item in relevant:
            print(json.dumps({key: item.get(key) for key in ("name", "value", "scope-type", "availability-domain")}))
    print("No resources changed. Verify existing usage, free allowance and capacity in Console before creation.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oci-cli", default="oci")
    parser.add_argument("--config-file", type=Path, default=Path.home() / ".oci" / "config")
    parser.add_argument("--profile", default="TRUYEN")
    args = parser.parse_args()
    cli = shutil.which(args.oci_cli)
    if not cli:
        parser.exit(1, "OCI CLI not found; add it to PATH or pass --oci-cli with its executable path.\n")
    try:
        inspect_account(cli, args.config_file, args.profile)
    except (ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
