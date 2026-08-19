#!/usr/bin/env python3
"""Veille des annonces in'li avec diagnostic et alerte en cas de panne."""

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
INCIDENT_FILE = STATE_FILE.replace(".json", "_incident.json")
MAX_PAGES = 15
DELAI_ALERTE = 6 * 3600  # une alerte de panne toutes les 6 h maximum

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

OFFER_RE = re.compile(
    r'''href=["'](?:https?://(?:www\.)?inli\.fr)?'''
    r'''(/location[^"'?#]*\d{5}/[^"'?#]+|/locations/offre/[^"'?#]+)["']'''
)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
DESC_RE = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)', re.I)


def fetch(url, essais=3):
    derniere = None
    for n in range(essais):
        try:
            req = Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "fr-FR,fr;q=0.9",
                "Referer": BASE + "/",
            })
            with urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:
            derniere = exc
            if n < essais - 1:
                time.sleep(8)
    raise derniere


def with_page(url, page):
    sep = "&" if "?" in url else "?"
    return "%s%spage=%d" % (url, sep, page)


def list_offers():
    offers = {}
    for page in range(1, MAX_PAGES + 1):
        try:
            page_html = fetch(with_page(SEARCH_URL, page))
        except Exception as exc:
            print("[warn] page %d illisible : %s" % (page, exc), file=sys.stderr)
            break

        found = set(OFFER_RE.findall(page_html))
        if page == 1:
            marqueur = "logements" in page_html.lower()
            print("[info] page 1 : %d caracteres, mot-cle present : %s, liens trouves : %d"
                  % (len(page_html), marqueur, len(found)))
            if not found:
                print("[info] extrait recu : %s" % re.sub(r"\s+", " ", page_html[:400]))

        nouveaux = found - set(offers)
        if not nouveaux:
            break
        for path in nouveaux:
            offers[path] = urljoin(BASE, path)
        time.sleep(2)
    return offers


def describe(url):
    try:
        page_html = fetch(url, essais=2)
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


def notify(message):
    token = os.environ.get("TG_TOKEN")
    chat = os.environ.get("TG_CHAT")
    print(message)
    if not token or not chat:
        return
    data = urlencode({"chat_id": chat, "text": message}).encode()
    try:
        urlopen(Request("https://api.telegram.org/bot%s/sendMessage" % token, data=data), timeout=30)
    except Exception as exc:
        print("[warn] envoi Telegram echoue : %s" % exc, file=sys.stderr)


def alerte_panne():
    """Previent sur Telegram, au maximum une fois toutes les six heures."""
    maintenant = time.time()
    try:
        with open(INCIDENT_FILE, encoding="utf-8") as f:
            dernier = json.load(f).get("dernier_envoi", 0)
    except Exception:
        dernier = 0
    if maintenant - dernier > DELAI_ALERTE:
        notify("⚠️ Veille in'li : aucune annonce detectee.\n"
               "Le site a peut-etre change, ou bloque temporairement les requetes.\n"
               "Voir le journal dans l'onglet Actions de GitHub.")
        with open(INCIDENT_FILE, "w", encoding="utf-8") as f:
            json.dump({"dernier_envoi": maintenant}, f)


def main():
    offers = list_offers()
    if not offers:
        print("[erreur] aucune annonce detectee : site modifie ou requete bloquee.", file=sys.stderr)
        alerte_panne()
        return 1

    premier = not os.path.exists(STATE_FILE)
    deja = set()
    if not premier:
        with open(STATE_FILE, encoding="utf-8") as f:
            deja = set(json.load(f))

    nouvelles = sorted(set(offers) - deja)

    if premier:
        print("Initialisation : %d annonces enregistrees, aucune alerte." % len(offers))
    elif nouvelles:
        for path in nouvelles:
            notify("🏠 Nouvelle annonce in'li\n%s\n%s" % (describe(offers[path]), offers[path]))
            time.sleep(1)
        print("%d nouvelle(s) annonce(s) signalee(s)." % len(nouvelles))
    else:
        print("Rien de neuf (%d annonces en ligne)." % len(offers))

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(offers), f, ensure_ascii=False, indent=0)
    if os.path.exists(INCIDENT_FILE):
        os.remove(INCIDENT_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
