"""
Colectare analytics pentru repository-ul GitHub.

Rulat zilnic prin GitHub Actions. Colectează:
- Traffic: clones și views (GitHub păstrează doar 14 zile)
- Releases: download count per release/asset
- Community: stars, forks, watchers, open issues
- Referrers: top surse de trafic

Datele sunt salvate în .github/analytics/stats.json cu deduplicare
automată pe dată — rulări multiple în aceeași zi nu creează duplicate.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# ─────────────────────────────────────────────
# Configurare
# ─────────────────────────────────────────────

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")
STATS_FILE = Path(".github/analytics/stats.json")
SHIELDS_DIR = Path("statistici/shields")

API_BASE = "https://api.github.com"
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# Header special pentru starred_at pe stargazers
HEADERS_STARS = {
    **HEADERS,
    "Accept": "application/vnd.github.star+json",
}


# ─────────────────────────────────────────────
# Funcții API
# ─────────────────────────────────────────────


def api_get(endpoint: str, headers: dict | None = None) -> dict | list | None:
    """Apel GET la GitHub API cu tratare de erori."""
    url = f"{API_BASE}/repos/{GITHUB_REPOSITORY}{endpoint}"
    try:
        resp = requests.get(url, headers=headers or HEADERS, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        print(f"  WARN: {endpoint} → {resp.status_code}: {resp.text[:200]}")
        return None
    except requests.RequestException as e:
        print(f"  EROARE: {endpoint} → {e}")
        return None


def colecteaza_traffic() -> dict:
    """Colectează clones și views pe ultimele 14 zile."""
    print("Colectez traffic (clones + views)...")

    clones_data = api_get("/traffic/clones") or {}
    views_data = api_get("/traffic/views") or {}

    # Indexăm pe dată (YYYY-MM-DD)
    zilnic: dict[str, dict] = {}

    for clone in clones_data.get("clones", []):
        data = clone["timestamp"][:10]
        zilnic.setdefault(data, {})["clones_total"] = clone["count"]
        zilnic[data]["clones_unice"] = clone["uniques"]

    for view in views_data.get("views", []):
        data = view["timestamp"][:10]
        zilnic.setdefault(data, {})["views_total"] = view["count"]
        zilnic[data]["views_unice"] = view["uniques"]

    print(f"  → {len(zilnic)} zile cu date de traffic")
    return zilnic


def colecteaza_releases() -> dict[str, int]:
    """Colectează download count per release (suma asset-urilor)."""
    print("Colectez releases (downloads)...")

    releases = api_get("/releases") or []
    rezultat: dict[str, int] = {}

    for release in releases:
        tag = release.get("tag_name", "unknown")
        total = sum(
            asset.get("download_count", 0)
            for asset in release.get("assets", [])
        )
        rezultat[tag] = total

    print(f"  → {len(rezultat)} release-uri: {rezultat}")
    return rezultat


def colecteaza_community() -> dict:
    """Colectează stars, forks, watchers, open issues."""
    print("Colectez community stats...")

    repo = api_get("") or {}

    stats = {
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "watchers": repo.get("subscribers_count", 0),
        "open_issues": repo.get("open_issues_count", 0),
    }

    print(f"  → stars={stats['stars']}, forks={stats['forks']}, "
          f"watchers={stats['watchers']}, issues={stats['open_issues']}")
    return stats


def colecteaza_referrers() -> list[dict]:
    """Colectează top referrers (surse de trafic)."""
    print("Colectez referrers...")

    referrers = api_get("/traffic/popular/referrers") or []

    rezultat = [
        {
            "sursa": r.get("referrer", ""),
            "vizite": r.get("count", 0),
            "vizitatori_unici": r.get("uniques", 0),
        }
        for r in referrers[:10]
    ]

    print(f"  → {len(rezultat)} referrers")
    return rezultat


# ─────────────────────────────────────────────
# Stocare și deduplicare
# ─────────────────────────────────────────────


def incarca_stats() -> dict:
    """Încarcă fișierul de statistici existent sau creează unul nou."""
    if STATS_FILE.exists():
        try:
            return json.loads(STATS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print("WARN: stats.json corupt, reconstruiesc de la zero")
    return {
        "repo": GITHUB_REPOSITORY,
        "prima_colectare": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "zilnic": {},
        "releases": {},
    }


def salveaza_stats(stats: dict) -> None:
    """Salvează statisticile în fișier JSON."""
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATS_FILE.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=False),
        encoding="utf-8",
    )
    print(f"Salvat: {STATS_FILE}")


def merge_traffic(stats: dict, traffic_nou: dict) -> None:
    """Merge-uiește datele noi de traffic cu cele existente (fără duplicate)."""
    zilnic = stats.setdefault("zilnic", {})

    for data, valori in traffic_nou.items():
        if data not in zilnic:
            zilnic[data] = {}
        # Traffic: suprascrierea e OK — GitHub returnează date actualizate
        zilnic[data].update(valori)


def actualizeaza_snapshot_zilnic(stats: dict, community: dict,
                                 releases: dict, referrers: list) -> None:
    """Adaugă snapshot-ul zilnic (community + releases + referrers)."""
    azi = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    zilnic = stats.setdefault("zilnic", {})
    zilnic.setdefault(azi, {})

    # Community snapshot
    zilnic[azi]["stars"] = community.get("stars", 0)
    zilnic[azi]["forks"] = community.get("forks", 0)
    zilnic[azi]["watchers"] = community.get("watchers", 0)
    zilnic[azi]["open_issues"] = community.get("open_issues", 0)

    # Referrers (top surse la momentul colectării)
    if referrers:
        zilnic[azi]["referrers"] = referrers

    # Releases — snapshot global (nu per zi, ci per tag)
    stats["releases"] = releases


# ─────────────────────────────────────────────
# Generare badge-uri shields.io (endpoint JSON)
# ─────────────────────────────────────────────


def _scrie_shield(nume: str, label: str, message: str, color: str) -> None:
    """Scrie un fișier JSON compatibil shields.io endpoint."""
    SHIELDS_DIR.mkdir(parents=True, exist_ok=True)
    cale = SHIELDS_DIR / f"{nume}.json"
    cale.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "label": label,
                "message": message,
                "color": color,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def genereaza_shields(releases: dict, community: dict,
                      stats: dict) -> None:
    """Generează fișierele JSON pentru badge-urile din README.

    Badge-uri generate:
    - descarcari.json: clone-uri totale cumulate (metrica reală de adopție HACS)
    - ultima_release.json: ultima versiune + clone-uri 14 zile
    - stars.json: total stars
    - vizitatori.json: vizitatori unici ultimele 14 zile
    - clone.json: clone unice ultimele 14 zile
    """
    print("Generez badge-uri shields.io...")

    zilnic = stats.get("zilnic", {})

    # ── Total clone cumulate (toate zilele colectate) ──
    total_clone_cumulate = sum(
        zi.get("clones_total", 0)
        for zi in zilnic.values()
    )
    _scrie_shield(
        "descarcari",
        "instalări (clone)",
        _format_numar(total_clone_cumulate),
        "blue",
    )

    # ── Ultima versiune + clone recente ──
    if releases:
        tags_sortate = sorted(releases.keys(), reverse=True)
        ultim_tag = tags_sortate[0]
        clone_14z = sum(
            zi.get("clones_unice", 0)
            for zi in zilnic.values()
        )
        _scrie_shield(
            "ultima_release",
            f"{ultim_tag}",
            f"{_format_numar(clone_14z)} clone (14z)",
            "green",
        )

    # ── Stars ──
    _scrie_shield(
        "stars",
        "stars",
        _format_numar(community.get("stars", 0)),
        "yellow",
    )

    # ── Vizitatori unici (ultimele 14 zile) ──
    zilnic = stats.get("zilnic", {})
    vizitatori_14z = sum(
        zi.get("views_unice", 0)
        for zi in zilnic.values()
    )
    _scrie_shield(
        "vizitatori",
        "vizitatori (14 zile)",
        _format_numar(vizitatori_14z),
        "brightgreen",
    )

    # ── Clone unice (ultimele 14 zile) ──
    clone_14z = sum(
        zi.get("clones_unice", 0)
        for zi in zilnic.values()
    )
    _scrie_shield(
        "clone",
        "clone (14 zile)",
        _format_numar(clone_14z),
        "orange",
    )

    print(f"  → {len(list(SHIELDS_DIR.glob('*.json')))} badge-uri generate")


def _format_numar(n: int) -> str:
    """Formatează un număr pentru afișare pe badge (1234 → 1.2k)."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────


