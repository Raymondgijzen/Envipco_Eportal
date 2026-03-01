# Envipco ePortal -- Home Assistant Custom Component

Home Assistant custom component voor het uitlezen van Envipco
statiegeldautomaten via de ePortal API.

Deze integratie haalt status, bin-informatie, rejects en
opbrengstgegevens op en maakt deze beschikbaar als sensoren en binary
sensors in Home Assistant.

------------------------------------------------------------------------

## Functionaliteit

### Machine status

-   Status (Ready / Processing / Error / etc.)
-   Laatste rapportage
-   Online / storing detectie (binary_sensor)

### Bins

-   Alleen gebruikte bins worden automatisch aangemaakt
-   Aantal ingeleverde items per bin
-   Vulling in %
-   "Bijna vol" (binary_sensor)
-   "Vol" (binary_sensor)
-   Instelbare limieten per machine en per bin
-   Modelprofielen (Quantum / Optima) met eigen defaults

### Reject informatie

-   Reject totaal
-   Reject percentage\
    Formule:\
    `rejects / (accepted + rejects)`

### Opbrengst

-   Vergoeding instelbaar per machine:
    -   CAN
    -   PET
-   Opbrengst per:
    -   Dag
    -   Week
    -   Maand
    -   Jaar
-   Opbrengst uitgesplitst per materiaal

### Extra functies

-   Update-now knop
-   Instelbare update-intervallen (status / statistieken apart)
-   Nederlandse vertalingen
-   Blueprint voor pushmeldingen in de Home Assistant app

------------------------------------------------------------------------

## Ondersteunde automaten

Getest met:

-   Quantum (090290, 090368, 090340)
-   Optima (075979)

Nieuwe machines kunnen worden toegevoegd via "Scan op nieuwe automaten".

------------------------------------------------------------------------

## Installatie (handmatig)

1.  Kopieer de map:

custom_components/envipco_eportal

naar:

/config/custom_components/

2.  Herstart Home Assistant\
3.  Ga naar:

Instellingen → Apparaten & Diensten → Integraties

4.  Voeg "Envipco ePortal" toe\
5.  Vul je ePortal inloggegevens in

------------------------------------------------------------------------

## Configuratie

Via:

Instellingen → Apparaten & Diensten → Envipco ePortal → Opties

Kun je instellen:

-   Vergoedingen per machine (CAN / PET)
-   Update-interval status
-   Update-interval statistieken
-   Bin limieten per machine
-   Modelprofiel per machine
-   Scan op nieuwe automaten

------------------------------------------------------------------------

## Pushmeldingen (Home Assistant app)

De meegeleverde blueprint bevindt zich in:

blueprints/automation/rvm/rvm_push_hass_app.yaml

Ondersteunt:

-   Bijna vol meldingen
-   Vol meldingen
-   Storing meldingen
-   Cooldown tegen spam
-   Meerdere telefoons
-   Hoge prioriteit
-   Deeplink naar de betreffende entiteit

------------------------------------------------------------------------

## Entiteiten

Per machine worden onder andere aangemaakt:

### Sensors

-   Status
-   Laatste rapport
-   Accepted totaal
-   Accepted CAN
-   Accepted PET
-   Reject totaal
-   Reject percentage
-   Revenue today / week / month / year
-   Revenue CAN today
-   Revenue PET today
-   Bin X count
-   Bin X vulling %

### Binary sensors

-   Machine storing
-   Bin X bijna vol
-   Bin X vol

------------------------------------------------------------------------

## Architectuur

-   DataUpdateCoordinator voor API polling
-   Gescheiden polling voor status en statistieken
-   API token caching (15 minuten sessie)
-   Minimale API requests per dag
-   Bin thresholds worden lokaal berekend (geen extra API calls)

------------------------------------------------------------------------

## Veiligheid

-   Geen credentials opgeslagen in code
-   API key opgeslagen in config entry
-   Geen logging van gevoelige gegevens

------------------------------------------------------------------------

## Versiebeheer

Volgt semantische versieopbouw:

-   Major → breaking changes\
-   Minor → nieuwe functionaliteit\
-   Patch → bugfixes

------------------------------------------------------------------------

## Licentie

Privé project. Gebruik en verspreiding alleen met toestemming van de
eigenaar.
