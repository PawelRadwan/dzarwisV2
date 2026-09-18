# -*- coding: utf-8 -*-
# odczyt falownika Growatt i licznika SDM630 (bramka Modbus 192.168.8.40), zapis minutowych średnich
# do SQLite i bilans dnia dla zakładki PV panelu WWW. Opis: docs/panel-www.md, rejestry: docs/mapa-io.md

import logging
import os
import sqlite3
import struct
import threading
import time

GATEWAY_IP = '192.168.8.40'
GATEWAY_PORT = 502
GROWATT_UID = 2
METER_UID = 3
POLL_INTERVAL = 5       # s, odczyt urządzeń
MAX_GAP = 30            # s, dłuższa przerwa między odczytami nie jest doliczana do energii
MODBUS_TIMEOUT = 2      # s
INVERTER_PHASE = 1      # falownik jednofazowy podłączony do L1 (sprawdzone: L1 oddaje tyle, ile produkuje)

STATUS_TEXT = {0: 'Oczekiwanie', 1: 'Praca', 3: 'Awaria'}

log = logging.getLogger('energia')


def _u32(regs, i):
    return (regs[i] << 16) | regs[i + 1]


def _f32(regs, i):
    return struct.unpack('>f', struct.pack('>HH', regs[i], regs[i + 1]))[0]


def decode_growatt(regs_3000, regs_3093, regs_3105):
    # regs_3000: rejestry wejściowe 3000-3059, regs_3093: temperatura, regs_3105: kody błędu i ostrzeżenia
    r = regs_3000
    status = r[0]
    return {
        'status': status,
        'status_text': STATUS_TEXT.get(status, 'Kod %d' % status),
        'strings': [
            {'w': round(_u32(r, 5) / 10, 1), 'v': round(r[3] / 10, 1), 'a': round(r[4] / 10, 1)},
            {'w': round(_u32(r, 9) / 10, 1), 'v': round(r[7] / 10, 1), 'a': round(r[8] / 10, 1)},
        ],
        'ac_w': round(_u32(r, 23) / 10, 1),
        'freq_hz': round(r[25] / 100, 2),
        'today_kwh': round(_u32(r, 49) / 10, 1),
        'total_kwh': round(_u32(r, 51) / 10, 1),
        'temp_c': round(regs_3093[0] / 10, 1),
        'fault': regs_3105[0],
        'warning': regs_3105[1],
    }


def decode_meter(regs_0, regs_52, regs_72):
    # SDM630: float32 big-endian; regs_0: rejestry 0-17, regs_52: moc łączna, regs_72: energia pobrana/oddana
    return {
        'voltages': [_f32(regs_0, i) for i in (0, 2, 4)],
        'currents': [_f32(regs_0, i) for i in (6, 8, 10)],
        'phase_w': [_f32(regs_0, i) for i in (12, 14, 16)],
        'grid_w': _f32(regs_52, 0),
        'import_kwh': _f32(regs_72, 0),
        'export_kwh': _f32(regs_72, 2),
    }


def _read(mb, uid, start, count):
    mb.unit_id = uid
    return mb.read_input_registers(start, count)


def read_growatt(mb):
    # None, gdy falownik nie odpowiada (w nocy normalne). Growatt przyjmuje maks. 64 rejestry na zapytanie.
    blocks = [_read(mb, GROWATT_UID, 3000, 60), _read(mb, GROWATT_UID, 3093, 1), _read(mb, GROWATT_UID, 3105, 2)]
    return None if None in blocks else decode_growatt(*blocks)


def read_meter(mb):
    # None, gdy licznik nie odpowiada. Bramka odrzuca duże bloki rejestrów licznika - małe zapytania.
    blocks = [_read(mb, METER_UID, 0, 18), _read(mb, METER_UID, 52, 2), _read(mb, METER_UID, 72, 4)]
    return None if None in blocks else decode_meter(*blocks)


def day_bounds(ts):
    # początek i koniec doby (czas lokalny Pi) zawierającej ts
    lt = time.localtime(ts)
    start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    end = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + 1, 0, 0, 0, 0, 0, -1))
    return int(start), int(end)