def main() -> None:
    """Colectare completă și salvare."""
    if not GITHUB_TOKEN:
        print("EROARE: GITHUB_TOKEN lipsește")
        sys.exit(1)
    if not GITHUB_REPOSITORY:
        print("EROARE: GITHUB_REPOSITORY lipsește")
        sys.exit(1)

    print(f"=== Analytics: {GITHUB_REPOSITORY} ===")
    print(f"Data: {datetime.now(timezone.utc).isoformat()}")
    print()

    # Colectare
    traffic = colecteaza_traffic()
    releases = colecteaza_releases()
    community = colecteaza_community()
    referrers = colecteaza_referrers()

    # Încărcare + merge
    stats = incarca_stats()
    stats["ultima_actualizare"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    merge_traffic(stats, traffic)
    actualizeaza_snapshot_zilnic(stats, community, releases, referrers)

    # Sortăm zilnic cronologic
    if "zilnic" in stats:
        stats["zilnic"] = dict(sorted(stats["zilnic"].items()))

    # Salvare stats
    salveaza_stats(stats)

    # Generare badge-uri shields.io
    genereaza_shields(releases, community, stats)

    # Sumar
    nr_zile = len(stats.get("zilnic", {}))
    print(f"\n=== Sumar: {nr_zile} zile colectate, "
          f"{len(releases)} release-uri ===")


if __name__ == "__main__":
    main()
