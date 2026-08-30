"""Load integration test data from a local service before testing the product.

Exit 69 indicates an unavailable environment dependency (no assertions run).
Malformed data and product assertion failures remain ordinary failures (exit 1).
This client does not start, repair, or substitute for the independently managed service.
"""

import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.greeting import format_greeting, health_status


def main(endpoint: str) -> int:
    # Do not send loopback traffic through ambient HTTP proxies.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(endpoint, timeout=2) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        print(json.dumps({"event": "SERVICE_UNAVAILABLE", "endpoint": endpoint,
                          "error": str(error), "assertions_executed": False}))
        return 69
    cases = json.loads(payload)["cases"]
    assert cases, "Service must provide integration test data"
    for case in cases:
        assert format_greeting(case["name"]) == case["expected"]
    assert health_status() == "ok"
    print(json.dumps({"event": "CHECK_COMPLETED", "assertions_executed": True,
                      "case_count": len(cases), "endpoint": endpoint}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
