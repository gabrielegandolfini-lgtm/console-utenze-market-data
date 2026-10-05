#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Tuple

import requests

BASE = "https://www.ilportaleofferte.it/portaleOfferte/resources/opendata/csv"
OUT = Path("data/latest")
TIMEOUT = 120
LOOKBACK_DAYS = 14

# The current official Open Data page currently points to the 10/08/2026 dataset.
# This is used only as a fallback when the current-day direct files are not yet published.
KNOWN_OFFICIAL_SNAPSHOT = "20260810"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    "Accept": "application/xml,text/xml,text/csv,text/plain,*/*",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Referer": "https://www.ilportaleofferte.it/portaleOfferte/it/open-data.page",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def compact_date(d: date) -> str:
    return d.strftime("%Y%m%d")


def urls_for(ds: str) -> Dict[str, str]:
    y = ds[:4]
    m = str(int(ds[4:6]))
    ym = f"{y}_{m}"
    return {
        "electricXml": f"{BASE}/offerteML/{ym}/PO_Offerte_E_MLIBERO_{ds}.xml",
        "gasXml": f"{BASE}/offerteML/{ym}/PO_Offerte_G_MLIBERO_{ds}.xml",
        "dualXml": f"{BASE}/offerteML/{ym}/PO_Offerte_D_MLIBERO_{ds}.xml",
        "electricParam": f"{BASE}/parametriML/{ym}/PO_Parametri_Mercato_Libero_E_{ds}.csv",
        "gasParam": f"{BASE}/parametriML/{ym}/PO_Parametri_Mercato_Libero_G_{ds}.csv",
    }


def probe(session: requests.Session, url: str) -> Tuple[int, str]:
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True, stream=True)
        code = r.status_code
        ctype = r.headers.get("Content-Type", "")
        r.close()
        return code, ctype
    except Exception as exc:
        print(f"PROBE ERROR {url}: {exc}")
        return 0, ""


def find_snapshot(session: requests.Session):
    candidates = []
    today = date.today()
    for i in range(LOOKBACK_DAYS + 1):
        candidates.append(compact_date(today - timedelta(days=i)))
    if KNOWN_OFFICIAL_SNAPSHOT not in candidates:
        candidates.append(KNOWN_OFFICIAL_SNAPSHOT)

    diagnostics = []
    for ds in candidates:
        u = urls_for(ds)
        ec, ect = probe(session, u["electricXml"])
        gc, gct = probe(session, u["gasXml"])
        diagnostics.append({
            "date": ds,
            "electricXml": ec,
            "gasXml": gc,
            "electricContentType": ect,
            "gasContentType": gct,
        })
        print(f"{ds}: XML E={ec}, XML G={gc}")
        if 200 <= ec < 300 and 200 <= gc < 300:
            return ds, u, diagnostics

    raise RuntimeError(
        "Nessun dataset ufficiale diretto raggiungibile. "
        + json.dumps(diagnostics, ensure_ascii=False)
    )


def download(session: requests.Session, url: str, path: Path) -> bool:
    try:
        with session.get(url, timeout=TIMEOUT, allow_redirects=True, stream=True) as r:
            print(f"DOWNLOAD {url} -> HTTP {r.status_code}")
            if not (200 <= r.status_code < 300):
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as f:
                for chunk in r.iter_content(1024 * 1024):
                    if chunk:
                        f.write(chunk)
            return True
    except Exception as exc:
        print(f"DOWNLOAD ERROR {url}: {exc}")
        return False


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    ds, urls, diagnostics = find_snapshot(session)
    print(f"Selected official dataset: {ds}")

    OUT.mkdir(parents=True, exist_ok=True)
    for p in OUT.iterdir():
        if p.is_file():
            p.unlink()

    files = {}
    warnings = []

    mapping = {
        "electricXml": "electric.xml",
        "gasXml": "gas.xml",
        "dualXml": "dual.xml",
        "electricParam": "electricParam.csv",
        "gasParam": "gasParam.csv",
    }

    for key, filename in mapping.items():
        ok = download(session, urls[key], OUT / filename)
        if ok:
            files[key] = f"data/latest/{filename}"
        elif key in ("electricXml", "gasXml"):
            raise RuntimeError(f"Download obbligatorio fallito: {key} -> {urls[key]}")
        else:
            warnings.append(f"{key} non disponibile: {urls[key]}")

    manifest = {
        "schemaVersion": 2,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourcePage": "https://www.ilportaleofferte.it/portaleOfferte/it/open-data.page",
        "sourceUpdatedAt": f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}",
        "sourceUrls": urls,
        "files": files,
        "warnings": warnings,
        "diagnostics": diagnostics,
        "relay": "GitHub Actions",
    }

    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
