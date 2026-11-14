"""Synthetic provider payloads: use the real parsers and archive path, without network."""

import json
from datetime import date, timedelta

from .models import TENORS
from .providers import NS

DEMO_DATE = date(2025, 1, 8)


def payloads(as_of=DEMO_DATE):
    entries = []
    # 10Y: Treasury 5.15 vs FRED 5.13 => 2 bps / OK.
    # 5Y warning (3 bps), 30Y critical (7 bps), one null prior observation.
    treasury = {2: 4.8, 5: 4.95, 10: 5.15, 30: 5.35}
    fred = {2: 4.8, 5: 4.92, 10: 5.13, 30: 5.28}
    for day in (as_of - timedelta(days=1), as_of):
        fields = "".join(f"<d:BC_{t}YEAR>{treasury[t]}</d:BC_{t}YEAR>" for t in TENORS)
        entries.append(
            f"<entry><content><m:properties><d:NEW_DATE>{day}T00:00:00</d:NEW_DATE>"
            f"{fields}</m:properties></content></entry>"
        )
    xml = (
        f'<feed xmlns="{NS["atom"]}" xmlns:m="{NS["m"]}" xmlns:d="{NS["d"]}">'
        + "".join(entries)
        + "</feed>"
    ).encode()
    yield "treasury", None, xml, "xml"
    for tenor in TENORS:
        observations = [
            {
                "date": str(day),
                "value": str(fred[tenor]),
                "realtime_start": str(as_of),
                "realtime_end": str(as_of),
            }
            for day in (as_of - timedelta(days=1), as_of)
        ]
        if tenor == 5:
            observations[0]["value"] = "."
        body = json.dumps({"count": 2, "observations": observations}).encode()
        yield "fred", tenor, body, "json"
