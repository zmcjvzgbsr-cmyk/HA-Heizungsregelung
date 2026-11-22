/* heizung-haus-card – Hausschnitt-Dashboard der Integration „Heizungsregelung“ */
const HHC_VERSION = '0.4.0';

const HHC_ICON = {
  flame: '<path d="M12 3c1 3 4 5 4 9a4 4 0 0 1-8 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-5 0-8z"/>',
  down: '<path d="M12 4v16"/><path d="M19 13l-7 7-7-7"/>',
  up: '<path d="M12 20V4"/><path d="M5 11l7-7 7 7"/>',
  check: '<path d="M4 12l5 5L20 6"/>',
  snow: '<path d="M12 2v20"/><path d="M3.5 7l17 10"/><path d="M20.5 7l-17 10"/><path d="M9 3.5l3 2 3-2"/><path d="M9 20.5l3-2 3 2"/>',
  window: '<rect x="4" y="3" width="16" height="18"/><path d="M12 3v18"/><path d="M4 12h16"/>',
};

function hhcSvg(name, size, sw) {
  return '<svg aria-hidden="true" width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="' + (sw || 2.4) + '" stroke-linecap="square" stroke-linejoin="round">' + HHC_ICON[name] + '</svg>';
}
function hhcEsc(v) {
  return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function hhcNum(v) { const n = parseFloat(v); return isNaN(n) ? null : n; }
function hhcFmt(v, d) {
  return v == null ? '–' : Number(v).toLocaleString('de-DE', { minimumFractionDigits: d, maximumFractionDigits: d });
}
function hhcTime(iso) {
  const d = new Date(iso);
  return isNaN(d) ? '--:--' : d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
}
// Nur Geändertes im DOM anpassen, statt alles neu aufzubauen (sonst springt die Seite beim Scrollen)
function hhcMorph(target, source) {
  const tNodes = Array.from(target.childNodes);
  const sNodes = Array.from(source.childNodes);
  for (let i = 0; i < sNodes.length; i++) {
    const s = sNodes[i];
    const t = tNodes[i];
    if (!t) { target.appendChild(s.cloneNode(true)); continue; }
    if (t.nodeType !== s.nodeType || t.nodeName !== s.nodeName) { target.replaceChild(s.cloneNode(true), t); continue; }
    if (t.nodeType !== 1) { if (t.nodeValue !== s.nodeValue) t.nodeValue = s.nodeValue; continue; }
    for (const a of Array.from(t.attributes)) if (!s.hasAttribute(a.name)) t.removeAttribute(a.name);
    for (const a of Array.from(s.attributes)) if (t.getAttribute(a.name) !== a.value) t.setAttribute(a.name, a.value);
    hhcMorph(t, s);
  }
  for (let i = tNodes.length - 1; i >= sNodes.length; i--) target.removeChild(tNodes[i]);
}

function hhcDay(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return '–';
  return d.toLocaleDateString('de-DE', { weekday: 'short' }).replace('.', '').toUpperCase() + ' ' +
    d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' });
}

(function loadFonts() {
  if (document.querySelector('link[data-hhc-fonts]')) return;
  const l = document.createElement('link');
  l.rel = 'stylesheet';
  l.dataset.hhcFonts = '1';
  l.href = 'https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=Rajdhani:wght@500;600;700&family=Share+Tech+Mono&display=swap';
  document.head.appendChild(l);
})();

class HeizungHausCard extends HTMLElement {
  static getStubConfig() {
    return { floors: [{ short: 'EG', name: 'Erdgeschoss', rooms: [] }] };
  }

  setConfig(config) {
    if (!config || !Array.isArray(config.floors)) throw new Error('floors fehlt (Liste der Geschosse mit Räumen)');
    this._config = Object.assign({ tolerance: 0.5, title: 'HAUS HEIZUNG' }, config);
    if (!this.shadowRoot) {
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.addEventListener('click', (e) => this._onClick(e));
    }
    this._sig = null;
    if (this._hass) this._render();
  }

  getCardSize() { return 24; }
  getGridOptions() { return { columns: 'full', rows: 'auto' }; }

  set hass(hass) {
    this._hass = hass;
    if (!this._meta && !this._loading && !this._err) this._load();
    const sig = this._watched().map((id) => { const s = hass.states[id]; return s ? s.last_updated : '-'; }).join('|') + '|' + new Date().getMinutes();
    if (sig === this._sig) return;
    this._sig = sig;
    this._render();
  }

  async _load() {
    this._loading = true;
    try {
      this._meta = await this._hass.callWS({ type: 'heizungsregelung/card_config' });
      this._err = null;
    } catch (e) {
      this._err = (e && e.message) || 'Integration nicht erreichbar';
      setTimeout(() => { this._err = null; this._sig = null; if (this._hass) this.hass = this._hass; }, 30000);
    }
    this._loading = false;
    this._sig = null;
    this._render();
  }

  // ---------------------------------------------------------------- Helfer
  _e(key) { return this._meta && this._meta.entities ? this._meta.entities[key] : undefined; }
  _s(id) { return id && this._hass ? this._hass.states[id] : undefined; }
  _st(id) { const s = this._s(id); return s ? s.state : undefined; }
  _n(id) { return hhcNum(this._st(id)); }
  _attr(id, a) { const s = this._s(id); return s ? s.attributes[a] : undefined; }

  _watched() {
    const ids = [];
    const m = this._meta;
    if (m) {
      Object.values(m.entities || {}).forEach((id) => ids.push(id));
      (m.rooms || []).forEach((r) => ['climate', 'temperature_sensor', 'window_sensor', 'humidity_sensor'].forEach((k) => r[k] && ids.push(r[k])));
      (m.persons || []).forEach((p) => ids.push(p));
      if (m.boiler) ids.push(m.boiler);
      if (m.outdoor_sensor) ids.push(m.outdoor_sensor);
    }
    const c = this._config || {};
    (c.floors || []).forEach((f) => (f.rooms || []).forEach((r) => {
      [].concat(r.valve || []).forEach((v) => ids.push(v));
      if (r.temperature) ids.push(r.temperature);
      if (r.climate) ids.push(r.climate);
    }));
    Object.values(c.basement || {}).forEach((v) => { if (typeof v === 'string' && v.indexOf('.') > 0) ids.push(v); });
    if (c.outdoor) ids.push(c.outdoor);
    return ids;
  }

  _moreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent('hass-more-info', { detail: { entityId }, bubbles: true, composed: true }));
  }

  _onClick(e) {
    const a = e.target.closest('[data-action]');
    if (a) { this._run(a.dataset.action, a.dataset.arg); return; }
    const m = e.target.closest('[data-more]');
    if (m) this._moreInfo(m.dataset.more);
  }

  _run(action, arg) {
    const h = this._hass;
    if (action === 'mode') {
      h.callService('select', 'select_option', { entity_id: this._e('betriebsart'), option: arg });
    } else if (action === 'toggle') {
      h.callService('switch', 'toggle', { entity_id: arg });
    } else if (action === 'level') {
      const i = arg.indexOf('|');
      h.callService('select', 'select_option', { entity_id: arg.slice(0, i), option: arg.slice(i + 1) });
    } else if (action === 'eingriffe') {
      const id = this._e('eingriffe_aktiv');
      const on = this._st(id) === 'on';
      const q = on
        ? 'Eingriffe ausschalten? Die Regelung rechnet dann nur noch mit und schaltet nichts.'
        : 'Eingriffe einschalten? Die Integration steuert dann Kessel, Pläne und Thermostate. Alte Automationen vorher deaktivieren.';
      if (confirm(q)) h.callService('switch', on ? 'turn_off' : 'turn_on', { entity_id: id });
    }
  }

  // ---------------------------------------------------------------- Räume
  _roomModel(cfg) {
    const m = this._meta || {};
    const tol = Number(this._config.tolerance);
    const r = cfg.room ? (m.rooms || []).find((x) => x.room_id === cfg.room) : null;
    const climate = cfg.climate || (r && r.climate);
    const tempId = cfg.temperature || (r && r.temperature_sensor);
    const name = (cfg.name || (r && r.name) || cfg.room || '?').toUpperCase();
    let ist = this._n(tempId);
    if (ist == null && climate) ist = hhcNum(this._attr(climate, 'current_temperature'));
    const cst = this._s(climate);
    const off = cst && cst.state === 'off';
    const soll = cst && !off ? hhcNum(cst.attributes.temperature) : null;
    const hasTrv = !!cst;
    const heating = cst && cst.attributes.hvac_action === 'heating';
    const valveIds = cfg.valve ? [].concat(cfg.valve) : ((r && r.valve_sensors) || []);
    const valves = valveIds.map((v) => this._n(v)).filter((v) => v != null);
    const valve = valves.length ? Math.max.apply(null, valves) : null;

    const out = {
      name, ist, soll, hasTrv, off, heating, valve, grow: cfg.grow || 1, more: climate || tempId,
      cls: '', state: '', stateTxt: '', notes: [],
    };
    if (hasTrv && !off && ist != null && soll != null) {
      const d = ist - soll;
      if (d < -tol) { out.cls = 'cold'; out.state = 'down'; out.stateTxt = hhcFmt(d, 1).replace('-', '−') + ' K'; }
      else if (d > tol) { out.cls = 'warm'; out.state = 'up'; out.stateTxt = '+' + hhcFmt(d, 1) + ' K'; }
      else { out.state = 'check'; out.stateTxt = 'PASST'; }
    }
    if (off) { out.stateTxt = 'AUS'; }
    if (!hasTrv) out.cls = 'none';

    if (r) {
      const away = this._st(this._e(r.room_id + '_gerade_abwesend')) === 'on';
      if (away) {
        out.cls = 'away';
        out.notes.push({ c: 'mag', t: 'WEG BIS ' + hhcTime(this._st(this._e(r.room_id + '_abwesend_bis'))) });
      }
      if (r.window_sensor && this._st(r.window_sensor) === 'on') out.notes.push({ c: 'warn', t: 'FENSTER OFFEN', icon: 'window' });
      if (r.humidity_sensor) {
        const hum = this._n(r.humidity_sensor);
        if (hum != null) out.notes.push({ c: '', t: 'FEUCHTE ' + hhcFmt(hum, 0) + ' %' });
      }
      if (r.thermostat_type === 'manual') {
        const id = this._e(r.room_id + '_stufe');
        out.manual = { id, levels: r.levels || [], cur: this._st(id) };
        out.more = tempId || id;
        if (r.radiators) out.notes.push({ c: '', t: String(r.radiators).toUpperCase() });
      }
      const heatId = this._e(r.room_id + '_aufheizrate');
      if (heatId && !away && !off) {
        const hs = this._s(heatId);
        const lern = hs ? hs.attributes.lernstand : null;
        if (!hs || hs.state === 'unknown' || hs.state === 'unavailable') {
          if (lern != null) out.notes.push({ c: '', t: 'MODELL LERNT · ' + hhcFmt(lern, 0) + ' %' });
        } else if (out.cls === 'cold') {
          const eta = this._st(this._e(r.room_id + '_zeit_bis_ziel'));
          const reach = this._attr(this._e(r.room_id + '_zeit_bis_ziel'), 'ziel_erreichbar');
          out.notes.push(reach === false
            ? { c: 'warn', t: 'ZIEL BEI VOLLER LEISTUNG NICHT ERREICHBAR' }
            : { c: 'cy', t: '↗ ' + hhcFmt(hhcNum(hs.state), 1) + ' K/H · ZIEL IN ' + hhcFmt(hhcNum(eta), 0) + ' MIN' });
        } else {
          const cool = this._n(this._e(r.room_id + '_auskuehlrate'));
          if (cool != null) out.notes.push({ c: '', t: '↘ AUSKÜHLUNG ' + hhcFmt(cool, 1) + ' K/H' });
        }
      }
      const lead = this._attr(this._e('heizbedarf'), 'fuehrender_raum');
      const bedarf = this._n(this._e('heizbedarf'));
      if (!away && lead && lead === r.name && bedarf != null && bedarf > 0) out.notes.push({ c: 'ora', t: 'BESTIMMT DEN BEDARF' });
    }
    if (cfg.note) out.notes.push({ c: '', t: String(cfg.note).toUpperCase() });
    return out;
  }

  _roomHtml(r) {
    let segs = '';
    const on = r.valve == null ? 0 : Math.round(r.valve / 10);
    for (let i = 0; i < 10; i++) segs += '<i class="' + (i < on ? 'f' : '') + '"></i>';
    return '<div class="room ' + r.cls + '" style="--g:' + Number(r.grow) + '" data-more="' + hhcEsc(r.more || '') + '" role="button" tabindex="0" aria-label="' + hhcEsc(r.name) + '">' +
      '<div class="rh"><span class="rn">' + hhcEsc(r.name) + '</span>' + (r.heating ? '<span class="fl" title="heizt">' + hhcSvg('flame', 16, 2.2) + '</span>' : '') + '</div>' +
      (r.ist != null ? '<div class="rt"><b>' + hhcFmt(r.ist, 1) + '</b><small>°C</small></div>' : '') +
      (r.hasTrv
        ? '<div class="rs"><span class="mut">SOLL ' + (r.soll != null ? hhcFmt(r.soll, 1) : '–') + '</span><span class="st">' + (r.state ? hhcSvg(r.state, 13, 3) : '') + hhcEsc(r.stateTxt) + '</span></div>' +
          (r.valve != null ? '<div class="vs">' + segs + '</div><div class="vl"><span>VENTIL</span><span>' + hhcFmt(r.valve, 0) + ' %</span></div>' : '')
        : '') +
      (r.manual && r.manual.id
        ? '<div class="lv" role="group" aria-label="Thermostat-Stufe ' + hhcEsc(r.name) + '">' + r.manual.levels.map((l) => {
            const sel = l === r.manual.cur;
            const kind = l === '0' ? 'z' : (l === '❄' || l === '*') ? 'c' : 'o';
            const lbl = (l === '❄' || l === '*') ? 'Frostschutz' : 'Stufe ' + l;
            return '<button class="' + (sel ? 'sel ' + kind : '') + '" aria-pressed="' + sel + '" aria-label="' + hhcEsc(lbl) + '" data-action="level" data-arg="' + hhcEsc(r.manual.id + '|' + l) + '">' +
              ((l === '❄' || l === '*') ? hhcSvg('snow', 14, 2) : hhcEsc(l)) + '</button>';
          }).join('') + '</div><div class="vl"><span>STUFE</span><span>' +
          (r.manual.cur === '❄' || r.manual.cur === '*' ? 'FROSTSCHUTZ' : r.manual.cur === '0' ? 'AUS' : hhcEsc(r.manual.cur || '–')) + '</span></div>'
        : '') +
      r.notes.map((n) => '<span class="note ' + n.c + '">' + (n.icon ? hhcSvg(n.icon, 11, 2) : '') + hhcEsc(n.t) + '</span>').join('') +
      '</div>';
  }

  // ---------------------------------------------------------------- Abschnitte
  _head(no, title) {
    return '<div class="h"><span class="no">' + no + '//</span><h2>' + hhcEsc(title) + '</h2><span class="ln"></span></div>';
  }

  _keller() {
    const b = this._config.basement || {};
    const m = this._meta || {};
    const boiler = b.boiler || m.boiler;
    const bs = this._s(boiler);
    const heating = bs && bs.attributes.hvac_action === 'heating';
    const vl = this._n(b.flow), rl = this._n(b.return);
    const dhw = this._n(b.dhw);
    let tank = '';
    const lvl = dhw == null ? 0 : Math.max(0, Math.min(8, Math.round((dhw - 20) / 5)));
    for (let i = 0; i < 8; i++) tank += '<i class="' + (i < lvl ? 'f' : '') + '"></i>';

    const kwh = this._n(b.gas_today_kwh), m3 = this._n(b.gas_today_m3);
    const factor = kwh != null && m3 ? kwh / m3 : (b.gas_kwh_per_m3 || null);
    const hz = this._n(b.gas_heating_m3), ww = this._n(b.gas_dhw_m3);
    const kwhY = this._n(b.gas_yesterday_kwh), m3Y = this._n(b.gas_yesterday_m3);
    const split = factor && (hz != null || ww != null)
      ? '<span class="sub">HZG ' + hhcFmt(hz != null ? hz * factor : null, 1) + ' · WW ' + hhcFmt(ww != null ? ww * factor : null, 1) + ' kWh</span>' : '';

    return '<div class="floor kg"><div class="fl-lbl"><span class="mag">' + hhcEsc(b.short || 'KG') + '//</span> ' + hhcEsc((b.name || 'Keller · unbeheizt').toUpperCase()) + '</div><div class="kgrid">' +
      '<div class="boiler cut16" data-more="' + hhcEsc(boiler || '') + '" role="button" tabindex="0">' +
        '<div class="bh"><span class="bn">' + hhcEsc((b.boiler_name || 'Kessel').toUpperCase()) + '</span>' +
        (heating ? '<span class="chipo">' + hhcSvg('flame', 13, 2.6) + 'HEIZT</span>' : '<span class="chipm">RUHE</span>') + '</div>' +
        '<div class="bm"><div><span class="lbl">KESSEL-SOLLWERT</span><div class="big o"><b>' + hhcFmt(bs ? bs.attributes.temperature : null, 1) + '</b><small>°C</small></div></div>' +
        '<div class="ra"><span class="lbl">RAUMFÜHLER</span><span class="mid">' + hhcFmt(bs ? bs.attributes.current_temperature : null, 1) + '<small> °C</small></span></div></div>' +
        '<div class="g4">' +
          '<div class="tl o" data-more="' + hhcEsc(b.flow || '') + '"><span>VORLAUF</span><b>' + hhcFmt(vl, 1) + ' °C</b></div>' +
          '<div class="tl c" data-more="' + hhcEsc(b.return || '') + '"><span>RÜCKLAUF</span><b>' + hhcFmt(rl, 1) + ' °C</b></div>' +
          '<div class="tl"><span>SPREIZUNG</span><b>' + hhcFmt(vl != null && rl != null ? vl - rl : null, 1) + ' K</b></div>' +
          '<div class="tl" data-more="' + hhcEsc(b.pressure || '') + '"><span>DRUCK</span><b>' + hhcFmt(this._n(b.pressure), 1) + ' bar</b></div>' +
        '</div></div>' +
      (b.dhw ? '<div class="pan cut12 dhw" data-more="' + hhcEsc(b.dhw) + '" role="button" tabindex="0"><div class="tank">' + tank + '</div><div class="col"><span class="lbl">WARMWASSER</span><span class="mid">' + hhcFmt(dhw, 1) + '<small> °C</small></span>' +
        (b.dhw_volume ? '<span class="sub">SPEICHER ' + hhcEsc(b.dhw_volume) + ' L</span>' : '') + '</div></div>' : '') +
      (b.gas_today_kwh || b.gas_today_m3 ? '<div class="pan cut12 col" data-more="' + hhcEsc(b.gas_today_kwh || b.gas_today_m3) + '" role="button" tabindex="0"><span class="lbl">GAS HEUTE</span>' +
        '<span class="mid">' + hhcFmt(kwh, 1) + '<small> kWh</small></span>' +
        '<span class="sub">' + hhcFmt(m3, 2) + ' m³</span>' + split +
        '<span class="sub">GESTERN ' + hhcFmt(kwhY, 1) + ' kWh · ' + hhcFmt(m3Y, 2) + ' m³</span></div>' : '') +
      '</div></div>';
  }

  _aside() {
    const m = this._meta || {};
    const modeId = this._e('betriebsart');
    const modeS = this._s(modeId);
    const modes = modeS && modeS.attributes.options ? modeS.attributes.options : [];
    const label = { 'Alltag': 'ALLTAG', 'Urlaub zuhause': 'URLAUB HEIM', 'Urlaub weg': 'URLAUB WEG' };

    const persons = (m.persons || []).map((p) => {
      const s = this._s(p);
      const home = s && s.state === 'home';
      const n = s ? (s.attributes.friendly_name || p) : p;
      return '<span class="person ' + (home ? 'home' : '') + '" data-more="' + hhcEsc(p) + '"><i></i>' + hhcEsc(String(n).toUpperCase()) + ' · ' + (home ? 'DA' : 'WEG') + '</span>';
    }).join('');

    const abw = this._n(this._e('param_abwesend_temp'));
    const verz = this._n(this._e('param_abwesend_verzoegerung'));
    const exc = (m.rooms || []).filter((r) => r.away_exception).map((r) =>
      hhcEsc(r.name.toUpperCase()) + ' ' + hhcFmt(r.away_exception_temperature, 1) + ' (' + String(r.away_exception_start || '').slice(0, 5) + '–' + String(r.away_exception_end || '').slice(0, 5) + ')');
    const awayLine = (m.persons || []).length
      ? '<span class="sub">ALLE WEG &gt; ' + hhcFmt(verz, 0) + ' MIN → ' + hhcFmt(abw, 1) + ' °C' + (exc.length ? ' · ' + exc.join(' · ') : '') + '</span>' : '';

    let no = 3;
    const rhythm = (m.rooms || []).filter((r) => r.rhythm).map((r) => {
      const sw = this._e(r.room_id + '_rhythmus');
      const enabled = this._st(sw) === 'on';
      const active = this._st(this._e(r.room_id + '_gerade_abwesend')) === 'on';
      const von = this._st(this._e(r.room_id + '_abwesend_von'));
      const bis = this._st(this._e(r.room_id + '_abwesend_bis'));
      const days = Number(r.rhythm_interval_days || 14);
      const title = days === 14 ? 'JEDES 2. WOCHENENDE' : 'ALLE ' + days + ' TAGE';
      const wd = ['MO', 'DI', 'MI', 'DO', 'FR', 'SA', 'SO'][Number(r.rhythm_weekday || 4)];
      const html = this._head(String(no).padStart(2, '0'), r.name.toUpperCase()) +
        '<div class="pan cut16 pink col">' +
          '<div class="row2"><div><b class="t">' + title + '</b><span class="sub">' + wd + ' ' + String(r.rhythm_start || '').slice(0, 5) + ' · ' + hhcFmt(r.rhythm_duration_hours, 0) + ' H · ' + hhcFmt(r.rhythm_temperature, 1) + ' °C</span></div>' +
          '<button class="sw ' + (enabled ? 'on' : '') + '" data-action="toggle" data-arg="' + hhcEsc(sw || '') + '" aria-pressed="' + enabled + '" aria-label="' + title + (enabled ? ' ausschalten' : ' einschalten') + '"><span></span></button></div>' +
          (active
            ? '<div class="row2 end"><div><span class="lbl">ZURÜCK UM</span><div class="big m"><b>' + hhcTime(bis) + '</b></div></div><span class="chipp">GERADE WEG</span></div>'
            : '<div class="row2 end"><div><span class="lbl">' + (enabled ? 'NÄCHSTES MAL' : 'AUSGESCHALTET') + '</span><div class="big m"><b>' + (enabled ? hhcDay(von) : '–') + '</b></div></div>' + (enabled ? '<span class="sub">' + hhcTime(von) + '</span>' : '') + '</div>') +
          (enabled ? '<div class="g2t"><div data-more="' + hhcEsc(this._e(r.room_id + '_abwesend_von') || '') + '"><span>VON</span><b>' + hhcDay(von) + ' ' + hhcTime(von) + '</b></div><div data-more="' + hhcEsc(this._e(r.room_id + '_abwesend_bis') || '') + '"><span>BIS</span><b>' + hhcDay(bis) + ' ' + hhcTime(bis) + '</b></div></div>' : '') +
        '</div>';
      no += 1;
      return '<section class="sec">' + html + '</section>';
    }).join('');

    const eId = this._e('eingriffe_aktiv');
    const eOn = this._st(eId) === 'on';
    const boiler = m.boiler;
    const now = boiler ? this._attr(boiler, 'temperature') : null;
    const calc = this._n(this._e('kessel_sollwert'));
    const regNo = String(no).padStart(2, '0');
    const logNo = String(no + 1).padStart(2, '0');

    const log = (this._attr(this._e('status'), 'letzte_aktionen') || []).slice(0, 5).map((l) => {
      const parts = String(l).split(' ');
      const t = parts.length > 2 ? parts[1] : '';
      const txt = (parts.length > 2 ? parts.slice(2).join(' ') : String(l)).replace(/(\d)\.(\d)/g, '$1,$2');
      return '<li><span class="mag">' + hhcEsc(t) + '</span> ' + hhcEsc(txt.toUpperCase()) + '</li>';
    }).join('');

    return '<aside>' +
      '<section class="sec">' + this._head('02', 'BETRIEBSART') +
        '<div class="pan cut16 col"><div class="seg" role="group" aria-label="Betriebsart">' +
        modes.map((o) => '<button class="' + (modeS.state === o ? 'sel' : '') + '" aria-pressed="' + (modeS.state === o) + '" data-action="mode" data-arg="' + hhcEsc(o) + '">' + hhcEsc(label[o] || o.toUpperCase()) + '</button>').join('') +
        '</div>' + (persons ? '<span class="lbl">ANWESENHEIT</span><div class="g2p">' + persons + '</div>' + awayLine : '') + '</div></section>' +
      rhythm +
      '<section class="sec">' + this._head(regNo, 'REGELUNG') +
        '<div class="pan cut16 col"><div class="row2"><div><b class="t">EINGRIFFE AKTIV</b><span class="sub ' + (eOn ? 'cy' : 'yel') + '">' + (eOn ? 'REGELUNG STEUERT' : 'BEOBACHTUNG · SCHALTET NICHTS') + '</span></div>' +
        '<button class="sw ' + (eOn ? 'on cyan' : '') + '" data-action="eingriffe" aria-pressed="' + eOn + '" aria-label="Eingriffe ' + (eOn ? 'ausschalten' : 'einschalten') + '"><span></span></button></div>' +
        '<div class="g2t"><div data-more="' + hhcEsc(boiler || '') + '"><span>KESSEL JETZT</span><b class="o">' + hhcFmt(now, 1) + ' °C</b></div><div data-more="' + hhcEsc(this._e('kessel_sollwert') || '') + '"><span>' + (eOn ? 'BERECHNET' : 'NEU BERECHNET') + '</span><b>' + hhcFmt(calc, 1) + ' °C</b></div></div></div></section>' +
      (log ? '<section class="sec">' + this._head(logNo, 'LOG') + '<ul class="log">' + log + '</ul></section>' : '') +
      '</aside>';
  }

  // ---------------------------------------------------------------- Render
  _patch(html) {
    if (!this._root) {
      this.shadowRoot.innerHTML = '<style>' + HHC_CSS + '</style><div id="hhc-root"></div>';
      this._root = this.shadowRoot.getElementById('hhc-root');
      this._last = null;
    }
    if (html === this._last) return;
    this._last = html;
    const tpl = document.createElement('template');
    tpl.innerHTML = html;
    hhcMorph(this._root, tpl.content);
  }

  _render() {
    if (!this.shadowRoot || !this._hass || !this._config) return;
    const c = this._config;
    if (this._err && !this._meta) {
      this._patch('<div class="wrap"><div class="pan cut16 col"><b class="t">HEIZUNGSREGELUNG NICHT ERREICHBAR</b><span class="sub">' + hhcEsc(this._err) + '</span></div></div>');
      return;
    }
    if (!this._meta) {
      this._patch('<div class="wrap"><span class="lbl">// VERBINDE …</span></div>');
      return;
    }
    const m = this._meta;
    const status = this._st(this._e('status')) || '';
    const outdoor = this._n(c.outdoor || m.outdoor_sensor);
    const bedarf = this._n(this._e('heizbedarf'));
    const lead = this._attr(this._e('heizbedarf'), 'fuehrender_raum');
    const gas = this._n((c.basement || {}).gas_today_kwh);
    const now = new Date();
    const stamp = now.toLocaleDateString('de-DE', { weekday: 'short' }).replace('.', '').toUpperCase() + ' ' +
      now.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' }) + ' ' + hhcTime(now.toISOString());
    const words = String(c.title).split(' ');
    const title = hhcEsc(words[0]) + (words.length > 1 ? ' <span class="glow">' + hhcEsc(words.slice(1).join(' ')) + '</span>' : '');

    const floors = (c.floors || []).map((f) =>
      '<div class="floor"><div class="fl-lbl"><span class="mag">' + hhcEsc(f.short || '') + '//</span> ' + hhcEsc(String(f.name || '').toUpperCase()) + '</div>' +
      '<div class="rooms">' + (f.rooms || []).map((r) => this._roomHtml(this._roomModel(r))).join('') + '</div></div>'
    ).join('<div class="slab"></div>');

    this._patch('<div class="wrap"><div class="scan"></div><div class="inner">' +
      '<header><div class="top"><div><span class="lbl">// HEIZUNGS-LINK · ' + stamp + '</span><h1>' + title + '</h1></div>' +
      '<div class="chip cut9" data-more="' + hhcEsc(this._e('status') || '') + '"><i></i>' + hhcEsc(status.toUpperCase()) + '</div></div>' +
      '<div class="bar"></div><div class="pills">' +
      (outdoor != null ? '<span class="pill cut9" data-more="' + hhcEsc(c.outdoor || m.outdoor_sensor) + '">AUSSEN <em class="c">' + hhcFmt(outdoor, 1) + ' °C</em></span>' : '') +
      '<span class="pill cut9" data-more="' + hhcEsc(this._e('heizbedarf') || '') + '">BEDARF <em class="o">' + (bedarf != null && bedarf > 0 ? '+' : '') + hhcFmt(bedarf, 1) + ' K</em>' + (lead ? ' · ' + hhcEsc(lead.toUpperCase()) : '') + '</span>' +
      (gas != null ? '<span class="pill cut9" data-more="' + hhcEsc(c.basement.gas_today_kwh) + '">GAS HEUTE <em class="o">' + hhcFmt(gas, 1) + ' kWh</em></span>' : '') +
      '<span class="pill cut9 muted">SYNC ' + hhcTime(now.toISOString()) + '</span></div></header>' +

      '<div class="layout"><section class="house">' + this._head('01', 'HAUSSCHNITT') +
        '<div class="frame">' +
          '<div class="roof"><svg aria-hidden="true" width="100%" height="100%" viewBox="0 0 1000 100" preserveAspectRatio="none"><polygon points="2,99 500,3 998,99" fill="rgba(0,229,255,0.04)" stroke="#00E5FF" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>' +
          (c.roof_note ? '<span class="rnote">' + hhcEsc(String(c.roof_note).toUpperCase()) + '</span>' : '') + '</div>' +
          floors + '<div class="slab"></div><div class="earth"></div>' + this._keller() +
          '<div class="pipes" aria-hidden="true"><span class="po"></span><span class="pc"></span></div>' +
        '</div>' +
        '<div class="legend"><span class="c">' + hhcSvg('down', 13, 3) + 'ZU KALT</span><span>' + hhcSvg('check', 13, 3) + 'PASST ±' + hhcFmt(c.tolerance, 1) + ' K</span><span class="o">' + hhcSvg('up', 13, 3) + 'ZU WARM</span><span class="mag">MAGENTA · ABWESEND</span><span class="mut">GESTRICHELT · OHNE THERMOSTAT</span><span class="mut">LINIEN · VORLAUF / RÜCKLAUF</span></div>' +
      '</section>' + this._aside() + '</div></div></div>');
  }
}

