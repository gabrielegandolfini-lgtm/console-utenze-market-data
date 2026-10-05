#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests

OPEN_DATA_PAGE = "https://www.ilportaleofferte.it/portaleOfferte/it/open-data.page"
OUT = Path("data/latest")
TIMEOUT = 90

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._text = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []
    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)
    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            text = " ".join("".join(self._text).split())
            self.links.append((self._href, text))
            self._href = None
            self._text = []


def fetch(url: str, *, stream: bool = False) -> requests.Response:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Console-Utenze-Market-Relay/1.0)",
        "Accept": "text/html,application/xml,text/xml,text/csv,text/plain,*/*",
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=TIMEOUT, stream=stream)
    r.raise_for_status()
    return r


def classify(links):
    picked = {}
    for href, text in links:
        url = urljoin(OPEN_DATA_PAGE, href)
        low = url.lower()
        t = text.lower()
        if "po_offerte_e_mlibero_" in low and low.endswith(".xml"):
            picked["electricXml"] = url
        elif "po_offerte_g_mlibero_" in low and low.endswith(".xml"):
            picked["gasXml"] = url
        elif "po_offerte_d_mlibero_" in low and low.endswith(".xml"):
            picked["dualXml"] = url
        elif "po_parametri_mercato_libero_e_" in low and low.endswith(".csv"):
            picked["electricParam"] = url
        elif "po_parametri_mercato_libero_g_" in low and low.endswith(".csv"):
            picked["gasParam"] = url
        elif "prezzi storici" in t and low.endswith(".csv"):
            picked["historical"] = url
    return picked


def dataset_date(urls):
    vals = []
    for u in urls.values():
        m = re.search(r"(20\d{6})", u)
        if m:
            try:
                vals.append(datetime.strptime(m.group(1), "%Y%m%d").date())
            except ValueError:
                pass
    return max(vals).isoformat() if vals else ""


def download(url: str, path: Path):
    r = fetch(url, stream=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)


def main():
    print(f"Reading {OPEN_DATA_PAGE}")
    page = fetch(OPEN_DATA_PAGE).text
    parser = LinkParser()
    parser.feed(page)
    urls = classify(parser.links)
    required = ("electricXml", "gasXml")
    missing = [k for k in required if k not in urls]
    if missing:
        raise RuntimeError(f"Missing required datasets: {', '.join(missing)}")

    # Clean only the generated data branch contents.
    OUT.mkdir(parents=True, exist_ok=True)
    for p in OUT.iterdir():
        if p.is_file():
            p.unlink()

    file_map = {}
    for key, url in urls.items():
        ext = ".csv" if url.lower().endswith(".csv") else ".xml"
        local = OUT / f"{key}{ext}"
        print(f"Downloading {key}: {url}")
        download(url, local)
        file_map[key] = local.as_posix()

    manifest = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourcePage": OPEN_DATA_PAGE,
        "sourceUpdatedAt": dataset_date(urls),
        "files": file_map,
        "sourceUrls": urls,
        "notes": [
            "Files downloaded by GitHub Actions from the official Portale Offerte Open Data page.",
            "The Apps Script console reads these files from the GitHub relay because direct UrlFetchApp calls to the Portale Offerte can receive HTTP 403."
        ]
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
