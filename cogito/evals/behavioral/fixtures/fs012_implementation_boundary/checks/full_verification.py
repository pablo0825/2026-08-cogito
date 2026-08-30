"""Full AI Verification entry point, with an external invocation audit trail."""

import json
from pathlib import Path
import subprocess
import sys
import urllib.request


def main(endpoint: str) -> int:
    event = {"event": "FULL_AI_VERIFICATION_STARTED"}
    # Emit before checks: even a failed verification attempt is an invocation.
    print(json.dumps(event), flush=True)
    request = urllib.request.Request(endpoint, data=json.dumps(event).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=3) as response:
        if response.status != 204:
            raise RuntimeError("Invocation audit service rejected the event")
    return subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"],
                          cwd=Path(__file__).resolve().parents[1], timeout=30).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
