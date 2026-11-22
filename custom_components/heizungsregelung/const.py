"""Konstanten der Heizungsregelung."""

from __future__ import annotations

DOMAIN = "heizungsregelung"
PLATFORMS = ["binary_sensor", "datetime", "number", "select", "sensor", "switch"]

# --- Grundeinstellungen (config entry data/options) ---
CONF_BOILER = "boiler_climate"
CONF_OUTDOOR = "outdoor_sensor"
CONF_PERSONS = "persons"
CONF_LABEL_ALLTAG = "label_alltag"
CONF_LABEL_URLAUB = "label_urlaub"
CONF_ABWESEND_PLAN = "abwesend_plan"
CONF_URLAUB_PLAN_RUN = "urlaub_plan_run"
CONF_NOTIFY = "notify_services"
CONF_ROOMS = "rooms"

# --- Raum ---
CONF_ROOM_ID = "room_id"
CONF_ROOM_NAME = "name"
CONF_ROOM_CLIMATE = "climate"
CONF_ROOM_SENSOR = "temperature_sensor"
CONF_ROOM_WINDOW = "window_sensor"
CONF_ROOM_IN_DEMAND = "in_demand"
CONF_ROOM_MAX_TEMP = "max_temperature"
# Ausnahme bei Abwesenheit (z. B. Kinderzimmer nachmittags)
CONF_ROOM_EXC_ENABLED = "away_exception"
CONF_ROOM_EXC_START = "away_exception_start"
CONF_ROOM_EXC_END = "away_exception_end"
CONF_ROOM_EXC_END_FRI = "away_exception_end_friday"
CONF_ROOM_EXC_TEMP = "away_exception_temperature"
# Wiederkehrende Abwesenheit einer Person (z. B. jedes 2. Wochenende)
CONF_ROOM_RHYTHM = "rhythm"
CONF_ROOM_RHYTHM_WEEKDAY = "rhythm_weekday"
CONF_ROOM_RHYTHM_START = "rhythm_start"
CONF_ROOM_RHYTHM_HOURS = "rhythm_duration_hours"
CONF_ROOM_RHYTHM_DAYS = "rhythm_interval_days"
CONF_ROOM_RHYTHM_TEMP = "rhythm_temperature"
# Fenster-Erinnerung
CONF_ROOM_REMIND = "window_reminder"
CONF_ROOM_HUMIDITY = "humidity_sensor"
CONF_ROOM_REMIND_MINUTES = "reminder_minutes"
CONF_ROOM_REMIND_HUMIDITY = "reminder_humidity_below"

# --- Parameter (Number-Entitäten), Schlüssel -> (Name, min, max, step, default, unit) ---
PARAMS: dict[str, tuple[str, float, float, float, float, str | None]] = {
    "schub_faktor": ("Schub-Faktor", 0.0, 5.0, 0.1, 1.5, None),
    "schub_maximum": ("Schub maximal", 0.0, 6.0, 0.5, 3.0, "K"),
    "ruhe_sollwert": ("Ruhe-Sollwert", 5.0, 20.0, 0.5, 15.0, "°C"),
    "start_schwelle": ("Start-Schwelle", 0.0, 2.0, 0.1, 0.3, "K"),
    "stopp_schwelle": ("Stopp-Schwelle", -1.0, 1.0, 0.1, 0.0, "K"),
    "mindestpause": ("Mindestpause", 0.0, 120.0, 1.0, 20.0, "min"),
    "lueften_grenze": ("Lüften: Schub-Grenze", 0.0, 2.0, 0.1, 0.5, "K"),
    "lueften_nachlauf": ("Lüften: Nachlaufzeit", 0.0, 120.0, 1.0, 30.0, "min"),
    "abwesend_temp": ("Abwesenheitstemperatur", 12.0, 22.0, 0.5, 18.0, "°C"),
    "heimkehr_temp": ("Heimkehrtemperatur", 15.0, 24.0, 0.5, 20.0, "°C"),
    "urlaub_weg_temp": ("Urlaub-weg-Temperatur", 8.0, 20.0, 0.5, 16.0, "°C"),
    "abwesend_verzoegerung": ("Abwesend nach", 0.0, 120.0, 1.0, 10.0, "min"),
    "sollwert_min": ("Kessel-Sollwert minimal", 5.0, 20.0, 0.5, 12.0, "°C"),
    "sollwert_max": ("Kessel-Sollwert maximal", 18.0, 30.0, 0.5, 26.0, "°C"),
}