class EnergyStore:
    # minutowe próbki w SQLite; ts = początek minuty (epoch s)
    def __init__(self, path):
        if path != ':memory:':
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.execute('CREATE TABLE IF NOT EXISTS samples ('
                            'ts INTEGER PRIMARY KEY, pv_w REAL, grid_w REAL, home_w REAL, '
                            'pv_today_kwh REAL, pv_total_kwh REAL, import_kwh REAL, export_kwh REAL)')
            # energia zbilansowana (suma faz) w minucie [Wh] - dodane 2026-09-18, starsze wiersze mają NULL
            cols = {row[1] for row in self.db.execute('PRAGMA table_info(samples)')}
            for col in ('bal_import_wh', 'bal_export_wh'):
                if col not in cols:
                    self.db.execute('ALTER TABLE samples ADD COLUMN %s REAL' % col)
            self.db.commit()

    def add(self, ts, pv_w, grid_w, home_w, pv_today_kwh, pv_total_kwh, import_kwh, export_kwh,
            bal_import_wh=None, bal_export_wh=None):
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO samples (ts, pv_w, grid_w, home_w, pv_today_kwh, pv_total_kwh, '
                            'import_kwh, export_kwh, bal_import_wh, bal_export_wh) '
                            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (ts, pv_w, grid_w, home_w, pv_today_kwh, pv_total_kwh, import_kwh, export_kwh,
                             bal_import_wh, bal_export_wh))
            self.db.commit()

    def balanced_sum(self, start, end):
        # (pobór Wh, oddanie Wh) zbilansowane w przedziale
        row = self._query('SELECT COALESCE(SUM(bal_import_wh), 0), COALESCE(SUM(bal_export_wh), 0) FROM samples '
                          'WHERE ts >= ? AND ts < ?', (start, end))[0]
        return row[0], row[1]

    def month_rows(self):
        # tylko minuty z energią zbilansowaną - wszystkie wartości podsumowań za ten sam okres
        return self._query('SELECT ts, bal_import_wh, bal_export_wh, pv_total_kwh FROM samples '
                           'WHERE bal_import_wh IS NOT NULL ORDER BY ts', ())

    def _query(self, sql, args):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def day_points(self, start, end):
        return [list(row) for row in self._query(
            'SELECT ts, pv_w, home_w FROM samples WHERE ts >= ? AND ts < ? ORDER BY ts', (start, end))]

    def first_meter_sample(self, start, end):
        # (ts, import_kwh, export_kwh, pv_today_kwh) - początek okresu bilansu dnia
        # tylko minuty z energią zbilansowaną - produkcja w bilansie liczona od tej samej chwili co pobór/oddanie
        rows = self._query('SELECT ts, import_kwh, export_kwh, pv_today_kwh FROM samples WHERE ts >= ? AND ts < ? '
                           'AND bal_import_wh IS NOT NULL ORDER BY ts LIMIT 1', (start, end))
        return tuple(rows[0]) if rows else None

    def last_pv_today(self, start, end):
        rows = self._query('SELECT pv_today_kwh FROM samples WHERE ts >= ? AND ts < ? '
                           'AND pv_today_kwh IS NOT NULL ORDER BY ts DESC LIMIT 1', (start, end))
        return rows[0][0] if rows else None


def _mean(values):
    return round(sum(values) / len(values), 1) if values else None


