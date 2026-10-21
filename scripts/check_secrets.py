"""Scan Git's index and outgoing commits. Never print detected values."""

import argparse
import re
import subprocess
from pathlib import Path


def git(*args):
    return subprocess.check_output(["git", *args])


def forbidden(path):
    name = Path(path).name.lower()
    return (name == ".env" or name.startswith(".env.")) and name != ".env.example"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="origin/feat/writing-multi-agent")
    parser.add_argument("--env-path", action="append", default=[])
    args = parser.parse_args()
    root = Path(git("rev-parse", "--show-toplevel").decode().strip())
    private = []
    for file in [root / ".env", *(Path(p) for p in args.env_path)]:
        if file.is_file():
            for line in file.read_text(encoding="utf-8-sig").splitlines():
                if "=" in line and re.search(
                    r"KEY|SECRET|TOKEN|PASSWORD", line.split("=", 1)[0], re.I
                ):
                    value = line.split("=", 1)[1].strip().strip("\"'")
                    if len(value) >= 12:
                        private.append(value.encode())
    scans = [("index", path.decode()) for path in git("ls-files", "-z").split(b"\0") if path]
    for commit in git("rev-list", f"{args.base}..HEAD").decode().splitlines():
        scans += [
            (commit, path.decode())
            for path in git("diff-tree", "--no-commit-id", "--name-only", "-r", "-z", commit).split(
                b"\0"
            )
            if path
        ]
    problems = set()
    for ref, path in scans:
        if forbidden(path) or "/data/" in "/" + path or "/backups/" in "/" + path:
            problems.add(path)
            continue
        try:
            data = git("show", (":" if ref == "index" else ref + ":") + path)
        except subprocess.CalledProcessError:
            continue  # Deleted files have no blob in this revision.
        if any(value in data for value in private) or re.search(
            rb"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----)",
            data,
        ):
            problems.add(path)
    if problems:
        print("BLOCKED: forbidden file or potential secret in: " + ", ".join(sorted(problems)))
        raise SystemExit(1)
    print(
        f"PASS: {len(scans)} indexed/outgoing file revisions checked; no private env files or detected secrets."
    )


if __name__ == "__main__":
    main()
