# -*- coding: utf-8 -*-
# pompa ciepła (sterownik Quotek) przez narzędzie kotek_rpi: podgląd stanu, zmiana programu,
# same pompy obiegowe, ręczne grzanie. Opis: docs/panel-www.md, polecenia: docs/pompa-ciepla.md

import datetime
import json
import logging
import os
import re
import subprocess
import threading
import time
import xml.etree.ElementTree as ET

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KOTEK = os.path.join(REPO, 'kotek_rpi')
PUMP_IP = '192.168.1.31'
KOTEK_TIMEOUT = 20      # s
POLL_INTERVAL = 5       # s, status i temperatury
SLOW_INTERVAL = 60      # s, harmonogram, lista programów, ostatnie akcje
PROGRAM_CONFIRM = 20    # s, wlaczprogram działa z opóźnieniem

# kolejność i nazwy czujników na stronie (funkcje z konfiguracji sterownika)
SENSORS = [('zco', 'Zasilanie CO'), ('pco', 'Powrót CO'), ('zko', 'Zasilanie kolektora'),
           ('pko', 'Powrót kolektora'), ('par', 'Parownik')]

log = logging.getLogger('pompa')


class KotekError(Exception):
    pass


def kotek_args(args):
    return ['--adres', PUMP_IP] + list(args)


def check_output(out):
    # kotek przy braku łączności kończy się kodem 0, ale wypisuje ERROR(...)
    m = re.search(r'ERROR\([^)]*\)\s*(.*)', out)
    if m:
        raise KotekError(m.group(1).strip() or 'błąd kotek')
    return out


