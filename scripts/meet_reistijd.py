#!/usr/bin/env python3
"""Meet de reistijd met de auto tussen thuis en werk.

Wordt gestart door GitHub Actions, ruim voor elk meetvenster (GitHub start geplande
workflows soms tot een uur te laat, daarom zijn er meerdere starttijden):
  heen  (thuis -> werk): vertrek 07:00 t/m 07:30, elke 5 minuten
  terug (werk -> thuis): vertrek 16:00 t/m 17:00, elke 5 minuten

Het script wacht zelf tot elk meetmoment en vraagt dan bij TomTom de actuele
reistijd op (met live verkeer). Elke meting komt als regel in data/reistijden.csv.

Gebruik:
  python3 scripts/meet_reistijd.py auto   # kiest zelf het venster dat nu (bijna) loopt
  python3 scripts/meet_reistijd.py test   # doet één meting per richting, schrijft niets weg
  python3 scripts/meet_reistijd.py samenvoegen <csv>  # voegt metingen uit <csv> toe aan data/,
                                                      # zonder dubbele regels

Omgevingsvariabelen (in GitHub als repository secrets):
  TOMTOM_API_KEY  je TomTom API key
  ADRES_THUIS     bijv. "Dorpsstraat 1, Plaatsnaam"
  ADRES_WERK      idem, voor het werkadres
                  (of coördinaten, bijv. "52.3000, 4.8600", voor een exact punt)

Privacy: de logs van een openbare repository zijn voor iedereen te zien. Het script
print daarom nooit adressen of coördinaten, alleen of het adres herkend is.
"""

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Amsterdam")

# Meetvensters: (start uur, start minuut), (eind uur, eind minuut) — eind telt mee.
WINDOWS = {
    "heen": ((7, 0), (7, 30)),
    "terug": ((16, 0), (17, 0)),
}
INTERVAL_MIN = 5
MAX_VROEG_MIN = 100     # start alleen als het venster binnen 100 min begint
TE_LAAT_SEC = 120       # meetmoment dat langer dan 2 min voorbij is: overslaan

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "reistijden.csv"
FIELDS = [
    "datum", "weekdag", "richting", "vertrektijd", "gemeten_om",
    "reistijd_min", "zonder_verkeer_min", "vertraging_min", "aankomst", "afstand_km",
]
WEEKDAGEN = ["ma", "di", "wo", "do", "vr", "za", "zo"]

API = "https://api.tomtom.com"


# --- kleine hulpfuncties (los gehouden zodat ze te testen zijn) -------------

def now_local() -> datetime:
    return datetime.now(TZ)


def sleep_until(moment: datetime) -> None:
    wacht = (moment - now_local()).total_seconds()
    if wacht > 0:
        time.sleep(wacht)


def api_get(url: str) -> dict:
    """GET met een paar herhaalpogingen bij netwerk- of serverfouten."""
    laatste_fout = None
    for poging in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 404):
                body = e.read().decode("utf-8", "replace")[:300]
                raise SystemExit(f"TomTom gaf fout {e.code}: {body}")
            laatste_fout = e
        except (urllib.error.URLError, TimeoutError) as e:
            laatste_fout = e
        time.sleep(5 * (poging + 1))
    raise RuntimeError(f"TomTom niet bereikbaar: {laatste_fout}")


# --- TomTom ---------------------------------------------------------------

def _norm(tekst: str) -> str:
    return "".join(ch for ch in tekst.lower() if ch.isalnum())


def geocode(key: str, adres: str, label: str) -> str:
    # Coördinaten ("52.30, 4.86") direct gebruiken, zonder opzoeken.
    delen = [d.strip() for d in adres.split(",")]
    if len(delen) == 2:
        try:
            lat, lon = float(delen[0]), float(delen[1])
            if 50 < lat < 54 and 3 < lon < 8:
                print(f"  adres {label}: coördinaten gebruikt")
                return f"{lat},{lon}"
        except ValueError:
            pass
    q = urllib.parse.quote(adres)
    url = f"{API}/search/2/geocode/{q}.json?key={key}&countrySet=NL&limit=1&language=nl-NL"
    data = api_get(url)
    if not data.get("results"):
        raise SystemExit(f"Adres {label} niet gevonden door TomTom. Controleer het secret.")
    res = data["results"][0]
    pos = res["position"]
    # Controle zonder het adres in het (openbare) log te zetten: komt straat + huisnummer overeen?
    gevraagd = _norm(adres.split(",")[0])
    gevonden = res.get("address", {})
    gevonden_txt = _norm(f"{gevonden.get('streetName', '')}{gevonden.get('streetNumber', '')}")
    if gevraagd and gevraagd == gevonden_txt:
        print(f"  adres {label}: herkend (straat en huisnummer kloppen)")
    else:
        print(f"  adres {label}: LET OP, TomTom vond een iets ander adres "
              f"(soort resultaat: {res.get('type', '?')}). Controleer het secret.")
    return f"{pos['lat']},{pos['lon']}"


def route(key: str, van: str, naar: str) -> dict:
    params = urllib.parse.urlencode({
        "key": key,
        "traffic": "true",
        "travelMode": "car",
        "routeType": "fastest",
        "departAt": "now",
        "computeTravelTimeFor": "all",
    })
    url = f"{API}/routing/1/calculateRoute/{van}:{naar}/json?{params}"
    data = api_get(url)
    return data["routes"][0]["summary"]


# --- logica ---------------------------------------------------------------

