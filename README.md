# Heizungsregelung für Home Assistant

Eigene Integration, die einen modulierenden Gaskessel nach dem tatsächlichen Wärmebedarf der Räume führt und dazu Anwesenheit, Urlaub und wiederkehrende Abwesenheiten (z. B. Kinder jedes 2. Wochenende) steuert. Entstanden aus einer Sammlung von Automationen für eine Remeha Tzerra Ace mit Better Thermostat und dem [Scheduler](https://github.com/nielsfaber/scheduler-component).

## Was sie macht

**Kesselregelung**
- Heizbedarf = größte Unterdeckung (Ziel − Ist) aller Räume, begrenzt auf ±2 K. Räume mit offenem Fenster zählen nicht; nach dem Lüften wird der Bedarf eines Raums für die Nachlaufzeit auf die Lüften-Grenze begrenzt.
- Kessel-Sollwert = Raumfühler des Kessels + Schub-Faktor × Bedarf (höchstens Schub maximal), auf 0,5 °C gerundet. Ohne Bedarf: Ruhe-Sollwert.
- Hysterese: Start ab der Start-Schwelle und nach der Mindestpause (ab 1 K Bedarf sofort), Stopp bei der Stopp-Schwelle.
- Geschrieben wird beim Wechsel Heizen ↔ Ruhe sofort, sonst ab 2 K sofort und ab 1 K frühestens nach 15 Minuten.

**Betriebsarten** (Auswahl-Entität *Betriebsart*)
- *Alltag*: Scheduler-Pläne mit dem Alltags-Label laufen.
- *Urlaub zuhause*: Pläne mit dem Urlaubs-Label laufen.
- *Urlaub weg*: alle Pläne aus; der „Urlaub weg“-Plan läuft, oder alle Räume gehen auf die Urlaub-weg-Temperatur.

**Anwesenheit**
- Sind alle gewählten Personen länger als *Abwesend nach* weg: Pläne aus, Räume auf die Abwesenheitstemperatur.
- Ausnahme je Raum, z. B. Kinderzimmer nachmittags warm (eigenes Ende am Freitag möglich).
- Heimkehr: Pläne wieder an, der aktuelle Zeitslot wird sofort angewendet, und Räume werden mindestens auf die Heimkehrtemperatur gestellt (nachts 22–5 Uhr nicht).

**Wiederkehrende Abwesenheit je Raum**
- Schalter *Jedes 2. Wochenende weg* plus *Abwesend von/bis*. Der Raum hält dann die eingestellte Temperatur; ein Wächter stellt sie zurück, falls ein Plan dazwischenfunkt, und merkt sich den Planwert. Am Ende wird der Planwert wiederhergestellt und der Termin um das Intervall weitergeschoben.

**Je Raum außerdem**
- Höchsttemperatur: höhere Sollwerte (aus Plänen oder von Hand) werden zurückgestellt.
- Fenster-Erinnerung aufs Handy: nach X Minuten offen, optional erst wenn die Luftfeuchte unter dem Grenzwert liegt; höchstens alle 30 Minuten.

**Beobachtungsmodus**
Nach der Einrichtung ist der Schalter *Eingriffe aktiv* aus. Die Integration rechnet dann alles mit und schreibt nur ins Protokoll (Attribut `letzte_aktionen` des Sensors *Status*), was sie tun würde. So lässt sie sich gefahrlos neben einer bestehenden Lösung vergleichen.

## Installation über HACS

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/zmcjvzgbsr-cmyk/HA-Heizungsregelung`, Typ *Integration*.
2. *Heizungsregelung* installieren, Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Heizungsregelung*.
4. Grundeinstellungen ausfüllen, danach über *Konfigurieren → Raum hinzufügen* die Räume anlegen.

Voraussetzung: Home Assistant 2025.2 oder neuer. Für die Betriebsarten wird die Scheduler-Integration empfohlen (Pläne werden über Labels gefunden).

## Entitäten

| Entität | Zweck |
|---|---|
| `switch.…_eingriffe_aktiv` | Aus = Beobachtungsmodus |
| `select.…_betriebsart` | Alltag / Urlaub zuhause / Urlaub weg |
| `sensor.…_heizbedarf` | größte Unterdeckung, Attribut je Raum |
| `sensor.…_kessel_sollwert_berechnet` | Ergebnis der Regelung mit Grund |
| `sensor.…_status` | Betriebsart, Anwesenheit, Rhythmus-Termine, letzte Aktionen |
| `binary_sensor.…_kessel_heizt`, `…_alle_weg` | Zustände |
| `number.…` | alle Parameter (Schub, Schwellen, Temperaturen, Verzögerungen) |
| je Raum `sensor.heizung_<raum>_unterdeckung` | Ziel − Ist |
| je Rhythmus-Raum `switch`, `datetime` von/bis, `binary_sensor` *Gerade abwesend* | wiederkehrende Abwesenheit |

## Dashboard: Hausschnitt-Karte

Die Integration bringt die Karte `custom:heizung-haus-card` mit und lädt sie automatisch, eine Ressource muss nicht eingetragen werden (nach dem ersten Update einmal die App bzw. den Browser-Cache neu laden). Die Karte zeigt einen Hausschnitt mit allen Geschossen, den Kessel im Keller, Betriebsart, Anwesenheit, die Rhythmus-Abwesenheiten, den Schalter „Eingriffe aktiv“ und das Protokoll. Räume der Integration werden über ihre `room`-ID verknüpft; Räume ohne Thermostat lassen sich mit Name, optionalem Temperatursensor und Notiz ergänzen.

Empfohlen als eigenes Dashboard mit einer Ansicht vom Typ **Panel**:

```yaml
type: custom:heizung-haus-card
title: HAUS HEIZUNG
outdoor: sensor.aussentemperatur
roof_note: Dach · 12–16 cm gedämmt
tolerance: 0.5            # ± K, in denen ein Raum als „passt“ gilt
floors:
  - short: DG
    name: Dachgeschoss
    rooms:
      - room: fabienne                     # room_id aus der Integration
        valve: [sensor.ventil_bett, sensor.ventil_schreibtisch]
        grow: 1.3                          # relative Breite
      - name: Arbeitszimmer
        note: kein Thermostat
  - short: EG
    name: Erdgeschoss
    rooms:
      - room: wohnzimmer
        valve: sensor.wohnzimmer_ventilstellung
      - name: Flur EG
        temperature: sensor.flur_temperatur
basement:
  name: Keller · unbeheizt
  boiler_name: Remeha Tzerra Ace
  flow: sensor.vorlauf
  return: sensor.ruecklauf
  pressure: sensor.anlagendruck
  dhw: sensor.warmwasser_temperatur
  dhw_volume: 160
  gas_today_kwh: sensor.gas_energie_heute
  gas_today_m3: sensor.gas_volumen_heute
  gas_yesterday_kwh: sensor.gas_energie_gestern
  gas_yesterday_m3: sensor.gas_volumen_gestern
  gas_heating_m3: sensor.gas_heute_heizung     # Aufteilung, wird in kWh umgerechnet
  gas_dhw_m3: sensor.gas_heute_warmwasser
```

Farben: Cyan ⬇️ = zu kalt, Häkchen = passt, Orange ⬆️ = zu warm bzw. heizt, Magenta = Rhythmus-Abwesenheit. Antippen öffnet das Detailfenster der jeweiligen Entität.

## Umstieg von bestehenden Automationen

Beim allerersten Start übernimmt die Integration – falls vorhanden – die Werte dieser Helfer: `input_number.heizung_schub_faktor`, `…_schub_maximum`, `…_kessel_ruhe_sollwert`, `…_kessel_start_schwelle`, `…_kessel_stopp_schwelle`, `…_kessel_mindestpause`, `…_luften_schub_grenze`, `…_abwesenheit_temperatur`, `…_heimkehr_temperatur` sowie `input_boolean.heizung_kessel_heizt`, `…_heizung_abwesenheit`, `…_urlaub_zuhause`, `…_urlaub_abwesend`.

Empfohlener Ablauf:
1. Integration einrichten, Eingriffe aus lassen, ein paar Tage *Kessel-Sollwert berechnet* mit dem echten Sollwert vergleichen.
2. Alte Automationen **deaktivieren** (nicht löschen), dann *Eingriffe aktiv* einschalten.
3. Läuft alles, können die alten Automationen und Helfer entfernt werden.

## Entwicklung

Die Regel-Logik liegt ohne Home-Assistant-Abhängigkeit in `logic.py` und ist mit `pytest tests/test_logic.py` testbar.

## Lizenz

MIT
