#!/usr/bin/env python3
"""
Veille des annonces in'li.

Compare la liste des annonces actuellement en ligne avec celle du dernier
passage (seen.json) et envoie une alerte Telegram pour chaque NOUVELLE annonce.

Variables d'environnement :
  INLI_URL    URL de recherche in'li (avec tes filtres). Valeur par defaut : 92 par prix croissant.
  TG_TOKEN    Token du bot Telegram (facultatif : sans lui, affichage console).
  TG_CHAT     Ton chat_id Telegram.
  INLI_STATE  Chemin du fichier d'etat (defaut : seen.json).

Aucune dependance externe : uniquement la bibliotheque standard Python 3.
"""

import html
import json
import os
import re
import sys
import time
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

BASE = "https://www.inli.fr"
DEFAULT_URL = (
    "https://www.inli.fr/locations/offres/hauts-de-seine-departement_d:92"
    "?order%5BpriceWithCharges%5D=asc"
)
SEARCH_URL = os.environ.get("INLI_URL") or DEFAULT_URL
STATE_FILE = os.environ.get("INLI_STATE") or "seen.json"
MAX_PAGES = 15
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

OFFER_RE = re.compile(r'href="(/locations/offre/[^"?#]+)"')
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)', re.I
)


def fetch(url: str) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "fr-FR,fr;q=0.9",
        },
    )
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def with_page(url: str, page: int) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}page={page}"


def list_offers() -> dict:
    """Retourne {chemin_annonce: url_complete} sur toutes les pages de resultats."""
    offers = {}
    for page in range(1, MAX_PAGES + 1):
        try:
            page_html = fetch(with_page(SEARCH_URL, page))
        except Exception as exc:  # reseau / 5xx
            print(f"[warn] page {page} illisible : {exc}", file=sys.stderr)
            break

        found = set(OFFER_RE.findall(page_html))
        nouveaux = found - set(offers)
        if not nouveaux:
            break  # derniere page atteinte (ou page vide / repetee)
        for path in nouveaux:
            offers[path] = urljoin(BASE, path)
        time.sleep(1.5)  # on reste poli avec le serveur
    return offers


def describe(url: str) -> str:
    """Petit resume de l'annonce (titre + meta description) pour le message."""
    try:
        page_html = fetch(url)
    except Exception:
        return ""
    parts = []
    for regex in (TITLE_RE, DESC_RE):
        m = regex.search(page_html)
        if m:
            txt = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()
            if txt:
                parts.append(txt)
    return " — ".join(parts)[:300]


def notify(message: str) -> None:
    token = os.environ.get("TG_TOKEN")
    chat = os.environ.get("TG_CHAT")
    print(message)
    if not token or not chat:
        return
    data = urlencode({"chat_id": chat, "text": message}).encode()
    try:
        urlopen(
            Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data),
            timeout=30,
        )
    except Exception as exc:
        print(f"[warn] envoi Telegram echoue : {exc}", file=sys.stderr)


def main() -> int:
    offers = list_offers()
    if not offers:
        print(
            "[erreur] aucune annonce detectee : le site a peut-etre change de structure.",
            file=sys.stderr,
        )
        return 1

    premier_passage = not os.path.exists(STATE_FILE)
    if premier_passage:
        deja_vues = set()
    else:
        with open(STATE_FILE, encoding="utf-8") as f:
            deja_vues = set(json.load(f))

    nouvelles = sorted(set(offers) - deja_vues)

    if premier_passage:
        print(f"Initialisation : {len(offers)} annonces enregistrees, aucune alerte.")
    elif nouvelles:
        for path in nouvelles:
            url = offers[path]
            resume = describe(url)
            notify(f"🏠 Nouvelle annonce in'li\n{resume}\n{url}")
            time.sleep(1)
        print(f"{len(nouvelles)} nouvelle(s) annonce(s) signalee(s).")
    else:
        print(f"Rien de neuf ({len(offers)} annonces en ligne).")

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(offers), f, ensure_ascii=False, indent=0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