def meetmomenten(richting: str, dag: datetime) -> list:
    (sh, sm), (eh, em) = WINDOWS[richting]
    start = dag.replace(hour=sh, minute=sm, second=0, microsecond=0)
    eind = dag.replace(hour=eh, minute=em, second=0, microsecond=0)
    momenten = []
    t = start
    while t <= eind:
        momenten.append(t)
        t += timedelta(minutes=INTERVAL_MIN)
    return momenten


def kies_venster(nu: datetime):
    """Geeft de richting waarvan het venster nu loopt of binnenkort begint."""
    for richting in WINDOWS:
        m = meetmomenten(richting, nu)
        if m[0] - timedelta(minutes=MAX_VROEG_MIN) <= nu <= m[-1] + timedelta(seconds=TE_LAAT_SEC):
            return richting
    return None


def al_gemeten(datum: str, richting: str) -> set:
    if not CSV_PATH.exists():
        return set()
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        return {r["vertrektijd"] for r in csv.DictReader(f)
                if r["datum"] == datum and r["richting"] == richting}


def schrijf_regel(regel: dict) -> None:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    nieuw = not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        if nieuw:
            w.writeheader()
        w.writerow(regel)


def samenvoegen(extra_pad: str) -> None:
    """Voeg regels uit extra_pad toe aan CSV_PATH; per datum+richting+vertrektijd één regel."""
    def lees(pad):
        pad = Path(pad)
        if not pad.exists() or pad.stat().st_size == 0:
            return []
        with pad.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    regels = {}
    for r in lees(CSV_PATH) + lees(extra_pad):
        regels.setdefault((r["datum"], r["richting"], r["vertrektijd"]), r)
    volgorde = sorted(regels.values(), key=lambda r: (r["datum"], r["richting"] != "heen", r["vertrektijd"]))
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(volgorde)
    print(f"{len(volgorde)} metingen in {CSV_PATH.name}")


def maak_regel(richting: str, moment: datetime, gemeten: datetime, s: dict) -> dict:
    reis = s["travelTimeInSeconds"]
    zonder = s.get("noTrafficTravelTimeInSeconds", reis - s.get("trafficDelayInSeconds", 0))
    aankomst = gemeten + timedelta(seconds=reis)
    return {
        "datum": moment.strftime("%Y-%m-%d"),
        "weekdag": WEEKDAGEN[moment.weekday()],
        "richting": richting,
        "vertrektijd": moment.strftime("%H:%M"),
        "gemeten_om": gemeten.strftime("%H:%M:%S"),
        "reistijd_min": round(reis / 60, 1),
        "zonder_verkeer_min": round(zonder / 60, 1),
        "vertraging_min": round(max(reis - zonder, 0) / 60, 1),
        "aankomst": aankomst.strftime("%H:%M"),
        "afstand_km": round(s["lengthInMeters"] / 1000, 1),
    }


def env(naam: str) -> str:
    waarde = os.environ.get(naam, "").strip()
    if not waarde:
        raise SystemExit(f"Ontbrekende instelling: {naam} (zet hem als repository secret)")
    return waarde


def main(modus: str) -> None:
    if modus == "samenvoegen":
        samenvoegen(sys.argv[2])
        return
    key = env("TOMTOM_API_KEY")
    thuis_adres, werk_adres = env("ADRES_THUIS"), env("ADRES_WERK")
    nu = now_local()

    if modus == "test":
        print("Testmeting (wordt niet opgeslagen):")
        thuis, werk = geocode(key, thuis_adres, "thuis"), geocode(key, werk_adres, "werk")
        for richting, (van, naar) in {"heen": (thuis, werk), "terug": (werk, thuis)}.items():
            r = maak_regel(richting, nu, nu, route(key, van, naar))
            print(f"  {richting}: {r['reistijd_min']} min "
                  f"(zonder verkeer {r['zonder_verkeer_min']}, {r['afstand_km']} km)")
        return

    if nu.weekday() >= 5:
        print("Weekend: geen meting.")
        return

    richting = kies_venster(nu)
    if richting is None:
        print(f"{nu:%H:%M}: geen meetvenster in de buurt, klaar.")
        return

    datum = nu.strftime("%Y-%m-%d")
    gedaan = al_gemeten(datum, richting)
    if all(m.strftime("%H:%M") in gedaan for m in meetmomenten(richting, nu)):
        print(f"Venster '{richting}' op {datum} is al volledig gemeten, klaar.")
        return
    print(f"Meetvenster '{richting}' op {datum}.")
    thuis, werk = geocode(key, thuis_adres, "thuis"), geocode(key, werk_adres, "werk")
    van, naar = (thuis, werk) if richting == "heen" else (werk, thuis)

    for moment in meetmomenten(richting, nu):
        label = moment.strftime("%H:%M")
        if label in gedaan:
            print(f"  {label}: al gemeten, overslaan")
            continue
        if now_local() > moment + timedelta(seconds=TE_LAAT_SEC):
            print(f"  {label}: voorbij (workflow startte te laat), overslaan")
            continue
        sleep_until(moment)
        try:
            samenvatting = route(key, van, naar)
        except RuntimeError as e:
            print(f"  {label}: mislukt ({e})")
            continue
        regel = maak_regel(richting, moment, now_local(), samenvatting)
        schrijf_regel(regel)
        print(f"  {label}: {regel['reistijd_min']} min, aankomst {regel['aankomst']} "
              f"(+{regel['vertraging_min']} min vertraging)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "auto")