def run_kotek(args):
    try:
        p = subprocess.run([KOTEK] + kotek_args(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=KOTEK_TIMEOUT, universal_newlines=True, errors='replace')
    except (OSError, subprocess.TimeoutExpired) as e:
        raise KotekError('kotek: %s' % e)
    if p.returncode != 0:
        raise KotekError('kotek zakończył się kodem %d: %s' % (p.returncode, p.stdout.strip()[-200:]))
    return check_output(p.stdout)


def _hms(text):
    h, m, s = (int(x) for x in text.strip().split(':'))
    return h * 3600 + m * 60 + s


def parse_status(xml):
    root = ET.fromstring(xml)
    st = root.find('status')
    czas = st.find('czas')
    stan = st.find('stan')
    awaria = st.find('awaria')
    grz = st.find('grzanie')
    fault = awaria.get('opis').strip() if awaria is not None and stan.get('nazwa') == 'AWARIA' else None
    energy = {('razem' if e.get('taryfa') == 'obie' else e.get('taryfa')): int(e.get('impulsy')) / 1000
              for e in st.find('energia')}   # 1000 imp = 1 kWh
    wl = {e.get('typ'): e.get('stan') == '1' for e in st.find('grzaniewlwyl')}
    power = int(st.find('moc').get('wartosc'))             # -1 = brak impulsów licznika (pompa stoi), nie moc
    return {
        'clock': '%s %s' % (czas.get('data').split()[0], czas.get('godzina')),
        'state': stan.get('nazwa'),
        'state_text': stan.get('opis').strip(),
        'fault': fault,
        'heating_left_s': _hms(grz.find('czasPracy').get('doKonca')),
        'heating_elapsed_s': _hms(grz.find('czasPracy').get('odStartu')),
        'sensors': {c.get('id'): c.get('stan') == '1' for c in grz.find('czujniki')},
        'program': int(st.find('aktywnyProgram').get('nr')) + 1,         # w XML liczony od zera
        'pumps': {p.get('id'): p.get('stan') == '1' for p in st.find('pompy')},
        'tariff': st.find('taryfa').get('opis'),
        'energy_kwh': {k: round(v, 3) for k, v in energy.items()},
        'power_w': power if power >= 0 else None,
        'co_on': wl.get('co', False),
        'cwu_on': wl.get('cwu', False),
    }


def parse_sensors(xml):
    root = ET.fromstring(xml)
    by_func = {t.get('funkcja'): t for t in root.iter('temperaturaczujnik') if t.get('aktywny') == '1'}
    out = []
    for func, name in SENSORS:
        t = by_func.get(func)
        if t is not None:
            out.append({'funkcja': func, 'nazwa': name, 't': float(t.get('t')),
                        'tmin': float(t.get('tmin24')), 'tmax': float(t.get('tmax24'))})
    return out


def _hhmm_add(hhmm, minutes):
    t = datetime.datetime.strptime(hhmm, '%H:%M') + datetime.timedelta(minutes=minutes)
    return t.strftime('%H:%M')


def describe_action(line):
    # akcja z czytajprogram: (opis, start, koniec, codzienna, opis krótki); start/koniec 'GG:MM' albo None
    line = re.sub(r'\s+', ' ', line).strip()
    m = re.match(r'Grzanie (.+?) (\d\d:\d\d) pco= ?([\d.]+) zew=.*?czas= ?(-?\d+)min$', line)
    if m:
        dni, godz, pco, czas = m.group(1), m.group(2), m.group(3).replace('.', ','), int(m.group(4))
        daily = dni == 'codziennie'
        if czas < 0:            # czas ujemny: grzanie DO godziny akcji
            start, end = _hhmm_add(godz, czas), godz
        elif czas > 0:
            start, end = godz, _hhmm_add(godz, czas)
        else:
            short = 'grzanie od %s do temperatury, powrót CO %s °C' % (godz, pco)
            return '%s od %s grzanie do temperatury, powrót CO %s °C' % (dni, godz, pco), godz, None, daily, short
        short = 'grzanie %s–%s, powrót CO do %s °C' % (start, end, pco)
        return '%s %s–%s grzanie, powrót CO do %s °C' % (dni, start, end, pco), start, end, daily, short
    m = re.match(r'Pompy (.+?) (\d\d:\d\d) CZ\.KOL="(\d+)" CZ\.CO="(\d+)"$', line)
    if m:
        dni, godz, kol, co = m.groups()
        short = 'pompy: kolektor %s min, CO %s min' % (kol, co)
        return '%s %s %s' % (dni, godz, short), godz, _hhmm_add(godz, max(int(kol), int(co))), dni == 'codziennie', short
    return line, None, None, False, line


def parse_program(text):
    opis = re.search(r'^Opis \.+ (.*)$', text, re.M)
    items = []
    for nr, line in re.findall(r'^AK\. (\d+): (.*)$', text, re.M):
        desc, start, end, daily, short = describe_action(line)
        items.append({'nr': int(nr), 'text': desc, 'start': start, 'end': end, 'daily': daily, 'short': short})
    return {'opis': opis.group(1).strip() if opis else '', 'akcje': [i['text'] for i in items], 'items': items}


def _minutes(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def build_schedule(items, rows, program_nr, ctrl_now, diff_min):
    # stan zadań aktywnego programu dziś wg zegara sterownika: now / done / next / later / missed / unknown
    today = ctrl_now.strftime('%m/%d')
    cur = ctrl_now.hour * 60 + ctrl_now.minute + ctrl_now.second / 60
    today_rows = [r for r in rows if r[0] == today]
    earliest = min((_minutes(r[1]) for r in today_rows), default=None)
    done = {}
    for data, czas, prog, akcja in today_rows:            # od najnowszej - pierwsze trafienie = ostatnie wykonanie
        if prog == str(program_nr):
            done.setdefault(akcja, czas)
    out = []
    for it in items:
        e = dict(it, status='other', done_at=None, in_min=None, start_pi=None, tomorrow_in_min=None)
        if it['start'] and diff_min and abs(diff_min) > 5:
            e['start_pi'] = _hhmm_add(it['start'], -diff_min)
        if it['daily'] and it['start']:
            s = _minutes(it['start'])
            en = _minutes(it['end']) if it['end'] else None
            in_window = en is not None and en != s and ((s <= cur < en) if s < en else (cur >= s or cur < en))
            if in_window:
                e['status'] = 'now'
            elif str(it['nr']) in done and s <= cur:
                e['status'], e['done_at'] = 'done', done[str(it['nr'])]
            elif s <= cur:
                # "nie wykonano" tylko gdy ten program był dziś aktywny (coś wykonał) przed godziną zadania
                active_today = any(p == str(program_nr) and _minutes(c) <= cur for _, c, p, _a in today_rows)
                e['status'] = 'missed' if active_today and earliest is not None and earliest <= s else 'unknown'
            else:
                e['status'] = 'later'
                e['in_min'] = int(s - cur)
        out.append(e)
    later = [e for e in out if e['status'] == 'later']
    if later:
        min(later, key=lambda e: e['in_min'])['status'] = 'next'
    else:
        # dziś już nic - najbliższe zadanie jutro
        daily = [e for e in out if e['daily'] and e['start']]
        if daily:
            first = min(daily, key=lambda e: _minutes(e['start']))
            first['tomorrow_in_min'] = int(24 * 60 - cur + _minutes(first['start']))
    return out


def describe_actions(actions, defs, ctrl_now):
    # ostatnie akcje w zrozumiałej postaci: kiedy, co (z treści programu), który program
    today = ctrl_now.strftime('%m/%d') if ctrl_now else None
    yesterday = (ctrl_now - datetime.timedelta(days=1)).strftime('%m/%d') if ctrl_now else None
    out = []
    for a in actions:
        day = 'dziś' if a['data'] == today else 'wczoraj' if a['data'] == yesterday else \
            '%s.%s' % (a['data'][3:], a['data'][:2])
        prog = defs.get(a['program'])
        label = 'specjalny (S)' if a['program'] == 'S' else a['program']
        item = next((i for i in (prog or {}).get('items', []) if str(i['nr']) == a['akcja']), None)
        out.append({
            'kiedy': '%s %s' % (day, a['od'] if a['ile'] == 1 else '%s–%s' % (a['od'], a['do'])),
            'opis': item['short'] if item else 'zadanie nr %s — już usunięte z programu' % a['akcja'],
            'program': '%s · %s' % (label, prog['opis']) if prog else label,
            'ile': a['ile'],
        })
    return out


def activity(status):
    # co się teraz dzieje - jedno zdanie
    if status.get('fault'):
        return 'Awaria: %s' % status['fault']
    parts = []
    if status.get('heating_left_s'):
        parts.append('grzanie')
    co, kol = status['pumps'].get('co'), status['pumps'].get('kol')
    if co and kol:
        parts.append('pracują pompy CO i kolektora')
    elif co:
        parts.append('pracuje pompa CO')
    elif kol:
        parts.append('pracuje pompa kolektora')
    if not parts:
        return 'Spoczynek'
    text = ', '.join(parts)
    return text[0].upper() + text[1:]


def parse_program_list(text):
    out = []
    for nr, opis, akt in re.findall(r'program nr = (\d+)\s*\nOpis\s*= (.*)\n(?:.*\n)*?Aktywny\s*= (\S+)', text):
        out.append({'nr': int(nr), 'opis': opis.strip(), 'aktywny': akt == 'TAK'})
    return out


def parse_actions(text):
    # lista od najnowszej; kolejne wpisy tej samej akcji co ~1 min zwijane w jeden
    rows = re.findall(r'^(\d\d/\d\d) (\d\d:\d\d):\d\d\s+(\S+)\s+(\S+)\s*$', text, re.M)
    out = []
    for data, czas, prog, akcja in rows:
        last = out[-1] if out else None
        minute = int(czas[:2]) * 60 + int(czas[3:])
        if (last and (last['data'], last['program'], last['akcja']) == (data, prog, akcja)
                and 0 <= last['_min'] - minute <= 2):
            last['od'], last['_min'] = czas, minute
            last['ile'] += 1
        else:
            out.append({'data': data, 'od': czas, 'do': czas, 'program': prog, 'akcja': akcja, 'ile': 1,
                        '_min': minute})
    for a in out:
        del a['_min']
    return out


def manual_heating_program(ctrl_date, ctrl_time, minutes):
    # program S z jednorazową akcją grzania (data!) na najbliższą minutę zegara sterownika.
    # Rok dwucyfrowo: sterownik trzyma rok na 6 bitach od 2000, a kotek wpisuje go bez odjęcia 2000
    # ("2026" zapisało się jako 2026 % 64 = 42, czyli 2042 - akcja nigdy się nie wykonała)
    now = datetime.datetime.strptime('%s %s' % (ctrl_date, ctrl_time), '%Y/%m/%d %H:%M:%S')
    start = now.replace(second=0) + datetime.timedelta(minutes=2 if now.second >= 45 else 1)
    xml = ('<pompa CfgVer="1.0"><program numer="S" opis="reczne grzanie">'
           '<akcja data="%s" czas="%s"><grzanie czas="%d"/></akcja></program></pompa>\n'
           % (start.strftime('%y/%m/%d'), start.strftime('%H:%M'), minutes))
    return xml, start.strftime('%Y/%m/%d %H:%M')


def check_manual_program(text, start):
    # czy sterownik zapisał akcję ręcznego grzania z datą i godziną startu ('RRRR/MM/DD GG:MM')
    m = re.search(r'Grzanie (\d{4}/\d\d/\d\d) +(\d?\d:\d\d)', text)
    if not m:
        raise KotekError('sterownik nie zapisał ręcznego grzania w programie S')
    saved = '%s %s' % (m.group(1), m.group(2).rjust(5, '0'))
    if saved != start:
        raise KotekError('sterownik zapisał ręczne grzanie na %s zamiast %s - pompa nie ruszy' % (saved, start))


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


class HeatPump:
    # stan pompy odczytywany w tle; zmiany zawsze przez kotek, pod blokadą (jedno wywołanie naraz)
    def __init__(self, runner, data_dir, clock=time.time, sleep=time.sleep):
        self.runner = runner
        self.data_dir = data_dir
        self.clock = clock
        self.sleep = sleep
        self.lock = threading.Lock()
        self.status = None
        self.slow = {'program': None, 'programs': [], 'actions_text': ''}
        self.temps = []
        self.error = None
        self.updated = None
        self.status_at = None           # czas Pi, w którym odczytano status (do przeliczenia zegara sterownika)
        self.state_path = os.path.join(data_dir, 'pompa-stan.json')
        self.manual = self._load_manual()

    def _kotek(self, args):
        with self.lock:
            return self.runner(args)

    def _load_manual(self):
        empty = {'pumps_co_until': None, 'pumps_kol_until': None,
                 'heating_start': None, 'heating_start_ts': None, 'heating_until': None}
        try:
            with open(self.state_path) as f:
                empty.update({k: v for k, v in json.load(f).items() if k in empty})
        except (OSError, ValueError):
            pass
        return empty

    def _save_manual(self):
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self.state_path, 'w') as f:
                json.dump(self.manual, f)
        except OSError as e:
            log.error('zapis stanu pompy: %s', e)

    def _expire_manual(self):
        now = self.clock()
        changed = False
        for key in ('pumps_co_until', 'pumps_kol_until'):
            if self.manual[key] and self.manual[key] <= now:
                self.manual[key] = None
                changed = True
        if self.manual['heating_until'] and self.manual['heating_until'] <= now:
            self.manual.update(heating_start=None, heating_start_ts=None, heating_until=None)
            changed = True
        if changed:
            self._save_manual()

    def poll(self, full=False):
        try:
            status = parse_status(self._kotek(['-b', '-x', '0', 'status']))
            temps = parse_sensors(self._kotek(['-b', '-x', '0', 'odczytczujnikow']))
            if full or self.slow['program'] is None or self.clock() - self.slow.get('at', 0) >= SLOW_INTERVAL:
                self.slow = {
                    'program': parse_program(self._kotek(['czytajprogram', '0'])),
                    'programs': parse_program_list(self._kotek(['listaprogramow'])),
                    'actions_text': self._kotek(['wykonaneakcje']),
                    # treść wszystkich programów - do opisu ostatnich akcji
                    'defs': {n: parse_program(self._kotek(['czytajprogram', n])) for n in ('1', '2', '3', '4', 'S')},
                    'at': self.clock(),
                }
            self.status, self.temps, self.error = status, temps, None
            self.status_at = self.clock()
        except (KotekError, ET.ParseError, AttributeError, ValueError, TypeError) as e:
            self.error = 'Brak połączenia ze sterownikiem pompy: %s' % e
            log.error('%s', self.error)
        self.updated = int(self.clock())
        self._expire_manual()

    def snapshot(self):
        if self.status is None and self.error is None:
            return None
        s = self.status or {}
        diff = None
        schedule = []
        ctrl_now = None
        actions_text = self.slow.get('actions_text', '')
        if s.get('clock'):
            ctrl = time.mktime(time.strptime(s['clock'], '%Y/%m/%d %H:%M:%S'))
            diff = round((ctrl - self.status_at) / 60)
            ctrl_now = datetime.datetime.fromtimestamp(ctrl + (self.clock() - self.status_at))
            rows = [(d, c, p, a) for d, c, p, a in
                    re.findall(r'^(\d\d/\d\d) (\d\d:\d\d):\d\d\s+(\S+)\s+(\S+)\s*$', actions_text, re.M)]
            items = (self.slow['program'] or {}).get('items', [])
            schedule = build_schedule(items, rows, s.get('program'), ctrl_now, diff)
        return {
            'ok': self.error is None,
            'error': self.error,
            'updated': self.updated,
            'state': s.get('state'),
            'state_text': s.get('state_text'),
            'fault': s.get('fault'),
            'power_w': s.get('power_w'),
            'tariff': s.get('tariff'),
            'pumps': s.get('pumps', {}),
            'sensors': s.get('sensors', {}),
            'heating_left_s': s.get('heating_left_s'),
            'co_on': s.get('co_on'),
            'cwu_on': s.get('cwu_on'),
            'energy_kwh': s.get('energy_kwh', {}),
            'clock': s.get('clock'),
            'clock_diff_min': diff,
            'program': dict(self.slow['program'] or {}, nr=s.get('program')),
            'programs': [p for p in self.slow['programs'] if 1 <= p['nr'] <= 4],    # tylko te da się włączyć
            'actions': describe_actions(parse_actions(actions_text)[:12], self.slow.get('defs', {}), ctrl_now),
            'schedule': schedule,
            'activity': activity(s) if s else None,
            'temps': self.temps,
            'manual': dict(self.manual),
        }

    def set_program(self, nr):
        if not _is_int(nr) or not 1 <= nr <= 4:
            raise ValueError('program musi być liczbą 1–4')
        self._kotek(['wlaczprogram', str(nr)])
        for attempt in range(PROGRAM_CONFIRM // 2 + 1):
            m = re.search(r'Aktywny program nr \.+ (\d+)', self._kotek(['aktprogram']))
            if m and int(m.group(1)) == nr:
                break
            self.sleep(2)
        else:
            raise KotekError('sterownik nie potwierdził zmiany programu na %d' % nr)
        log.info('program pompy -> %d', nr)
        self.poll(full=True)

    def pumps(self, co_min=0, kol_min=0):
        for v in (co_min, kol_min):
            if not _is_int(v) or not 0 <= v <= 120:
                raise ValueError('czas pompy musi być liczbą całkowitą 0–120 min')
        if co_min == 0 and kol_min == 0:
            raise ValueError('podaj czas dla co najmniej jednej pompy')
        self._kotek(['samepompy', str(kol_min), str(co_min)])     # kolejność: kolektor, CO
        now = self.clock()
        self.manual['pumps_co_until'] = int(now + co_min * 60) if co_min else None
        self.manual['pumps_kol_until'] = int(now + kol_min * 60) if kol_min else None
        self._save_manual()
        log.info('same pompy: CO %d min, kolektor %d min', co_min, kol_min)
        self.poll()

    def stop_pumps(self):
        self._kotek(['samepompy', '0', '0'])
        self.manual['pumps_co_until'] = self.manual['pumps_kol_until'] = None
        self._save_manual()
        log.info('same pompy: stop')
        self.poll()

    def manual_heating(self, hours):
        if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not 0.5 <= hours <= 8:
            raise ValueError('czas grzania musi być liczbą 0,5–8 h')
        if not self.status or not self.status.get('clock'):
            raise KotekError('brak odczytu zegara sterownika')
        # zegar sterownika przesunięty o czas od odczytu statusu
        ctrl = datetime.datetime.strptime(self.status['clock'], '%Y/%m/%d %H:%M:%S')
        ctrl += datetime.timedelta(seconds=round(self.clock() - self.status_at))
        minutes = int(round(hours * 60))
        xml, start = manual_heating_program(ctrl.strftime('%Y/%m/%d'), ctrl.strftime('%H:%M:%S'), minutes)
        path = os.path.join(self.data_dir, 'pompa-S-reczne.xml')
        os.makedirs(self.data_dir, exist_ok=True)
        with open(path, 'w') as f:
            f.write(xml)
        self._kotek(['program', path])
        check_manual_program(self._kotek(['czytajprogram', 'S']), start)
        start_ts = int(self.clock() + (datetime.datetime.strptime(start, '%Y/%m/%d %H:%M') - ctrl).total_seconds())
        self.manual.update(heating_start=start[-5:], heating_start_ts=start_ts,
                           heating_until=start_ts + minutes * 60)
        self._save_manual()
        log.info('ręczne grzanie %d min, start %s (czas sterownika)', minutes, start)
        self.poll(full=True)

    def run(self):
        while True:
            try:
                self.poll()
            except Exception:
                log.exception('odczyt pompy')
            time.sleep(POLL_INTERVAL)

    def start(self):
        threading.Thread(target=self.run, name='pompa', daemon=True).start()
