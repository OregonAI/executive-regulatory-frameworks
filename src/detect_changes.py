#!/usr/bin/env python3
"""Re-fetch every source in _meta/source-manifest.yml and compare content hashes.
Writes changed-sources.tsv (id, url, old sha256, new sha256) and, with
--github-output FILE, a changed=true/false output for the workflow. Exit code is
0 unless a fetch fails outright — a changed source is a signal, not an error."""
import argparse
import hashlib
import sys
import urllib.request

import yaml

from repo_lib import MANIFEST_PATH, REPO_ROOT

USER_AGENT = "oregon-policy-repo-change-detector (+https://github.com/morficflux/oregon-policy-repo)"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--github-output", help="path to $GITHUB_OUTPUT")
    args = ap.parse_args()

    manifest = yaml.safe_load(MANIFEST_PATH.read_text())
    changed, failed = [], []
    for src in manifest.get("sources", []):
        sid, url, old = src["id"], src["url"], src["sha256"]
        try:
            new = hashlib.sha256(fetch(url)).hexdigest()
        except Exception as e:
            failed.append(sid)
            print(f"FETCH FAILED {sid}: {url} ({e})")
            continue
        if new != old:
            changed.append((sid, url, old, new))
            print(f"CHANGED  {sid}: {old[:12]}… -> {new[:12]}…")
        else:
            print(f"unchanged {sid}")

    out = REPO_ROOT / "changed-sources.tsv"
    out.write_text("".join(f"{sid}\t{url}\t{old}\t{new}\n" for sid, url, old, new in changed))
    if args.github_output:
        with open(args.github_output, "a") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")

    print(f"\n{len(changed)} changed, {len(failed)} fetch failure(s).")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
