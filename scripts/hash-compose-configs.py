"""Hash active Compose files and recheck files recorded by the prior snapshot."""
import hashlib
from pathlib import Path
import re
import sys


def capture(identities, baseline=None):
    paths = set()
    for row in Path(identities).read_text().splitlines():
        fields = row.split("|")
        if len(fields) != 9:
            raise ValueError("Malformed container identity")
        if fields[8] in {"", "<no value>"}:
            continue
        paths.update(fields[8].split(","))
    if baseline is not None:
        for row in Path(baseline).read_text().splitlines():
            match = re.fullmatch(r"[0-9a-f]{64}  ([^\r\n]+)", row)
            if not match:
                raise ValueError("Malformed baseline Compose hash")
            paths.add(match[1])
    result = []
    for value in sorted(paths):
        path = Path(value)
        if not path.is_absolute() or any(ord(char) < 32 for char in value):
            raise ValueError("Invalid Compose path")
        # Fail if a formerly active file was removed or is no longer readable.
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result.append(f"{digest}  {value}")
    return "\n".join(result) + ("\n" if result else "")


if __name__ == "__main__":
    if len(sys.argv) not in {2, 3}:
        raise SystemExit("usage: hash-compose-configs.py IDENTITIES [BASELINE_HASHES]")
    print(capture(*sys.argv[1:]), end="")
