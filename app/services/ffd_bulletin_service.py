"""Read the official, explicitly marked bulletin cells; never infer hourly forecasts."""
import asyncio
import math
import re
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

URL = "https://ffd.pmd.gov.pk/bulletin"
CUSEC_TO_CUMECS = 0.028316846592


class BulletinParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.rows = []
        self.row = None
        self.cell = None
        self.cells = []
        self.permalink = URL

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href", "").startswith("https://ffd.pmd.gov.pk/b/") and self.permalink == URL:
            self.permalink = urljoin(URL, attrs["href"])
        if tag == "tr":
            self.row = {}
        if tag in {"td", "th"}:
            self.cell = attrs.get("data-ffd")
            self.cells = []

    def handle_data(self, data):
        self.text.append(data)
        if self.cell:
            self.cells.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"}:
            if self.cell and self.row is not None:
                self.row[self.cell] = " ".join("".join(self.cells).split())
            self.cell = None
        if tag == "tr":
            if self.row and "station" in self.row:
                self.rows.append(self.row)
            self.row = None


def number(value):
    if not re.fullmatch(r"\d+(?:\.\d+)?", value.strip()):
        return None
    parsed = float(value)
    return round(parsed * 1000 * CUSEC_TO_CUMECS, 2) if math.isfinite(parsed) else None


def forecast_range(text):
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:[-\u2013\u2014]\s*(\d+(?:\.\d+)?))?\s*", text)
    if not match:
        return None, None
    low, high = number(match[1]), number(match[2] or match[1])
    return (low, high) if low is not None and high is not None and low <= high else (None, None)


def parse_bulletin(html):
    parser = BulletinParser()
    parser.feed(html)
    text = " ".join(" ".join(parser.text).split())
    issued = re.search(r"BULLETIN\s+No:\s*([\w/-]+)\s+Dated:\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)[-\s]+(\d{4})\s+Time:\s*(\d{2}:\d{2})\s+hours\s*\(PST\)", text)
    if not issued or not re.search(r"QUANTITATIVE FLOOD FORECAST OF GAUGING STATIONS\s*\(IN THOUSANDS OF CUSECS\)", text, re.I) or not re.search(r"Next\s+24-hrs\s*\(Inflow\)", text, re.I):
        raise ValueError("Unrecognized FFD bulletin date, units or forecast basis")
    issued_at = datetime.strptime(f"{issued[2]} {issued[3]} {issued[4]} {issued[5]}", "%d %B %Y %H:%M").replace(tzinfo=timezone(timedelta(hours=5)))
    if issued_at > datetime.now(timezone.utc) + timedelta(minutes=15):
        raise ValueError("FFD bulletin issue time is in the future")
    observation_hour = re.search(r"Actual Observations at\s+(\d{2})(\d{2})\s+PST", text)
    observed_at = issued_at.replace(hour=int(observation_hour[1]), minute=int(observation_hour[2]), second=0) if observation_hour else None
    if observed_at and observed_at > issued_at:
        raise ValueError("FFD observation time follows issue time")
    result = {}
    for row in parser.rows:
        low, high = forecast_range(row.get("forecast", ""))
        result[row["station"]] = {
            "samples": {kind.upper(): {"time": observed_at.isoformat(), "value": value, "source": parser.permalink}
                        for kind in ("inflow", "outflow") if observed_at and (value := number(row.get(kind, ""))) is not None},
            "forecast": {"gauge": "INFLOW", "text": row.get("forecast", ""), "low": low, "high": high,
                         "issued_at": issued_at.isoformat(), "horizon_hours": 24, "source": parser.permalink,
                         "bulletin": issued[1], "valid_from": None, "valid_until": None},
        }
    if not result:
        raise ValueError("FFD bulletin has no marked station rows")
    return result


class FFDBulletinService:
    def __init__(self):
        self.cache = None
        self.cached_at = 0
        self.lock = asyncio.Lock()

    async def get(self):
        async with self.lock:
            if self.cache is not None and time.monotonic() - self.cached_at < 300:
                return self.cache
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(URL)
                response.raise_for_status()
            result = parse_bulletin(response.text)
            self.cache, self.cached_at = result, time.monotonic()
            return result


ffd_bulletins = FFDBulletinService()
