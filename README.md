# De Witte Schare voor Home Assistant

Custom integratie die het KNLTB.Club-afhangbord van tennis- en padelvereniging
De Witte Schare (Schaijk) uitleest, om bijvoorbeeld de verwarming van het
paviljoen te sturen op drukte.

Bron: de openbare pagina `https://www.witteschare.nl/afhangbord-overzicht`
(intern `/courtbooking-overview/GetBookings`). Er is geen login nodig en er
staan geen namen in, alleen baan, tijd, soort en aantal spelers.

## Installatie

1. HACS → Integraties → menu → *Aangepaste repositories* →
   `https://github.com/ganzewin/ha-witte-schare`, categorie *Integratie*.
2. Installeer **De Witte Schare** en herstart Home Assistant.
3. Instellingen → Apparaten en diensten → Integratie toevoegen → *De Witte Schare*.
   De standaard-URL `https://www.witteschare.nl` werkt voor onze club; een andere
   KNLTB.Club-clubsite werkt waarschijnlijk ook.

Opties (via *Configureren*): hoeveel minuten vooruit "binnenkort" telt
(standaard 90) en hoeveel dagen vooruit worden opgehaald (standaard 7).

## Entiteiten

Alle entiteiten hangen aan het apparaat **Afhangbord**.

| Entiteit | Wat |
|---|---|
| Banen bezet / Tennisbanen bezet / Padelbanen bezet | aantal banen dat nu in gebruik is (attributen: banen, soorten, spelers) |
| Spelers nu | som van "n spelers" van lopende reserveringen (trainingen en competitie tellen 0) |
| Banen bezet komende periode | banen met een reservering binnen het vooruitkijk-venster |
| Reserveringen vandaag | aantal, met verdeling per soort |
| Eerste reservering vandaag / Laatste eindtijd vandaag | tijdstempels |
| Volgende activiteit / Einde huidige activiteit | begin van het volgende en eind van het huidige aaneengesloten blok |
| Activiteit nu / Activiteit binnenkort | binary sensors (occupancy) |
| Agenda *Reserveringen* | elke reservering als afspraak |
| Agenda *Activiteit* | aaneengesloten blokken waarin minstens één baan bezet is |

"Gesloten"-blokken tellen nergens mee als activiteit.

Soorten die voorkomen: Baanreservering, Training, Competitie, Toernooi, Toss,
Meet & Play boeking, Gesloten.

### Let op

* Vooraf zichtbaar zijn vooral vaste blokken (training, competitie, toernooi)
  en reserveringen die via de app zijn gemaakt. Reserveringen op het bord zelf
  verschijnen pas als ze gemaakt worden.
* Vandaag wordt elke 5 minuten opgehaald, de komende dagen elk uur. De
  "nu"-sensoren worden daarnaast elk kwartier herberekend.

## Voorbeeld: paviljoen voorverwarmen

```yaml
automation:
  - alias: Paviljoen voorverwarmen voor activiteit
    triggers:
      - trigger: calendar
        event: start
        entity_id: calendar.afhangbord_activiteit  # controleer de echte entity_id in HA
        offset: "-01:00:00"
    actions:
      - action: climate.set_temperature
        target:
          entity_id: climate.zone_circuit_paviljoen_paviljoen
        data:
          temperature: 20
```

## Ontwikkelen

```bash
pip install -r requirements_test.txt
pytest
```

De parser (`custom_components/witte_schare/parser.py`) heeft geen afhankelijkheid
van Home Assistant. Als LISA de site aanpast, sla de nieuwe pagina op in
`tests/fixtures/` en pas de parser aan.

## Gepland

* Bardiensten (vereist inloggen op de clubsite).
