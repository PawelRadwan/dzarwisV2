#!/usr/bin/python3
# -*- coding: utf-8 -*-
# termometry Zigbee (zakładka Temperatury): odczyty z Zigbee2MQTT przez MQTT. Opis: docs/termometry.md

import json
import logging
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


class Thermometers:
    # każde urządzenie z polem 'temperature' pojawia się samo - nazwa z Zigbee2MQTT jest nazwą na stronie
    def __init__(self, source=mqtt_lines, clock=time.time, sleep=time.sleep):
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

    def snapshot(self):
        now = self.clock()
        with self.lock:
            items = sorted(self.sensors.items(), key=lambda kv: kv[0].lower())
        return {'sensors': [dict(r, id=name, label=name[:1].upper() + name[1:], stale=now - r['ts'] > STALE_S)
                            for name, r in items]}

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