class Collector:
    # co POLL_INTERVAL czyta falownik i licznik, trzyma ostatni stan i co minutę zapisuje średnie do bazy
    def __init__(self, mb, store, clock=time.time):
        self.mb = mb
        self.store = store
        self.clock = clock
        self.lock = threading.Lock()
        self.latest = None
        self._bucket = None         # bieżąca minuta: {'ts', 'pv', 'grid', 'home', 'last'}
        self._first = None          # (początek doby, ts, import_kwh, export_kwh, pv_today_kwh) - pierwszy odczyt w dobie
        self._pv_today = None       # (początek doby, kWh)
        self._inverter_ok = None
        self._last_meter_ts = None  # czas poprzedniego udanego odczytu licznika (do całkowania mocy)

    def _store_call(self, fn, *args):
        # błąd bazy nie może zatrzymać odczytów na żywo
        try:
            return fn(*args)
        except Exception as e:
            log.error('baza energii: %s: %s', type(e).__name__, e)
            return None

    def _flush(self):
        b = self._bucket
        last = b['last']
        self._store_call(self.store.add, b['ts'], _mean(b['pv']), _mean(b['grid']), _mean(b['home']),
                         last.get('pv_today_kwh'), last.get('pv_total_kwh'),
                         last.get('import_kwh'), last.get('export_kwh'),
                         round(b['imp_wh'], 3) if b['meter'] else None, round(b['exp_wh'], 3) if b['meter'] else None)

    def poll(self):
        now = self.clock()
        g = read_growatt(self.mb)
        m = read_meter(self.mb)
        day_start, day_end = day_bounds(now)

        if (g is not None) != self._inverter_ok:
            log.info('falownik: %s', 'odpowiada' if g else 'nie odpowiada')
            self._inverter_ok = g is not None

        pv_w = g['ac_w'] if g else 0.0
        grid_w = round(m['grid_w'], 1) if m else None
        home_w = round(pv_w + grid_w, 1) if m else None

        if g:
            self._pv_today = (day_start, g['today_kwh'])
        elif self._pv_today is None or self._pv_today[0] != day_start:
            stored = self._store_call(self.store.last_pv_today, day_start, day_end)
            self._pv_today = (day_start, stored or 0.0)
        pv_today = self._pv_today[1]

        # minutowe średnie; zapis poprzedniej minuty, gdy zaczyna się nowa
        minute = int(now // 60 * 60)
        if self._bucket and self._bucket['ts'] != minute:
            self._flush()
            self._bucket = None
        if self._bucket is None:
            self._bucket = {'ts': minute, 'pv': [], 'grid': [], 'home': [], 'last': {},
                            'imp_wh': 0.0, 'exp_wh': 0.0, 'meter': False}
        self._bucket['pv'].append(pv_w)
        # bilansowanie faz (jak licznik zakładu): moc łączna x czas od poprzedniego odczytu,
        # dodatnia -> pobór, ujemna -> oddanie; po przerwie > MAX_GAP nie doliczamy
        if m:
            dt = now - self._last_meter_ts if self._last_meter_ts is not None else 0
            if 0 < dt <= MAX_GAP:
                wh = m['grid_w'] * dt / 3600
                self._bucket['imp_wh' if wh > 0 else 'exp_wh'] += abs(wh)
            self._bucket['meter'] = True
        self._last_meter_ts = now if m else None
        if m:
            self._bucket['grid'].append(grid_w)
            self._bucket['home'].append(home_w)
            self._bucket['last'].update(import_kwh=m['import_kwh'], export_kwh=m['export_kwh'])
        if g:
            self._bucket['last'].update(pv_today_kwh=g['today_kwh'], pv_total_kwh=g['total_kwh'])

        if m and (self._first is None or self._first[0] != day_start):
            first = self._store_call(self.store.first_meter_sample, day_start, day_end)
            self._first = (day_start,) + (first if first else
                                          (int(now), m['import_kwh'], m['export_kwh'], g['today_kwh'] if g else None))

        # bilans liczony za ten sam okres dla wszystkich wartości: od pierwszego odczytu w dobie (since);
        # produkcja w bilansie = produkcja dziś minus produkcja dziś w chwili since (gdy zbieranie ruszyło w dzień)
        today = {'pv_kwh': pv_today, 'balance_pv_kwh': None, 'import_kwh': None, 'export_kwh': None,
                 'home_kwh': None, 'self_use_pct': None, 'since': None}
        if m:
            pv_base = self._first[4] or 0.0
            bal_pv = round(max(pv_today - pv_base, 0), 2)
            # pobór/oddanie dziś zbilansowane: zapisane minuty + bieżąca minuta
            stored = self._store_call(self.store.balanced_sum, day_start, day_end) or (0, 0)
            cur_imp = self._bucket['imp_wh'] if self._bucket['ts'] >= day_start else 0
            cur_exp = self._bucket['exp_wh'] if self._bucket['ts'] >= day_start else 0
            imp = round((stored[0] + cur_imp) / 1000, 3)
            exp = round((stored[1] + cur_exp) / 1000, 3)
            today.update(balance_pv_kwh=bal_pv, import_kwh=imp, export_kwh=exp,
                         home_kwh=round(max(bal_pv + imp - exp, 0), 2), since=self._first[1])
            if bal_pv > 0:
                today['self_use_pct'] = round(min(max((bal_pv - exp) / bal_pv * 100, 0), 100))

        # moc na fazach; dom na fazie falownika = sieć + produkcja
        phases = []
        if m:
            for i in range(3):
                grid = round(m['phase_w'][i], 1)
                on_inverter = i + 1 == INVERTER_PHASE
                phases.append({'name': 'L%d' % (i + 1), 'v': round(m['voltages'][i], 1),
                               'a': round(m['currents'][i], 2), 'grid_w': grid,
                               'home_w': round(grid + pv_w, 1) if on_inverter else grid,
                               'inverter': on_inverter})

        snapshot = {
            'updated': int(now),
            'meter_ok': m is not None,
            'inverter_ok': g is not None,
            'now': {'pv_w': pv_w, 'grid_w': grid_w, 'home_w': home_w},
            'today': today,
            'phases': phases,
            'strings': g['strings'] if g else [],
            'inverter': {k: g[k] for k in ('status', 'status_text', 'temp_c', 'freq_hz', 'fault', 'warning')} if g
            else {'status': None, 'status_text': 'Nie odpowiada', 'temp_c': None, 'freq_hz': None,
                  'fault': None, 'warning': None},
            'totals': {'pv_kwh': g['total_kwh'] if g else None,
                       'import_kwh': round(m['import_kwh'], 1) if m else None,
                       'export_kwh': round(m['export_kwh'], 1) if m else None},
        }
        with self.lock:
            self.latest = snapshot

    def snapshot(self):
        with self.lock:
            return self.latest

    def months(self):
        # podsumowanie miesięczne (od najnowszego) i łączne: pobór/oddanie zbilansowane, produkcja z licznika
        # falownika (różnica stanów), zużycie domu = produkcja + pobór - oddanie
        rows = self._store_call(self.store.month_rows) or []
        months = {}
        prev_total = None
        for ts, imp_wh, exp_wh, pv_total in rows:
            key = time.strftime('%Y-%m', time.localtime(ts))
            m = months.get(key)
            if m is None:
                m = months[key] = {'month': key, 'from_day': time.localtime(ts).tm_mday, 'imp_wh': 0.0,
                                   'exp_wh': 0.0, 'pv_start': prev_total, 'pv_end': None}
            m['imp_wh'] += imp_wh or 0
            m['exp_wh'] += exp_wh or 0
            if pv_total is not None:
                if m['pv_start'] is None:
                    m['pv_start'] = pv_total
                m['pv_end'] = pv_total
                prev_total = pv_total
        out = []
        for m in months.values():
            pv = round(m['pv_end'] - m['pv_start'], 1) if m['pv_end'] is not None else 0.0
            out.append(self._summary(m['imp_wh'] / 1000, m['exp_wh'] / 1000, pv,
                                     month=m['month'], from_day=m['from_day']))
        out.sort(key=lambda m: m['month'], reverse=True)
        totals = self._summary(sum(m['import_kwh'] for m in out), sum(m['export_kwh'] for m in out),
                               sum(m['pv_kwh'] for m in out))
        return {'since': rows[0][0] if rows else None, 'totals': totals, 'months': out}

    @staticmethod
    def _summary(imp, exp, pv, **extra):
        s = dict(extra, import_kwh=round(imp, 2), export_kwh=round(exp, 2), pv_kwh=round(pv, 1),
                 home_kwh=round(max(pv + imp - exp, 0), 2), self_use_pct=None)
        if pv > 0:
            s['self_use_pct'] = round(min(max((pv - exp) / pv * 100, 0), 100))
        return s

    def day(self):
        now = self.clock()
        start, end = day_bounds(now)
        points = self._store_call(self.store.day_points, start, end) or []
        return {'date': time.strftime('%Y-%m-%d', time.localtime(now)), 'points': points}

    def run(self):
        while True:
            try:
                self.poll()
            except Exception:
                log.exception('odczyt energii')
            time.sleep(POLL_INTERVAL)

    def start(self):
        threading.Thread(target=self.run, name='energia', daemon=True).start()