const HHC_CSS = `
:host{display:block;font-family:Rajdhani,system-ui,sans-serif;color:#ECEAF7}
*{box-sizing:border-box}
button{font:inherit;color:inherit;cursor:pointer;margin:0;-webkit-tap-highlight-color:transparent}
button:focus-visible,[role=button]:focus-visible{outline:2px solid #00E5FF;outline-offset:2px}
[data-more]{cursor:pointer}
.wrap{position:relative;container-type:inline-size;padding:24px 16px 40px;background-color:#07060D;
 background-image:linear-gradient(rgba(0,229,255,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(0,229,255,.05) 1px,transparent 1px);background-size:26px 26px;min-height:100%}
.scan{position:absolute;inset:0;pointer-events:none;background-image:repeating-linear-gradient(0deg,rgba(255,255,255,.025) 0,rgba(255,255,255,.025) 1px,transparent 1px,transparent 3px)}
.inner{position:relative;max-width:1240px;margin:0 auto;display:flex;flex-direction:column;gap:22px}
.cut9{clip-path:polygon(0 0,calc(100% - 9px) 0,100% 9px,100% 100%,9px 100%,0 calc(100% - 9px))}
.cut12{clip-path:polygon(0 0,calc(100% - 12px) 0,100% 12px,100% 100%,12px 100%,0 calc(100% - 12px))}
.cut16{clip-path:polygon(0 0,calc(100% - 16px) 0,100% 16px,100% 100%,16px 100%,0 calc(100% - 16px))}
.lbl{font-family:"Share Tech Mono",monospace;font-size:12px;letter-spacing:3px;color:#A39FC2}
.sub{display:block;font-family:"Share Tech Mono",monospace;font-size:12px;line-height:1.4;color:#A39FC2}
.sub.yel{color:#FCEE0A}.sub.cy{color:#00E5FF}
.mag{color:#FF3DCB}.o{color:#FF9F1C}.c{color:#00E5FF}.mut{color:#A39FC2}
header{display:flex;flex-direction:column;gap:12px}
.top{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-start;gap:12px}
h1{margin:4px 0 0;font-family:Orbitron,sans-serif;font-weight:900;font-size:38px;letter-spacing:2px;line-height:1}
.glow{color:#FF9F1C;text-shadow:0 0 14px #FF9F1C}
.chip{display:flex;align-items:center;gap:8px;padding:9px 14px;border:1px solid #00E5FF;background:rgba(0,229,255,.1);color:#00E5FF;font-family:"Share Tech Mono",monospace;font-size:13px;letter-spacing:1px}
.chip i{width:8px;height:8px;background:#00E5FF;box-shadow:0 0 10px #00E5FF}
.bar{height:2px;width:62%;background:#FF9F1C;box-shadow:0 0 10px #FF9F1C}
.pills{display:flex;flex-wrap:wrap;gap:8px}
.pill{font-family:"Share Tech Mono",monospace;font-size:13px;padding:6px 10px;background:#110E1F;border:1px solid #2A2445}
.pill em{font-style:normal}.pill.muted{color:#A39FC2;cursor:default}
.layout{display:flex;flex-wrap:wrap;gap:22px;align-items:flex-start}
.house{flex:999 1 660px;min-width:0;display:flex;flex-direction:column;gap:12px}
aside{flex:1 1 320px;min-width:0;display:flex;flex-direction:column;gap:22px}
.h{display:flex;align-items:center;gap:10px}
.h .no{font-family:"Share Tech Mono",monospace;font-size:13px;color:#FF3DCB}
.h h2{margin:0;font-family:Orbitron,sans-serif;font-weight:700;font-size:17px;letter-spacing:2px}
.h .ln{flex:1;height:1px;background:#2A2445}
.frame{position:relative;display:flex;flex-direction:column}
.roof{position:relative;height:104px;margin:0 -10px}
.roof svg{display:block;filter:drop-shadow(0 0 6px #00E5FF)}
.rnote{position:absolute;left:0;right:0;bottom:12px;text-align:center;font-family:"Share Tech Mono",monospace;font-size:11px;letter-spacing:3px;color:#A39FC2}
.floor{background:rgba(17,14,31,.6);border-left:2px solid #00E5FF;border-right:2px solid #00E5FF;box-shadow:inset 6px 0 12px -8px #00E5FF,inset -6px 0 12px -8px #00E5FF;padding:12px 12px 14px 46px;display:flex;flex-direction:column;gap:10px}
.floor.kg{background:#0B0916;border-color:#5B5480;border-bottom:2px solid #5B5480;box-shadow:none}
.fl-lbl{font-family:"Share Tech Mono",monospace;font-size:12px;letter-spacing:3px;color:#A39FC2}
.slab{height:3px;background:#00E5FF;box-shadow:0 0 10px #00E5FF}
.earth{height:12px;margin:0 -10px;background-image:repeating-linear-gradient(135deg,#3A3460 0,#3A3460 2px,transparent 2px,transparent 9px)}
.pipes{position:absolute;left:18px;top:104px;bottom:2px;width:10px;display:flex;gap:4px;pointer-events:none}
.pipes span{width:3px;height:100%}
.po{background:#FF9F1C;box-shadow:0 0 8px #FF9F1C}.pc{background:#00E5FF;box-shadow:0 0 8px #00E5FF}
.rooms{display:flex;flex-wrap:wrap;gap:8px}
.room{flex:var(--g) 1 140px;min-height:168px;background:#110E1F;border:1px solid #2A2445;padding:12px 12px 14px;display:flex;flex-direction:column;gap:8px;
 clip-path:polygon(0 0,calc(100% - 12px) 0,100% 12px,100% 100%,12px 100%,0 calc(100% - 12px))}
.room.cold{background:rgba(0,229,255,.06);border-color:#00E5FF;box-shadow:inset 0 0 18px rgba(0,229,255,.16)}
.room.warm{background:rgba(255,159,28,.06);border-color:#FF9F1C;box-shadow:inset 0 0 18px rgba(255,159,28,.16)}
.room.away{background:rgba(255,61,203,.08);border-color:#FF3DCB;box-shadow:inset 0 0 18px rgba(255,61,203,.16)}
.room.none{background:rgba(17,14,31,.5);border:1px dashed #3A3460}
.rh{display:flex;justify-content:space-between;align-items:center;gap:6px}
.rn{font-family:Orbitron,sans-serif;font-weight:700;font-size:11px;letter-spacing:1.5px}
.fl{color:#FF9F1C;filter:drop-shadow(0 0 4px #FF9F1C);display:flex}
.rt{display:flex;align-items:baseline;gap:4px}
.rt b{font-family:Orbitron,sans-serif;font-weight:700;font-size:32px;line-height:1}
.rt small{font-size:15px;color:#A39FC2}
.room.cold .rt b{color:#00E5FF;text-shadow:0 0 12px #00E5FF}
.room.warm .rt b{color:#FF9F1C;text-shadow:0 0 12px #FF9F1C}
.room.none .rt b{color:#A39FC2}
.rs{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:6px;font-family:"Share Tech Mono",monospace;font-size:12px}
.st{display:flex;align-items:center;gap:3px}
.room.cold .st{color:#00E5FF}.room.warm .st{color:#FF9F1C}
.vs{display:flex;gap:2px}.vs i{flex:1;height:8px;background:#2A2445}
.vs i.f{background:#FF9F1C;box-shadow:0 0 6px #FF9F1C}
.lv{display:flex;gap:3px;margin-top:auto}
.lv button{flex:1 1 0;min-width:0;height:36px;padding:0;display:flex;align-items:center;justify-content:center;background:transparent;border:1px solid #2A2445;color:#A39FC2;font-family:Orbitron,sans-serif;font-weight:700;font-size:12px}
.lv button.sel.o{background:#FF9F1C;border-color:#FF9F1C;color:#07060D;box-shadow:0 0 8px #FF9F1C}
.lv button.sel.c{background:#00E5FF;border-color:#00E5FF;color:#07060D;box-shadow:0 0 8px #00E5FF}
.lv button.sel.z{background:#ECEAF7;border-color:#ECEAF7;color:#07060D}
.vl{display:flex;gap:6px;justify-content:space-between;font-family:"Share Tech Mono",monospace;font-size:11px;color:#A39FC2;margin-top:-4px}
.note{display:flex;align-items:center;gap:4px;font-family:"Share Tech Mono",monospace;font-size:11px;line-height:1.35;color:#A39FC2}
.note.cy{color:#00E5FF}.note.mag{color:#FF3DCB}.note.ora{color:#FF9F1C}.note.warn{color:#FCEE0A}
.kgrid{display:flex;flex-wrap:wrap;gap:8px}
.boiler{flex:2 1 300px;background:rgba(255,159,28,.06);border:1px solid #FF9F1C;box-shadow:inset 0 0 22px rgba(255,159,28,.18);padding:16px;display:flex;flex-direction:column;gap:14px}
.bh{display:flex;justify-content:space-between;align-items:center;gap:8px}
.bn{font-family:Orbitron,sans-serif;font-weight:700;font-size:13px;letter-spacing:1.5px}
.chipo{display:flex;align-items:center;gap:6px;padding:4px 10px;background:#FF9F1C;color:#07060D;font-family:Orbitron,sans-serif;font-weight:900;font-size:11px;letter-spacing:1px;box-shadow:0 0 12px #FF9F1C}
.chipm{padding:4px 10px;border:1px solid #5B5480;color:#A39FC2;font-family:Orbitron,sans-serif;font-weight:700;font-size:11px;letter-spacing:1px}
.chipp{padding:6px 10px;background:#FF3DCB;color:#07060D;font-family:Orbitron,sans-serif;font-weight:900;font-size:11px;letter-spacing:1px}
.bm{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:12px}
.big{display:flex;align-items:baseline;gap:4px}
.big b{font-family:Orbitron,sans-serif;font-weight:900;font-size:60px;line-height:.9}
.big small{font-family:Orbitron,sans-serif;font-weight:700;font-size:22px}
.big.o{color:#FF9F1C;text-shadow:0 0 14px #FF9F1C}
.big.m{color:#FF3DCB;text-shadow:0 0 12px #FF3DCB}.big.m b{font-size:40px;line-height:1}
.ra{display:flex;flex-direction:column;align-items:flex-end;gap:2px}
.mid{font-family:Orbitron,sans-serif;font-weight:700;font-size:28px;line-height:1}
.mid small{font-size:14px;color:#A39FC2}
.g4{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;font-family:"Share Tech Mono",monospace}
.tl{display:flex;flex-direction:column;gap:2px;padding-top:8px;border-top:1px solid #2A2445}
.tl span{font-size:11px;color:#A39FC2}.tl b{font-weight:400;font-size:17px}
.tl.o{border-top:2px solid #FF9F1C}.tl.o b{color:#FF9F1C}
.tl.c{border-top:2px solid #00E5FF}.tl.c b{color:#00E5FF}
.pan{background:#110E1F;border:1px solid #2A2445;padding:16px}
.kgrid .pan{flex:1 1 160px}
.col{display:flex;flex-direction:column;gap:6px}
aside .col{gap:14px}
.dhw{display:flex;gap:14px}
.tank{width:26px;display:flex;flex-direction:column-reverse;gap:3px}
.tank i{flex:1;min-height:6px;background:#2A2445}.tank i.f{background:#FF9F1C;box-shadow:0 0 6px #FF9F1C}
.sec{display:flex;flex-direction:column;gap:12px}
.seg{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}
.seg button{height:46px;background:transparent;border:1px solid #2A2445;color:#A39FC2;font-family:Orbitron,sans-serif;font-weight:700;font-size:10px;letter-spacing:1px}
.seg button.sel{background:#FCEE0A;border-color:#FCEE0A;color:#07060D;font-weight:900;font-size:11px}
.g2p{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}
.person{display:flex;align-items:center;gap:8px;padding:9px 10px;border:1px solid #2A2445;color:#A39FC2;font-family:"Share Tech Mono",monospace;font-size:13px}
.person i{width:8px;height:8px;background:#5B5480}
.person.home{border-color:#00E5FF;background:rgba(0,229,255,.08);color:#00E5FF}
.person.home i{background:#00E5FF;box-shadow:0 0 8px #00E5FF}
.pink{background:rgba(255,61,203,.08);border-color:#FF3DCB}
.row2{display:flex;justify-content:space-between;align-items:center;gap:12px}
.row2.end{align-items:flex-end}
.t{display:block;font-family:Orbitron,sans-serif;font-weight:700;font-size:13px;letter-spacing:1px}
.sw{width:60px;height:32px;position:relative;background:transparent;border:1px solid #5B5480;padding:0;flex:none}
.sw span{position:absolute;top:4px;left:4px;width:22px;height:22px;background:#5B5480;transition:left .15s}
.sw.on{border-color:#FF3DCB;background:rgba(255,61,203,.25);box-shadow:0 0 10px #FF3DCB}
.sw.on span{left:32px;background:#FF3DCB}
.sw.on.cyan{border-color:#00E5FF;background:rgba(0,229,255,.2);box-shadow:0 0 10px #00E5FF}
.sw.on.cyan span{background:#00E5FF}
.g2t{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;text-align:center;font-family:"Share Tech Mono",monospace}
.g2t div{display:flex;flex-direction:column;gap:2px;padding-top:8px;border-top:1px solid #2A2445}
.g2t span{font-size:11px;color:#A39FC2}.g2t b{font-weight:400;font-size:15px}
.log{margin:0;padding:0 0 0 12px;list-style:none;border-left:2px solid #2A2445;display:flex;flex-direction:column;gap:8px;font-family:"Share Tech Mono",monospace;font-size:12px;color:#A39FC2}
.legend{display:flex;flex-wrap:wrap;gap:16px;font-family:"Share Tech Mono",monospace;font-size:12px}
.legend span{display:flex;align-items:center;gap:5px}
@container (max-width: 600px){
 .wrap{padding:20px 12px 32px}
 h1{font-size:30px}
 .roof{height:64px;margin:0 -6px}.pipes{top:64px;left:9px;width:9px;gap:3px}
 .floor{padding:10px 8px 10px 26px;gap:8px}
 .rooms{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}
 .room{min-height:118px;padding:9px;gap:5px;clip-path:polygon(0 0,calc(100% - 9px) 0,100% 9px,100% 100%,9px 100%,0 calc(100% - 9px))}
 .rn{font-size:10px;letter-spacing:1px}
 .rt b{font-size:24px}.rt small{font-size:12px}
 .rs{font-size:11px}.vs i{height:6px}.vs+.vl{display:none}
 .lv button{height:32px;font-size:11px}
 .note{font-size:10px}
 .big b{font-size:42px}.big.m b{font-size:36px}
 .g4{grid-template-columns:repeat(2,minmax(0,1fr))}
 .kgrid .pan{flex:1 1 130px;padding:10px}
 .mid{font-size:20px}
 .seg button{font-size:9px}
 .legend{gap:10px;font-size:11px}
}
`;

customElements.define('heizung-haus-card', HeizungHausCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: 'heizung-haus-card', name: 'Heizung – Hausschnitt', description: 'Cockpit der Integration Heizungsregelung mit Hausschnitt, Kessel und Abwesenheiten' });
console.info('%c HEIZUNG-HAUS-CARD %c ' + HHC_VERSION, 'background:#FF9F1C;color:#07060D;font-weight:700', 'color:#FF9F1C');
