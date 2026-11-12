# Reistijd thuis ⇄ werk

Dit project meet elke werkdag automatisch de reistijd met de auto, met actueel verkeer:

| Richting | Vertrek | Meetmomenten |
|---|---|---|
| Heen (thuis → werk) | 07:00 – 07:30 | elke 5 min (7 metingen) |
| Terug (werk → thuis) | 16:00 – 17:00 | elke 5 min (13 metingen) |

Alles draait gratis in de cloud (GitHub Actions + TomTom), dus je pc of telefoon hoeft niet aan te staan.
De metingen komen in `data/reistijden.csv`. Een dashboard (`index.html`, via GitHub Pages) laat de reistijd per
vertrektijd zien, de beste vertrektijd en een overzicht per dag.

## Eenmalig instellen (± 15 minuten)

### 1. TomTom API key (gratis)
1. Ga naar <https://my.tomtom.com> en maak een account aan (geen creditcard nodig).
2. Open **API & SDK Keys**. Gebruik de key die er al staat of maak een nieuwe aan, en kopieer hem.
   Gratis: 20.000 route-verzoeken en 20.000 geocodeer-verzoeken per maand. Dit project gebruikt er zo'n 450 en 90 per maand.

### 2. GitHub-repository
1. Maak een account op <https://github.com>.
2. Klik **New repository**, noem hem bijvoorbeeld `reistijd` en kies **Public**.
   *Waarom public:* zo zijn GitHub Actions en GitHub Pages gratis zonder limiet. Een private repository komt
   boven de gratis 2.000 minuten per maand uit. Je adressen staan **niet** in de code maar in geheime
   instellingen (stap 3). Wel openbaar zijn de reistijden zelf en het dashboard.
3. Zet de bestanden van dit project in de repository: **Add file → Upload files**, en sleep de inhoud van de
   uitgepakte map erin (dus `index.html`, `README.md`, en de mappen `scripts`, `data` en `.github`).
   Controleer na het uploaden dat het bestand `.github/workflows/reistijd.yml` er echt in staat.
   (Op een Mac zie je mappen die met een punt beginnen pas met Cmd+Shift+punt.)

### 3. Geheime instellingen (secrets)
Ga in de repository naar **Settings → Secrets and variables → Actions → New repository secret** en maak deze drie aan:

| Naam | Waarde |
|---|---|
| `TOMTOM_API_KEY` | je key uit stap 1 |
| `ADRES_THUIS` | je thuisadres, bijv. `Dorpsstraat 1, Plaatsnaam` |
| `ADRES_WERK` | je werkadres, in dezelfde vorm |

### 4. Dashboard aanzetten
**Settings → Pages → Build and deployment**: kies *Deploy from a branch*, branch `main`, map `/ (root)`, en **Save**.
Na een paar minuten staat het dashboard op `https://<jouw-gebruikersnaam>.github.io/reistijd/`.
Zet die link op het beginscherm van je telefoon.

### 5. Testen
**Actions → Reistijd meten → Run workflow**, met modus `test`. Na ongeveer 20 seconden zie je in het log
of TomTom beide adressen heeft herkend en wat de huidige reistijd in beide richtingen is. Er wordt dan
niets opgeslagen. De logs van een openbare repository zijn voor iedereen zichtbaar, daarom print het script
nooit adressen of coördinaten.

Daarna gaat het vanzelf: de eerste echte metingen komen op de eerstvolgende werkdag om 07:00.

## Hoe het werkt
- GitHub start geplande workflows soms tot een uur te laat. Daarom staat er elk half uur een start in de
  cron, ruim voor elk venster. De eerste run die binnen 100 minuten voor het venster binnenkomt, wacht en meet.
  De andere runs stoppen meteen.
- Komen twee runs toch tegelijk binnen, dan worden de metingen bij het opslaan samengevoegd, zonder dubbele regels.
- Het script wacht zelf tot elk meetmoment. Daardoor zijn de metingen precies om 07:00, 07:05, … ook al start
  GitHub soms een paar minuten later dan gepland.
- Na het laatste meetmoment commit de workflow de nieuwe regels in `data/reistijden.csv`, waarna het dashboard
  wordt bijgewerkt.
- Elke regel bevat: datum, weekdag, richting, vertrektijd, reistijd, reistijd zonder verkeer, vertraging,
  verwachte aankomst en afstand. Je kunt de CSV ook in Excel openen.

## Als iets niet werkt
- **Workflow faalt bij "Metingen opslaan" met "permission denied"**: Settings → Actions → General →
  Workflow permissions → *Read and write permissions*.
- **"Ontbrekende instelling"**: een secret heeft een andere naam of is leeg (stap 3).
- **TomTom geeft fout 403**: de key klopt niet, of Routing/Search staat niet aan voor deze key in het TomTom-dashboard.
- **Een meetmoment ontbreekt**: GitHub startte alle runs van die ochtend of middag te laat. Gemiste momenten
  worden overgeslagen.
- **Tijden aanpassen**: wijzig `WINDOWS` bovenin `scripts/meet_reistijd.py`. Als het venster ver verschuift,
  pas dan ook de cron-uren in `.github/workflows/reistijd.yml` aan.
