"""Steuerung: verbindet die reine Logik mit Home Assistant."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import learn, logic
from .const import (
    BEDARF_CLAMP,
    BEDARF_STABLE_SECONDS,
    BOILER_EVAL_SECONDS,
    CONF_ABWESEND_PLAN,
    CONF_BOILER,
    CONF_FLOW_SENSOR,
    CONF_LABEL_ALLTAG,
    CONF_LABEL_URLAUB,
    CONF_NOTIFY,
    CONF_OUTDOOR,
    CONF_PERSONS,
    CONF_ROOM_CLIMATE,
    CONF_ROOM_EXC_ENABLED,
    CONF_ROOM_EXC_END,
    CONF_ROOM_EXC_END_FRI,
    CONF_ROOM_EXC_START,
    CONF_ROOM_EXC_TEMP,
    CONF_ROOM_HEIMKEHR,
    CONF_ROOM_HUMIDITY,
    CONF_ROOM_ID,
    CONF_ROOM_IN_DEMAND,
    CONF_ROOM_LEVELS,
    CONF_ROOM_RADIATORS,
    CONF_ROOM_TYPE,
    CONF_ROOM_VALVE,
    CONF_ROOM_MAX_TEMP,
    CONF_ROOM_NAME,
    CONF_ROOM_REMIND,
    CONF_ROOM_REMIND_HUMIDITY,
    CONF_ROOM_REMIND_MINUTES,
    CONF_ROOM_RHYTHM,
    CONF_ROOM_RHYTHM_DAYS,
    CONF_ROOM_RHYTHM_HOURS,
    CONF_ROOM_RHYTHM_START,
    CONF_ROOM_RHYTHM_TEMP,
    CONF_ROOM_RHYTHM_WEEKDAY,
    CONF_ROOM_SENSOR,
    CONF_ROOM_WINDOW,
    CONF_ROOMS,
    DOMAIN,
    GUARD_DELAY_SECONDS,
    HEIMKEHR_SETTLE_SECONDS,
    LEARN_HISTORY_DAYS,
    LEGACY_AWAY,
    LEGACY_HEIZT,
    LEGACY_PARAM_HELPERS,
    LEGACY_URLAUB_WEG,
    LEGACY_URLAUB_ZUHAUSE,
    LOOP_SECONDS,
    MODE_ALLTAG,
    MODE_LABELS,
    MODE_URLAUB_WEG,
    MODE_URLAUB_ZUHAUSE,
    MODES,
    NIGHT_END,
    NIGHT_START,
    PARAMS,
    REMINDER_REPEAT_SECONDS,
    ROOM_DEFAULTS,
    ROOM_TYPE_MANUAL,
    SETPOINT_DELAY_SECONDS,
    SETPOINT_MIN_DELTA_DELAYED,
    SETPOINT_MIN_DELTA_IMMEDIATE,
    SIGNAL_UPDATE,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)
_BAD = (STATE_UNAVAILABLE, STATE_UNKNOWN, None)


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class RoomConfig:
    """Konfiguration eines Raums (aus den Optionen)."""

    room_id: str
    name: str
    climate: str | None
    temperature_sensor: str | None
    window_sensor: str | None
    in_demand: bool
    heimkehr: bool
    max_temp: float | None
    exc_enabled: bool
    exc_start: Any
    exc_end: Any
    exc_end_fri: Any
    exc_temp: float
    rhythm: bool
    rhythm_weekday: int
    rhythm_start: Any
    rhythm_hours: float
    rhythm_days: int
    rhythm_temp: float
    remind: bool
    humidity_sensor: str | None
    remind_minutes: float
    remind_humidity: float
    manual: bool = False
    valve_sensors: list[str] = field(default_factory=list)
    levels: list[str] = field(default_factory=list)
    radiators: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RoomConfig:
        g = {**ROOM_DEFAULTS, **{k: v for k, v in d.items() if v is not None}}
        manual = g.get(CONF_ROOM_TYPE) == ROOM_TYPE_MANUAL or not g.get(CONF_ROOM_CLIMATE)
        levels = [x.strip() for x in str(g.get(CONF_ROOM_LEVELS) or "").split(",") if x.strip()]
        room = cls(
            room_id=g[CONF_ROOM_ID],
            name=g[CONF_ROOM_NAME],
            climate=None if manual else g[CONF_ROOM_CLIMATE],
            temperature_sensor=g.get(CONF_ROOM_SENSOR) or None,
            window_sensor=g.get(CONF_ROOM_WINDOW) or None,
            in_demand=bool(g[CONF_ROOM_IN_DEMAND]),
            heimkehr=bool(g[CONF_ROOM_HEIMKEHR]),
            max_temp=_float(g.get(CONF_ROOM_MAX_TEMP)) or None,
            exc_enabled=bool(g[CONF_ROOM_EXC_ENABLED]),
            exc_start=logic.parse_time(g.get(CONF_ROOM_EXC_START)),
            exc_end=logic.parse_time(g.get(CONF_ROOM_EXC_END)),
            exc_end_fri=logic.parse_time(g.get(CONF_ROOM_EXC_END_FRI)),
            exc_temp=float(g[CONF_ROOM_EXC_TEMP]),
            rhythm=bool(g[CONF_ROOM_RHYTHM]),
            rhythm_weekday=int(g[CONF_ROOM_RHYTHM_WEEKDAY]),
            rhythm_start=logic.parse_time(g[CONF_ROOM_RHYTHM_START]),
            rhythm_hours=float(g[CONF_ROOM_RHYTHM_HOURS]),
            rhythm_days=int(float(g[CONF_ROOM_RHYTHM_DAYS])),
            rhythm_temp=float(g[CONF_ROOM_RHYTHM_TEMP]),
            remind=bool(g[CONF_ROOM_REMIND]),
            humidity_sensor=g.get(CONF_ROOM_HUMIDITY) or None,
            remind_minutes=float(g[CONF_ROOM_REMIND_MINUTES]),
            remind_humidity=float(g[CONF_ROOM_REMIND_HUMIDITY]),
            manual=manual,
            valve_sensors=[v for v in (g.get(CONF_ROOM_VALVE) or []) if v],
            levels=levels or ["0"],
            radiators=g.get(CONF_ROOM_RADIATORS) or None,
        )
        if manual:
            # Handthermostat: nichts zu regeln, zählt nicht für den Kessel
            room.in_demand = False
            room.heimkehr = False
            room.exc_enabled = False
            room.rhythm = False
            room.max_temp = None
        return room


@dataclass
class RhythmState:
    """Laufzeitstatus einer wiederkehrenden Abwesenheit."""

    enabled: bool = False
    von: datetime | None = None
    bis: datetime | None = None
    active: bool = False
    plan_target: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "von": self.von.isoformat() if self.von else None,
            "bis": self.bis.isoformat() if self.bis else None,
            "active": self.active,
            "plan_target": self.plan_target,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RhythmState:
        return cls(
            enabled=bool(d.get("enabled")),
            von=dt_util.parse_datetime(d["von"]) if d.get("von") else None,
            bis=dt_util.parse_datetime(d["bis"]) if d.get("bis") else None,
            active=bool(d.get("active")),
            plan_target=d.get("plan_target"),
        )


@dataclass
class Snapshot:
    """Zuletzt berechneter Zustand für die Sensoren."""

    bedarf: logic.BedarfResult | None = None
    decision: logic.BoilerDecision | None = None
    room_targets: dict[str, float | None] = field(default_factory=dict)
    room_currents: dict[str, float | None] = field(default_factory=dict)
    learn: dict[str, dict[str, Any]] = field(default_factory=dict)


class Controller:
    """Heizungsregelung für einen Config-Entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.conf: dict[str, Any] = {**entry.data, **entry.options}
        self.rooms = [RoomConfig.from_dict(r) for r in self.conf.get(CONF_ROOMS, [])]
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._lock = asyncio.Lock()
        self._unsubs: list = []
        self._away_timer = None
        self._guard_timers: dict[str, Any] = {}

        self.params: dict[str, float] = {k: v[4] for k, v in PARAMS.items()}
        self.eingriffe_aktiv = False
        self.mode = MODE_ALLTAG
        self.away = False
        self.heizt = False
        self.modus_seit: datetime = dt_util.utcnow()
        self.kessel_geaendert: datetime | None = None
        self.rhythm: dict[str, RhythmState] = {r.room_id: RhythmState() for r in self.rooms if r.rhythm}
        self.window_closed_at: dict[str, datetime] = {}
        self.last_reminder: dict[str, datetime] = {}
        self.away_applied: dict[str, float] = {}
        self.manual_levels: dict[str, str] = {}
        self.snapshot = Snapshot()
        self.learners: dict[str, learn.RoomLearner] = {
            r.room_id: learn.RoomLearner() for r in self.rooms if not r.manual
        }
        self.learn_bootstrapped = False
        self._learn_buf: dict[str, deque] = {}
        self._learn_last_sample: datetime | None = None
        self._learn_count = 0
        self.log: deque[str] = deque(maxlen=25)

        self._last_boiler_eval: datetime | None = None
        self._bedarf_cand: float | None = None
        self._bedarf_cand_since: datetime | None = None
        self._bedarf_last_eval: float | None = None
        self._force_boiler = True

    # ------------------------------------------------------------------ Grundlagen
    @property
    def boiler(self) -> str:
        return self.conf[CONF_BOILER]

    @property
    def persons(self) -> list[str]:
        return list(self.conf.get(CONF_PERSONS) or [])

    def room(self, room_id: str) -> RoomConfig | None:
        return next((r for r in self.rooms if r.room_id == room_id), None)

    def _signal(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(self.entry.entry_id))

    def _note(self, text: str) -> None:
        stamp = dt_util.now().strftime("%d.%m. %H:%M")
        self.log.appendleft(f"{stamp} {text}")
        _LOGGER.info(text)

    def _save(self) -> None:
        self._store.async_delay_save(self._data_to_save, 2)

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "params": self.params,
            "eingriffe_aktiv": self.eingriffe_aktiv,
            "mode": self.mode,
            "away": self.away,
            "heizt": self.heizt,
            "modus_seit": self.modus_seit.isoformat(),
            "rhythm": {k: v.as_dict() for k, v in self.rhythm.items()},
            "manual_levels": self.manual_levels,
            "learn": {k: v.as_dict() for k, v in self.learners.items()},
            "learn_bootstrapped": self.learn_bootstrapped,
        }

    async def _call(self, domain: str, service: str, data: dict[str, Any], text: str) -> None:
        """Dienst aufrufen – im Beobachtungsmodus nur protokollieren."""
        if not self.eingriffe_aktiv:
            self._note(f"(Beobachtung) {text}")
            return
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True)
        except Exception as err:  # noqa: BLE001 - jede Fehlerart protokollieren
            self._note(f"Fehler bei {text}: {err}")
            _LOGGER.warning("Aufruf %s.%s fehlgeschlagen: %s", domain, service, err)
        else:
            self._note(text)

    # ------------------------------------------------------------------ Start/Stop
    async def async_setup(self) -> None:
        stored = await self._store.async_load()
        if stored:
            self._restore(stored)
        else:
            self._import_legacy()
        for room in self.rooms:
            if room.rhythm and room.room_id not in self.rhythm:
                self.rhythm[room.room_id] = RhythmState()

        self._unsubs.append(
            async_track_time_interval(self.hass, self._tick_cb, timedelta(seconds=LOOP_SECONDS))
        )
        if self.persons:
            self._unsubs.append(
                async_track_state_change_event(self.hass, self.persons, self._person_changed)
            )
        windows = [r.window_sensor for r in self.rooms if r.window_sensor]
        if windows:
            self._unsubs.append(
                async_track_state_change_event(self.hass, windows, self._window_changed)
            )
        climates = [r.climate for r in self.rooms if r.climate]
        if climates:
            self._unsubs.append(
                async_track_state_change_event(self.hass, climates, self._climate_changed)
            )
        self._unsubs.append(
            async_track_state_change_event(self.hass, [self.boiler], self._boiler_changed)
        )
        self._unsubs.append(async_at_started(self.hass, self._started))

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._away_timer:
            self._away_timer()
        for t in self._guard_timers.values():
            t()
        await self._store.async_save(self._data_to_save())

    def _restore(self, d: dict[str, Any]) -> None:
        for k, v in (d.get("params") or {}).items():
            if k in self.params and _float(v) is not None:
                self.params[k] = float(v)
        self.eingriffe_aktiv = bool(d.get("eingriffe_aktiv"))
        self.mode = d.get("mode") if d.get("mode") in MODES else MODE_ALLTAG
        self.away = bool(d.get("away"))
        self.heizt = bool(d.get("heizt"))
        if d.get("modus_seit"):
            self.modus_seit = dt_util.parse_datetime(d["modus_seit"]) or dt_util.utcnow()
        self.manual_levels.update({k: str(v) for k, v in (d.get("manual_levels") or {}).items()})
        for k, v in (d.get("learn") or {}).items():
            if k in self.learners:
                self.learners[k] = learn.RoomLearner(v)
        self.learn_bootstrapped = bool(d.get("learn_bootstrapped"))
        for k, v in (d.get("rhythm") or {}).items():
            self.rhythm[k] = RhythmState.from_dict(v)

    def _import_legacy(self) -> None:
        """Beim ersten Start Werte einer vorhandenen Helfer-Lösung übernehmen."""
        st = self.hass.states
        for key, entity_id in LEGACY_PARAM_HELPERS.items():
            state = st.get(entity_id)
            value = _float(state.state) if state else None
            if value is not None:
                self.params[key] = value
        if (s := st.get(LEGACY_HEIZT)) is not None:
            self.heizt = s.state == STATE_ON
            self.modus_seit = s.last_changed
        if (s := st.get(LEGACY_AWAY)) is not None:
            self.away = s.state == STATE_ON
        if (s := st.get(LEGACY_URLAUB_WEG)) is not None and s.state == STATE_ON:
            self.mode = MODE_URLAUB_WEG
        elif (s := st.get(LEGACY_URLAUB_ZUHAUSE)) is not None and s.state == STATE_ON:
            self.mode = MODE_URLAUB_ZUHAUSE
        self._note("Erster Start: Werte aus bestehenden Helfern übernommen (Beobachtungsmodus)")
        self._save()

    @callback
    def _started(self, _hass: HomeAssistant | None = None) -> None:
        self.hass.async_create_task(self._startup())

    async def _startup(self) -> None:
        # Anwesenheit nach dem Neustart prüfen
        home = self._anyone_home()
        if home is True and self.away:
            await self._heimkehr()
        elif home is False and not self.away:
            self._start_away_timer()
        await self.async_tick()
        if not self.learn_bootstrapped and self.learners and self.conf.get(CONF_OUTDOOR):
            self.hass.async_create_background_task(self._learn_bootstrap(), f"{DOMAIN}_learn_bootstrap")

    # ------------------------------------------------------------------ Taktgeber
    @callback
    def _tick_cb(self, _now: datetime) -> None:
        self.hass.async_create_task(self.async_tick())

    async def async_tick(self) -> None:
        async with self._lock:
            now = dt_util.now()
            await self._process_rhythm(now)
            await self._apply_away_temps()
            self._compute_bedarf()
            await self._maybe_eval_boiler()
            await self._check_reminders()
            self._learn_step()
        self._signal()

    # ------------------------------------------------------------------ Heizbedarf
    def _room_current(self, room: RoomConfig) -> float | None:
        if room.temperature_sensor:
            s = self.hass.states.get(room.temperature_sensor)
            if s is not None and s.state not in _BAD:
                return _float(s.state)
        c = (self.hass.states.get(room.climate) if room.climate else None)
        return _float(c.attributes.get("current_temperature")) if c else None

    def _room_target(self, room: RoomConfig) -> float | None:
        c = (self.hass.states.get(room.climate) if room.climate else None)
        return _float(c.attributes.get("temperature")) if c else None

    def _compute_bedarf(self) -> None:
        now = dt_util.utcnow()
        inputs = []
        snap = self.snapshot
        for room in self.rooms:
            c = (self.hass.states.get(room.climate) if room.climate else None)
            target = self._room_target(room)
            current = self._room_current(room)
            snap.room_targets[room.room_id] = target
            snap.room_currents[room.room_id] = current
            if not room.in_demand:
                continue
            window_open = False
            if room.window_sensor:
                w = self.hass.states.get(room.window_sensor)
                window_open = w is not None and w.state == STATE_ON
            closed = self.window_closed_at.get(room.room_id)
            inputs.append(
                logic.RoomInput(
                    name=room.name,
                    target=target,
                    current=current,
                    heating_allowed=c is not None and c.state not in ("off", *_BAD),
                    window_open=window_open,
                    window_closed_seconds=(now - closed).total_seconds() if closed else None,
                )
            )
        snap.bedarf = logic.heizbedarf(
            inputs,
            self.params["lueften_grenze"],
            self.params["lueften_nachlauf"] * 60,
            BEDARF_CLAMP,
        )

    # ------------------------------------------------------------------ Kessel
    async def _maybe_eval_boiler(self) -> None:
        bedarf = self.snapshot.bedarf
        if bedarf is None or bedarf.leading_room is None:
            # Kein Raum liefert Werte (noch keine Räume, Sensoren nicht verfügbar,
            # alle Fenster offen): Zustand halten, wie die alte Automation bei
            # einem unbekannten Heizbedarf.
            return
        now = dt_util.utcnow()
        if bedarf.value != self._bedarf_cand:
            self._bedarf_cand = bedarf.value
            self._bedarf_cand_since = now
        stable = (now - self._bedarf_cand_since).total_seconds() >= BEDARF_STABLE_SECONDS
        due = (
            self._force_boiler
            or self._last_boiler_eval is None
            or (now - self._last_boiler_eval).total_seconds() >= BOILER_EVAL_SECONDS
            or (stable and self._bedarf_cand != self._bedarf_last_eval)
        )
        if due:
            await self._eval_boiler(bedarf.value)

    async def _eval_boiler(self, bedarf: float) -> None:
        now = dt_util.utcnow()
        self._force_boiler = False
        self._last_boiler_eval = now
        self._bedarf_last_eval = bedarf
        state = self.hass.states.get(self.boiler)
        if state is None or state.state in ("off", *_BAD):
            return
        basis = _float(state.attributes.get("current_temperature"))
        if basis is None:
            return
        aktuell = _float(state.attributes.get("temperature"))
        p = self.params
        decision = logic.boiler_decision(
            bedarf=bedarf,
            basis=basis,
            aktuell=aktuell,
            heizt=self.heizt,
            seit_modus_s=(now - self.modus_seit).total_seconds(),
            seit_aenderung_s=(now - self.kessel_geaendert).total_seconds()
            if self.kessel_geaendert
            else 99999,
            p=logic.BoilerParams(
                schub_faktor=p["schub_faktor"],
                schub_maximum=p["schub_maximum"],
                ruhe_sollwert=p["ruhe_sollwert"],
                start_schwelle=p["start_schwelle"],
                stopp_schwelle=p["stopp_schwelle"],
                mindestpause_s=p["mindestpause"] * 60,
                sollwert_min=p["sollwert_min"],
                sollwert_max=p["sollwert_max"],
            ),
            immediate_delta=SETPOINT_MIN_DELTA_IMMEDIATE,
            delayed_delta=SETPOINT_MIN_DELTA_DELAYED,
            delay_s=SETPOINT_DELAY_SECONDS,
        )
        self.snapshot.decision = decision
        if decision.wechsel:
            self.heizt = decision.heizen
            self.modus_seit = now
            self._note("Kessel: Heizen" if decision.heizen else "Kessel: Ruhe")
            self._save()
        if decision.schreiben:
            await self._call(
                "climate",
                "set_temperature",
                {"entity_id": self.boiler, "temperature": decision.sollwert},
                f"Kessel-Sollwert {decision.sollwert:.1f} °C ({decision.grund}, Bedarf {bedarf:+.1f} K)",
            )

    @callback
    def _boiler_changed(self, event: Event) -> None:
        new, old = event.data.get("new_state"), event.data.get("old_state")
        if new is None:
            return
        t_new = new.attributes.get("temperature")
        t_old = old.attributes.get("temperature") if old else None
        if t_new != t_old:
            self.kessel_geaendert = dt_util.utcnow()

    # ------------------------------------------------------------------ Pläne / Modi
    def _label_switches(self, label: str | None) -> list[str]:
        if not label:
            return []
        reg = er.async_get(self.hass)
        return sorted(
            e.entity_id for e in er.async_entries_for_label(reg, label) if e.domain == "switch"
        )

    async def _apply_plans(self, run: bool = True) -> None:
        """Zeitpläne passend zu Betriebsart und Anwesenheit schalten."""
        alltag = self._label_switches(self.conf.get(CONF_LABEL_ALLTAG))
        urlaub = self._label_switches(self.conf.get(CONF_LABEL_URLAUB))
        abw = self.conf.get(CONF_ABWESEND_PLAN)
        if self.mode == MODE_URLAUB_WEG:
            on = [abw] if abw else []
            off = alltag + urlaub
        elif self.away:
            on, off = [], alltag + urlaub + ([abw] if abw else [])
        elif self.mode == MODE_URLAUB_ZUHAUSE:
            on, off = urlaub, alltag + ([abw] if abw else [])
        else:
            on, off = alltag, urlaub + ([abw] if abw else [])
        off = [e for e in off if e not in on]
        st = self.hass.states
        # Scheduler-Zustände: on, off, triggered, completed, unavailable
        off_now = [e for e in off if (s := st.get(e)) is not None and s.state != STATE_OFF]
        on_now = [e for e in on if (s := st.get(e)) is None or s.state == STATE_OFF]
        if off_now:
            await self._call("switch", "turn_off", {"entity_id": off_now}, f"Pläne aus: {', '.join(off_now)}")
        if on_now:
            await self._call("switch", "turn_on", {"entity_id": on_now}, f"Pläne an: {', '.join(on_now)}")
        if run and on and self.hass.services.has_service("scheduler", "run_action"):
            await asyncio.sleep(2)
            for ent in on:
                s = st.get(ent)
                if s is not None and s.attributes.get("current_slot") is not None:
                    await self._call(
                        "scheduler", "run_action", {"entity_id": ent}, f"Aktuellen Zeitslot anwenden: {ent}"
                    )
        if self.mode == MODE_URLAUB_WEG and not abw:
            t = self.params["urlaub_weg_temp"]
            for room in self.rooms:
                await self._set_room(room, t, "Urlaub weg", hvac=True)
        if self.away and self.mode != MODE_URLAUB_WEG:
            self.away_applied.clear()
            await self._apply_away_temps()

    async def async_set_mode(self, mode: str) -> None:
        if mode not in MODES or mode == self.mode:
            return
        async with self._lock:
            old = self.mode
            self.mode = mode
            self._note(f"Betriebsart: {MODE_LABELS[old]} → {MODE_LABELS[mode]}")
            self._save()
            await self._apply_plans(run=True)
            if old == MODE_URLAUB_WEG and not self.away:
                await self._heimkehr_boost()
        self._signal()

    async def async_set_eingriffe(self, aktiv: bool) -> None:
        async with self._lock:
            self.eingriffe_aktiv = aktiv
            self._note("Eingriffe aktiviert" if aktiv else "Beobachtungsmodus")
            self._save()
            if aktiv:
                self._force_boiler = True
                await self._apply_plans(run=True)
                for room in self.rooms:
                    r = self.rhythm.get(room.room_id)
                    if r and r.active and self.mode != MODE_URLAUB_WEG:
                        await self._set_room(room, room.rhythm_temp, "Rhythmus-Abwesenheit")
        await self.async_tick()

    async def async_set_param(self, key: str, value: float) -> None:
        self.params[key] = float(value)
        self._save()
        self.away_applied.clear()
        self._force_boiler = True
        await self.async_tick()

    # ------------------------------------------------------------------ Anwesenheit
    def _anyone_home(self) -> bool | None:
        """True/False oder None, wenn ein Personenstatus unbekannt ist."""
        if not self.persons:
            return True
        states = [self.hass.states.get(p) for p in self.persons]
        if any(s is None or s.state in _BAD for s in states):
            return None
        return any(s.state == "home" for s in states)

    @callback
    def _person_changed(self, _event: Event) -> None:
        home = self._anyone_home()
        if home is None:
            return
        if home:
            if self._away_timer:
                self._away_timer()
                self._away_timer = None
            if self.away:
                self.hass.async_create_task(self._heimkehr_locked())
        elif not self.away:
            self._start_away_timer()

    def _start_away_timer(self) -> None:
        if self._away_timer:
            return
        delay = self.params["abwesend_verzoegerung"] * 60
        self._away_timer = async_call_later(self.hass, delay, self._away_timer_fired)

    @callback
    def _away_timer_fired(self, _now: datetime) -> None:
        self._away_timer = None
        if self._anyone_home() is False and not self.away:
            self.hass.async_create_task(self._weg_locked())

    async def _weg_locked(self) -> None:
        async with self._lock:
            self.away = True
            self._note("Alle weg")
            self._save()
            if self.mode != MODE_URLAUB_WEG:
                await self._apply_plans(run=False)
        self._signal()

    async def _heimkehr_locked(self) -> None:
        async with self._lock:
            await self._heimkehr()
        self._signal()

    async def _heimkehr(self) -> None:
        self.away = False
        self.away_applied.clear()
        self._note("Jemand ist heimgekommen")
        self._save()
        if self.mode == MODE_URLAUB_WEG:
            return
        await self._apply_plans(run=True)
        await self._heimkehr_boost()

    async def _heimkehr_boost(self) -> None:
        now = dt_util.now()
        night = logic.in_window(now, logic.parse_time(NIGHT_START), logic.parse_time(NIGHT_END))
        if night:
            return
        await asyncio.sleep(HEIMKEHR_SETTLE_SECONDS)
        heim = self.params["heimkehr_temp"]
        for room in self.rooms:
            if not room.heimkehr:
                continue
            r = self.rhythm.get(room.room_id)
            if r and r.active:
                continue
            t = logic.capped(heim, room.max_temp)
            current = self._room_target(room)
            if current is None or current < t:
                await self._set_room(room, t, "Heimkehr", hvac=True)

    async def _apply_away_temps(self) -> None:
        if not self.away or self.mode == MODE_URLAUB_WEG:
            return
        now = dt_util.now()
        for room in self.rooms:
            r = self.rhythm.get(room.room_id)
            if r and r.active:
                continue
            t = self.params["abwesend_temp"]
            if room.exc_enabled and logic.away_exception_active(
                now, room.exc_start, room.exc_end, room.exc_end_fri
            ):
                t = room.exc_temp
            t = logic.capped(t, room.max_temp)
            if self.away_applied.get(room.room_id) != t:
                self.away_applied[room.room_id] = t
                await self._set_room(room, t, "Abwesenheit", hvac=True)

    # ------------------------------------------------------------------ Rhythmus
    def rhythm_init(self, room: RoomConfig, r: RhythmState, now: datetime) -> None:
        r.von = logic.next_rhythm_start(now, room.rhythm_weekday, room.rhythm_start)
        r.bis = r.von + timedelta(hours=room.rhythm_hours)

    async def _process_rhythm(self, now: datetime) -> None:
        for room in self.rooms:
            r = self.rhythm.get(room.room_id)
            if r is None or not room.rhythm:
                continue
            if not r.enabled:
                if r.active:
                    await self._rhythm_end(room, r)
                continue
            if r.von is None or r.bis is None:
                self.rhythm_init(room, r, now)
                self._save()
            if now >= r.bis:
                if r.active:
                    await self._rhythm_end(room, r)
                r.von, r.bis = logic.advance_period(r.von, r.bis, now, room.rhythm_days)
                self._note(f"{room.name}: nächste Abwesenheit {r.von:%d.%m. %H:%M}")
                self._save()
            elif r.von <= now and not r.active:
                r.plan_target = self._room_target(room)
                r.active = True
                self._save()
                self._note(f"{room.name}: Abwesenheit beginnt")
                if self.mode != MODE_URLAUB_WEG:
                    await self._set_room(room, room.rhythm_temp, "Rhythmus-Abwesenheit")

    async def _rhythm_end(self, room: RoomConfig, r: RhythmState) -> None:
        r.active = False
        self._save()
        self._note(f"{room.name}: Abwesenheit endet")
        if self.mode == MODE_URLAUB_WEG:
            return
        if self.away:
            self.away_applied.pop(room.room_id, None)
            return  # _apply_away_temps setzt im selben Durchlauf
        if r.plan_target is not None:
            await self._set_room(room, r.plan_target, "Plan wiederhergestellt")

    async def async_set_rhythm_enabled(self, room_id: str, enabled: bool) -> None:
        room, r = self.room(room_id), self.rhythm.get(room_id)
        if room is None or r is None:
            return
        r.enabled = enabled
        now = dt_util.now()
        if enabled and (r.von is None or r.bis is None or r.bis <= now):
            self.rhythm_init(room, r, now)
        self._save()
        await self.async_tick()

    async def async_set_rhythm_time(self, room_id: str, which: str, value: datetime) -> None:
        room, r = self.room(room_id), self.rhythm.get(room_id)
        if room is None or r is None:
            return
        value = dt_util.as_local(value)
        if which == "von":
            r.von = value
            if r.bis is None or r.bis <= value:
                r.bis = value + timedelta(hours=room.rhythm_hours)
        else:
            r.bis = value
        self._save()
        await self.async_tick()

    # ------------------------------------------------------------------ Wächter
    def _forced_target(self, room: RoomConfig) -> float | None:
        r = self.rhythm.get(room.room_id)
        if r and r.active and self.mode != MODE_URLAUB_WEG:
            return room.rhythm_temp
        return None

    @callback
    def _climate_changed(self, event: Event) -> None:
        new, old = event.data.get("new_state"), event.data.get("old_state")
        if new is None:
            return
        room = next((r for r in self.rooms if r.climate == new.entity_id), None)
        if room is None:
            return
        t_new = _float(new.attributes.get("temperature"))
        t_old = _float(old.attributes.get("temperature")) if old else None
        if t_new is None or t_new == t_old:
            return
        forced = self._forced_target(room)
        target = None
        if forced is not None and abs(t_new - forced) >= 0.1:
            self.rhythm[room.room_id].plan_target = t_new  # vom Plan gewünscht -> merken
            self._save()
            target = forced
        elif forced is None and room.max_temp is not None and t_new > room.max_temp + 0.01:
            target = room.max_temp
        if target is None:
            return
        if (t := self._guard_timers.pop(room.room_id, None)) is not None:
            t()

        @callback
        def _fire(_now: datetime, room=room, target=target) -> None:
            self._guard_timers.pop(room.room_id, None)
            self.hass.async_create_task(self._guard_set(room, target))

        self._guard_timers[room.room_id] = async_call_later(self.hass, GUARD_DELAY_SECONDS, _fire)

    async def _guard_set(self, room: RoomConfig, target: float) -> None:
        async with self._lock:
            current = self._room_target(room)
            if current is not None and abs(current - target) < 0.1:
                return
            await self._set_room(room, target, "Wächter")
        self._signal()

    async def _set_room(self, room: RoomConfig, temp: float, why: str, hvac: bool = False) -> None:
        if not room.climate:
            return  # Handthermostat
        data: dict[str, Any] = {"entity_id": room.climate, "temperature": temp}
        if hvac:
            data["hvac_mode"] = "heat"
        await self._call("climate", "set_temperature", data, f"{room.name} → {temp:.1f} °C ({why})")

    # ------------------------------------------------------------------ Fenster
    @callback
    def _window_changed(self, event: Event) -> None:
        new, old = event.data.get("new_state"), event.data.get("old_state")
        if new is None or old is None:
            return
        room = next((r for r in self.rooms if r.window_sensor == new.entity_id), None)
        if room is None:
            return
        if old.state == STATE_ON and new.state != STATE_ON:
            self.window_closed_at[room.room_id] = dt_util.utcnow()
        if new.state == STATE_ON or old.state == STATE_ON:
            self._force_boiler = True

    async def _check_reminders(self) -> None:
        services = list(self.conf.get(CONF_NOTIFY) or [])
        if not services:
            return
        now = dt_util.utcnow()
        for room in self.rooms:
            if not room.remind or not room.window_sensor:
                continue
            w = self.hass.states.get(room.window_sensor)
            if w is None or w.state != STATE_ON:
                continue
            open_min = (now - w.last_changed).total_seconds() / 60
            if open_min < room.remind_minutes:
                continue
            humidity = None
            if room.humidity_sensor:
                h = self.hass.states.get(room.humidity_sensor)
                humidity = _float(h.state) if h else None
                if humidity is None or humidity >= room.remind_humidity:
                    continue
            last = self.last_reminder.get(room.room_id)
            if last and (now - last).total_seconds() < REMINDER_REPEAT_SECONDS:
                continue
            self.last_reminder[room.room_id] = now
            temp = self._room_current(room)
            parts = [f"Seit {open_min:.0f} min offen."]
            if humidity is not None:
                parts.append(f"Luftfeuchte {humidity:.0f} %")
            if temp is not None:
                parts.append(f"Raum {temp:.1f} °C")
            message = " ".join(parts)
            for svc in services:
                domain, _, name = svc.partition(".")
                await self._call(
                    domain or "notify",
                    name or svc,
                    {
                        "title": f"🪟 {room.name}: Fenster schließen",
                        "message": message,
                        "data": {"group": "heizung", "tag": f"fenster_{room.room_id}"},
                    },
                    f"Erinnerung {room.name} an {svc}",
                )

    # ------------------------------------------------------------------ Lernmodell
    def _num_state(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        s = self.hass.states.get(entity_id)
        return _float(s.state) if s is not None and s.state not in _BAD else None

    def _boiler_on(self) -> bool:
        s = self.hass.states.get(self.boiler)
        if s is not None and s.attributes.get("hvac_action") is not None:
            return s.attributes.get("hvac_action") == "heating"
        return self.heizt

    def _room_u(self, room: RoomConfig) -> float | None:
        vals = [v for v in (self._num_state(x) for x in room.valve_sensors) if v is not None]
        if vals:
            return max(0.0, min(1.0, sum(vals) / len(vals) / 100.0))
        if room.valve_sensors:
            return None
        c = self.hass.states.get(room.climate) if room.climate else None
        if c is None or c.state in _BAD:
            return None
        return 1.0 if c.attributes.get("hvac_action") == "heating" else 0.0

    def _window_blocked(self, room: RoomConfig) -> bool:
        if not room.window_sensor:
            return False
        w = self.hass.states.get(room.window_sensor)
        if w is not None and w.state == STATE_ON:
            return True
        closed = self.window_closed_at.get(room.room_id)
        return closed is not None and (dt_util.utcnow() - closed).total_seconds() < self.params["lueften_nachlauf"] * 60

    def _learn_step(self) -> None:
        """Einmal pro Minute messen, alle 10 Minuten ein 30-Minuten-Fenster lernen."""
        if not self.learners:
            return
        now = dt_util.utcnow()
        if self._learn_last_sample and (now - self._learn_last_sample).total_seconds() < 55:
            self._update_learn_snapshot()
            return
        self._learn_last_sample = now
        tout = self._num_state(self.conf.get(CONF_OUTDOOR))
        vl = self._num_state(self.conf.get(CONF_FLOW_SENSOR))
        boiler_on = self._boiler_on()
        self._learn_count += 1
        learn_now = self._learn_count % learn.STEP_MIN == 0
        changed = False
        for room in self.rooms:
            lr = self.learners.get(room.room_id)
            if lr is None:
                continue
            buf = self._learn_buf.setdefault(room.room_id, deque(maxlen=learn.WINDOW_MIN + 1))
            buf.append(
                learn.Sample(
                    tin=self._room_current(room),
                    tout=tout,
                    u=self._room_u(room),
                    vl=vl,
                    boiler_on=boiler_on,
                    window_open=self._window_blocked(room),
                )
            )
            lr.note_vl(vl, boiler_on)
            if learn_now and len(buf) == buf.maxlen:
                f = learn.window_features(list(buf))
                if f is not None:
                    lr.update(*f)
                    changed = True
        if changed:
            self._save()
        self._update_learn_snapshot()

    def _update_learn_snapshot(self) -> None:
        tout = self._num_state(self.conf.get(CONF_OUTDOOR))
        vl_id = self.conf.get(CONF_FLOW_SENSOR)
        vl_now = self._num_state(vl_id) if self._boiler_on() else None
        out: dict[str, dict[str, Any]] = {}
        for room in self.rooms:
            lr = self.learners.get(room.room_id)
            if lr is None:
                continue
            tin = self.snapshot.room_currents.get(room.room_id)
            target = self.snapshot.room_targets.get(room.room_id)
            info: dict[str, Any] = {
                "lernstand": lr.progress,
                "zuverlaessig": lr.reliable,
                "fenster_gelernt": lr.n,
                "waermeverlust_1_h": round(lr.a, 4),
                "zeitkonstante_h": round(1 / lr.a, 1) if lr.a > 0 else None,
                "heizwirkung_1_h": round(lr.b, 4),
                "sonstige_gewinne_k_h": round(lr.c, 2),
                "modellfehler_k_h": round(lr.rmse, 2),
                "vorlauf_beim_heizen": round(lr.vl_heat, 1),
                "cool": None,
                "heat": None,
                "eta": None,
            }
            if tin is not None and tout is not None:
                has_vl = bool(vl_id)
                info["cool"] = round(lr.cool_rate(tin, tout), 2)
                info["heat"] = round(lr.heat_rate(tin, tout, vl_now, has_vl), 2)
                if target is not None:
                    eta = lr.minutes_to_target(tin, target, tout, vl_now, has_vl)
                    info["eta"] = None if eta is None else round(eta)
                    info["ziel_erreichbar"] = eta is not None
            out[room.room_id] = info
        self.snapshot.learn = out

    async def _learn_bootstrap(self) -> None:
        """Modelle einmalig aus dem Verlauf der letzten Tage anlernen."""
        try:
            from homeassistant.components.recorder import get_instance, history
        except ImportError:
            return
        try:
            instance = get_instance(self.hass)
        except KeyError:
            self._note("Lernmodell: Recorder nicht verfügbar, lerne ab jetzt")
            return
        end = dt_util.utcnow()
        start = end - timedelta(days=LEARN_HISTORY_DAYS)
        ids: set[str] = {self.boiler}
        for k in (CONF_OUTDOOR, CONF_FLOW_SENSOR):
            if self.conf.get(k):
                ids.add(self.conf[k])
        for room in self.rooms:
            if room.room_id not in self.learners:
                continue
            ids.update(x for x in (room.temperature_sensor, room.climate, room.window_sensor) if x)
            ids.update(room.valve_sensors)
        try:
            states = await instance.async_add_executor_job(
                history.get_significant_states, self.hass, start, end, sorted(ids), None, True, False, False, False
            )
        except Exception as err:  # noqa: BLE001
            self._note(f"Lernmodell: Verlauf nicht lesbar ({err})")
            return
        nachlauf = int(self.params["lueften_nachlauf"])
        series = learn_series_from_history(states, start, end)
        rooms = [r for r in self.rooms if r.room_id in self.learners]

        def _work() -> dict[str, int]:
            used: dict[str, int] = {}
            for room in rooms:
                samples = build_samples(
                    series, room, self.boiler, self.conf.get(CONF_OUTDOOR), self.conf.get(CONF_FLOW_SENSOR), nachlauf
                )
                fresh = learn.RoomLearner()
                used[room.room_id] = fresh.learn_series(samples)
                if used[room.room_id]:
                    self.learners[room.room_id] = fresh
            return used

        used = await self.hass.async_add_executor_job(_work)
        async with self._lock:
            self.learn_bootstrapped = True
            self._save()
            self._update_learn_snapshot()
        self._note(
            "Lernmodell aus 7 Tagen Verlauf: "
            + ", ".join(f"{r.name} {used.get(r.room_id, 0)}" for r in rooms)
            + " Fenster"
        )
        self._signal()

    async def async_relearn(self) -> None:
        """Modelle verwerfen und neu aus dem Verlauf lernen."""
        for k in list(self.learners):
            self.learners[k] = learn.RoomLearner()
        self.learn_bootstrapped = False
        self._save()
        await self._learn_bootstrap()

    # ------------------------------------------------------------------ Handthermostate
    def manual_level(self, room: RoomConfig) -> str:
        level = self.manual_levels.get(room.room_id)
        return level if level in room.levels else room.levels[0]

    async def async_set_manual_level(self, room_id: str, level: str) -> None:
        room = self.room(room_id)
        if room is None or level not in room.levels:
            return
        self.manual_levels[room_id] = level
        self._note(f"{room.name}: Handthermostat auf {level}")
        self._save()
        self._signal()

    # ------------------------------------------------------------------ Anzeige
    @property
    def status_text(self) -> str:
        if self.mode == MODE_URLAUB_WEG:
            return "Urlaub weg"
        return f"{MODE_LABELS[self.mode]} – {'alle weg' if self.away else 'zuhause'}"


# ---------------------------------------------------------------------- Verlauf -> Minutenreihen
def learn_series_from_history(states: dict[str, list], start: datetime, end: datetime) -> dict[str, Any]:
    """Zustände je Entität als (Minute, Zustand, Attribute)-Liste, vorwärts aufgefüllt."""
    minutes = int((end - start).total_seconds() // 60)
    out: dict[str, Any] = {"_minutes": minutes}
    for entity_id, rows in states.items():
        grid: list[tuple[str | None, dict]] = [(None, {})] * minutes
        events = []
        for st in rows:
            ts = getattr(st, "last_updated", None) or getattr(st, "last_changed", None)
            if ts is None:
                continue
            idx = int((ts - start).total_seconds() // 60)
            events.append((max(0, idx), st.state, dict(getattr(st, "attributes", {}) or {})))
        events.sort(key=lambda e: e[0])
        cur: tuple[str | None, dict] = (None, {})
        j = 0
        for m in range(minutes):
            while j < len(events) and events[j][0] <= m:
                cur = (events[j][1], events[j][2])
                j += 1
            grid[m] = cur
        out[entity_id] = grid
    return out


def build_samples(
    series: dict[str, Any], room: RoomConfig, boiler: str, outdoor: str | None, flow: str | None, nachlauf_min: int
) -> list[learn.Sample]:
    """Minutenreihe eines Raums aus den aufbereiteten Verläufen."""
    minutes = series["_minutes"]
    none_grid = [(None, {})] * minutes

    def num(grid, m):
        v = grid[m][0]
        return None if v in _BAD else _float(v)

    tin_g = series.get(room.temperature_sensor) if room.temperature_sensor else None
    cl_g = series.get(room.climate, none_grid) if room.climate else none_grid
    out_g = series.get(outdoor, none_grid) if outdoor else none_grid
    vl_g = series.get(flow) if flow else None
    b_g = series.get(boiler, none_grid)
    w_g = series.get(room.window_sensor) if room.window_sensor else None
    v_gs = [series.get(v, none_grid) for v in room.valve_sensors]
    samples: list[learn.Sample] = []
    last_open = -10**9
    for m in range(minutes):
        tin = num(tin_g, m) if tin_g is not None else None
        if tin is None:
            tin = _float(cl_g[m][1].get("current_temperature"))
        if v_gs:
            vals = [x for x in (num(g, m) for g in v_gs) if x is not None]
            u = max(0.0, min(1.0, sum(vals) / len(vals) / 100.0)) if vals else None
        else:
            st, at = cl_g[m]
            u = None if st in _BAD else (1.0 if at.get("hvac_action") == "heating" else 0.0)
        b_state, b_attr = b_g[m]
        boiler_on = b_attr.get("hvac_action") == "heating"
        if w_g is not None and w_g[m][0] == STATE_ON:
            last_open = m
        samples.append(
            learn.Sample(
                tin=tin,
                tout=num(out_g, m),
                u=u,
                vl=num(vl_g, m) if vl_g is not None else None,
                boiler_on=boiler_on,
                window_open=(m - last_open) <= nachlauf_min,
            )
        )
    return samples