# Kessel-Sollwert: wann wird geschrieben (wie in der bisherigen Automation)
SETPOINT_MIN_DELTA_IMMEDIATE = 2.0  # K
SETPOINT_MIN_DELTA_DELAYED = 1.0  # K
SETPOINT_DELAY_SECONDS = 900
LOOP_SECONDS = 60
BEDARF_CLAMP = 2.0
NIGHT_START = "22:00"
NIGHT_END = "05:00"

BOILER_EVAL_SECONDS = 300  # wie time_pattern /5 der alten Automation
BEDARF_STABLE_SECONDS = 120  # Entprellung wie "for: 2 min"
GUARD_DELAY_SECONDS = 5
REMINDER_REPEAT_SECONDS = 1800
HEIMKEHR_SETTLE_SECONDS = 5

MODE_ALLTAG = "alltag"
MODE_URLAUB_ZUHAUSE = "urlaub_zuhause"
MODE_URLAUB_WEG = "urlaub_weg"
MODES = [MODE_ALLTAG, MODE_URLAUB_ZUHAUSE, MODE_URLAUB_WEG]
MODE_LABELS = {
    MODE_ALLTAG: "Alltag",
    MODE_URLAUB_ZUHAUSE: "Urlaub zuhause",
    MODE_URLAUB_WEG: "Urlaub weg",
}

WEEKDAY_LABELS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

CONF_ROOM_HEIMKEHR = "heimkehr_boost"

ROOM_DEFAULTS = {
    CONF_ROOM_IN_DEMAND: True,
    CONF_ROOM_HEIMKEHR: True,
    CONF_ROOM_EXC_ENABLED: False,
    CONF_ROOM_EXC_TEMP: 20.0,
    CONF_ROOM_RHYTHM: False,
    CONF_ROOM_RHYTHM_WEEKDAY: "4",
    CONF_ROOM_RHYTHM_START: "16:00:00",
    CONF_ROOM_RHYTHM_HOURS: 47.0,
    CONF_ROOM_RHYTHM_DAYS: 14.0,
    CONF_ROOM_RHYTHM_TEMP: 18.0,
    CONF_ROOM_REMIND: False,
    CONF_ROOM_REMIND_MINUTES: 15.0,
    CONF_ROOM_REMIND_HUMIDITY: 65.0,
}

# Übernahme aus einer bestehenden Helfer-Lösung beim allerersten Start.
# Fehlt ein Helfer, gilt der Standardwert aus PARAMS.
LEGACY_PARAM_HELPERS = {
    "schub_faktor": "input_number.heizung_schub_faktor",
    "schub_maximum": "input_number.heizung_schub_maximum",
    "ruhe_sollwert": "input_number.heizung_kessel_ruhe_sollwert",
    "start_schwelle": "input_number.heizung_kessel_start_schwelle",
    "stopp_schwelle": "input_number.heizung_kessel_stopp_schwelle",
    "mindestpause": "input_number.heizung_kessel_mindestpause",
    "lueften_grenze": "input_number.heizung_luften_schub_grenze",
    "lueften_nachlauf": "input_number.heizung_luften_nachlaufzeit",
    "abwesend_temp": "input_number.heizung_abwesenheit_temperatur",
    "heimkehr_temp": "input_number.heizung_heimkehr_temperatur",
}
LEGACY_HEIZT = "input_boolean.heizung_kessel_heizt"
LEGACY_AWAY = "input_boolean.heizung_abwesenheit"
LEGACY_URLAUB_ZUHAUSE = "input_boolean.urlaub_zuhause"
LEGACY_URLAUB_WEG = "input_boolean.urlaub_abwesend"

STORAGE_VERSION = 1

SIGNAL_UPDATE = f"{DOMAIN}_update_{{}}"
