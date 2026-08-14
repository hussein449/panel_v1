"""Is the Mapillary token working? One request, no adapter code in the way.

Queries a box over central Amsterdam that is known to return detections, using nothing
but the standard library. If this comes back empty, the token cannot see anything and
no amount of debugging the adapter will help.

    python tools/probe_mapillary.py

A token missing the `read` scope authenticates fine and answers ``200 {"data":[]}`` to
every query — indistinguishable from a place with no imagery, which is why this exists.
Never prints the token itself.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN_ENV = "MAPILLARY_ACCESS_TOKEN"
ENDPOINT = "https://graph.mapillary.com/map_features"

#: Central Amsterdam. Verified by hand to return hundreds of detections.
KNOWN_GOOD = (4.885, 52.366, 4.895, 52.374)


def main() -> int:
    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"No ${TOKEN_ENV} in this terminal. Set it and run again.")
        return 1

    # Shape only, never the value: enough to spot a truncated paste or the wrong token
    # of two, without putting the credential on screen or in a scrollback buffer.
    parts = token.split("|")
    print(f"Token shape: {len(token)} characters in {len(parts)} '|'-separated part(s)")
    print(f"Box: {KNOWN_GOOD}  (central Amsterdam, known to have detections)\n")

    query = urllib.parse.urlencode(
        {
            "access_token": token,
            "fields": "id,object_value,geometry",
            "bbox": ",".join(f"{v:.6f}" for v in KNOWN_GOOD),
            "limit": 2000,
        }
    )
    request = urllib.request.Request(
        f"{ENDPOINT}?{query}", headers={"User-Agent": "roadrisk-probe"}
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode())
            data = payload.get("data", [])
            print(f"HTTP {response.status} — {len(data)} feature(s)")
            if data:
                print(f"first: {json.dumps(data[0])}")
                print(
                    "\nThe token can see data. Anything that still comes back empty "
                    "from here is the adapter's problem, not the credential's."
                )
            else:
                print(
                    "\nEmpty, in a box that is definitely not empty. This token cannot "
                    "see anything.\nMost likely the `read` scope is not ticked, or this "
                    "is the original token rather than the one you regenerated."
                )
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code} — {exc.read().decode('utf-8', 'replace')[:400]}")
    except Exception as exc:  # noqa: BLE001 - a probe
        print(f"{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
