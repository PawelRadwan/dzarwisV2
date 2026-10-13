#!/usr/bin/python3
# -*- coding: utf-8 -*-
# termometry Zigbee (zakładka Temperatury): odczyty z Zigbee2MQTT przez MQTT. Opis: docs/termometry.md

import json
import logging
import os
import sqlite3
import subprocess
import threading
import time

# Zigbee2MQTT publikuje stan każdego urządzenia w temacie zigbee2mqtt/<nazwa>
TOPIC_PREFIX = 'zigbee2mqtt/'
# -v: przed treścią nazwa tematu; '+' pomija tematy mostka (zigbee2mqtt/bridge/...)
MQTT_CMD = ['mosquitto_sub', '-h', '127.0.0.1', '-v', '-t', TOPIC_PREFIX + '+']
RETRY_S = 5
# czujnik zgłasza się najrzadziej co godzinę; dłuższa cisza = bateria albo zasięg
STALE_S = 3 * 3600

log = logging.getLogger('termometry')


def mqtt_lines():
    # wiersze 'temat treść' aż do zerwania połączenia z brokerem
    proc = subprocess.Popen(MQTT_CMD, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
    try:
        for line in proc.stdout:
            yield line
    finally:
        proc.kill()
        proc.wait()


def day_bounds(date):
    # początek i koniec doby 'RRRR-MM-DD' (czas lokalny Pi)
    try:
        lt = time.strptime(date, '%Y-%m-%d')
    except (TypeError, ValueError):
        raise ValueError('data w formacie RRRR-MM-DD')
    start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    end = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + 1, 0, 0, 0, 0, 0, -1))
    return int(start), int(end)


def date_of(ts):
    return time.strftime('%Y-%m-%d', time.localtime(ts))


def label_of(name):
    return name[:1].upper() + name[1:]


class TempStore:
    # historia odczytów w SQLite: wiersz na każdy komunikat czujnika (ts = czas kontaktu, epoch s)
    def __init__(self, path):
        if path != ':memory:':
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.execute('CREATE TABLE IF NOT EXISTS readings ('
                            'name TEXT NOT NULL, ts INTEGER NOT NULL, temperature REAL NOT NULL, humidity REAL, '
                            'PRIMARY KEY (name, ts)) WITHOUT ROWID')
            self.db.commit()

    def add(self, name, ts, temperature, humidity):
        # ten sam (name, ts) = wartość zapamiętana przez broker, przysłana ponownie po restarcie
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO readings (name, ts, temperature, humidity) VALUES (?, ?, ?, ?)',
                            (name, ts, temperature, humidity))
            self.db.commit()

    def points(self, name, start, end):
        with self.lock:
            return [list(row) for row in self.db.execute(
                'SELECT ts, temperature, humidity FROM readings WHERE name = ? AND ts >= ? AND ts < ? ORDER BY ts',
                (name, start, end))]

    def first_ts(self, name):
        with self.lock:
            return self.db.execute('SELECT MIN(ts) FROM readings WHERE name = ?', (name,)).fetchone()[0]


class Thermometers:
    # każde urządzenie z polem 'temperature' pojawia się samo - nazwa z Zigbee2MQTT jest nazwą na stronie
    # store: TempStore z historią do wykresu; None = bez historii
    def __init__(self, source=mqtt_lines, clock=time.time, sleep=time.sleep, store=None):
        self.store = store
        self.source = source
        self.clock = clock
        self.sleep = sleep
        self.lock = threading.Lock()
        self.sensors = {}       # nazwa -> ostatni odczyt

    def feed(self, line):
        # nazwa urządzenia może zawierać spacje - treść JSON zaczyna się od ' {'
        line = line.rstrip('\n')
        topic, sep, payload = line.partition(' {')
        if not topic.startswith(TOPIC_PREFIX):
            return
        if not sep:
            # pusta treść = Zigbee2MQTT skasował temat (zmiana nazwy, usunięcie urządzenia)
            name = line[len(TOPIC_PREFIX):]
            if name.endswith(' (null)'):
                name = name[:-len(' (null)')]
            with self.lock:
                self.sensors.pop(name.rstrip(), None)
            return
        name = topic[len(TOPIC_PREFIX):]
        try:
            data = json.loads('{' + payload)
        except ValueError:
            return
        temp = data.get('temperature')
        if isinstance(temp, bool) or not isinstance(temp, (int, float)):
            return
        # last_seen (ms) - czas odczytu także dla wartości zapamiętanej przez broker
        seen = data.get('last_seen')
        ts = seen / 1000 if isinstance(seen, (int, float)) and not isinstance(seen, bool) else self.clock()
        reading = {'temperature': temp, 'ts': int(ts)}
        for key in ('humidity', 'battery', 'linkquality'):
            value = data.get(key)
            reading[key] = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        with self.lock:
            self.sensors[name] = reading
        if self.store:
            self.store.add(name, reading['ts'], temp, reading['humidity'])

    def snapshot(self):
        now = self.clock()
        with self.lock:
            items = sorted(self.sensors.items(), key=lambda kv: kv[0].lower())
        return {'sensors': [dict(r, id=name, label=label_of(name), stale=now - r['ts'] > STALE_S)
                            for name, r in items]}

    def history(self, name, date=None):
        # date None albo dzisiejsza/przyszła = ostatnie 24 h; wcześniejsza = doba kalendarzowa 00:00-24:00
        now = int(self.clock())
        today = date_of(now)
        if date is not None:
            start, end = day_bounds(date)
            if date >= today:
                date = None
        if date is None:
            start, end = now - 86400, now + 1
        points = self.store.points(name, start, end) if self.store else []
        first = self.store.first_ts(name) if self.store else None
        temps = [p[1] for p in points]
        return {'id': name, 'label': label_of(name), 'date': date, 'today': today, 'start': start, 'end': end,
                'first_date': date_of(first) if first is not None else None,
                'min': min(temps) if temps else None, 'max': max(temps) if temps else None, 'points': points}

    def run(self):
        while True:
            try:
                for line in self.source():
                    self.feed(line)
                log.warning('MQTT: połączenie zakończone, ponawiam za %s s', RETRY_S)
            except Exception as e:
                log.error('MQTT: %s, ponawiam za %s s', e, RETRY_S)
            self.sleep(RETRY_S)

    def start(self):
        threading.Thread(target=self.run, name='termometry', daemon=True).start()
