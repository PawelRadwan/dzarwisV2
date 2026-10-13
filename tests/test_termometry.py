# testy termometrów Zigbee bez brokera MQTT: python3 -m unittest discover -s tests
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import termometry  # noqa: E402


class StopLoop(Exception):
    pass


class ThermometersTest(unittest.TestCase):
    def setUp(self):
        self.now = 1000000.0
        self.t = termometry.Thermometers(source=lambda: [], clock=lambda: self.now)

    def sensors(self):
        return self.t.snapshot()['sensors']

    def test_reading_with_all_fields(self):
        self.t.feed('zigbee2mqtt/kuchnia {"battery":100,"humidity":55.4,"linkquality":92,"temperature":21.4}\n')
        self.assertEqual(self.sensors(), [{
            'id': 'kuchnia', 'label': 'Kuchnia', 'temperature': 21.4, 'humidity': 55.4,
            'battery': 100, 'linkquality': 92, 'ts': 1000000, 'stale': False}])

    def test_last_seen_gives_reading_time(self):
        # wartość zapamiętana przez broker przychodzi po restarcie panelu - liczy się czas z czujnika
        self.t.feed('zigbee2mqtt/kuchnia {"temperature":20,"last_seen":%d}' % ((self.now - 600) * 1000))
        self.assertEqual(self.sensors()[0]['ts'], self.now - 600)

    def test_missing_fields_are_none(self):
        self.t.feed('zigbee2mqtt/piwnica {"temperature":8}')
        s = self.sensors()[0]
        self.assertEqual((s['humidity'], s['battery'], s['linkquality']), (None, None, None))

    def test_name_with_space(self):
        self.t.feed('zigbee2mqtt/pokój Oli {"temperature":22.5}')
        self.assertEqual([(s['id'], s['label']) for s in self.sensors()], [('pokój Oli', 'Pokój Oli')])
        self.t.feed('zigbee2mqtt/pokój Oli (null)')
        self.assertEqual(self.sensors(), [])

    def test_broken_json_keeps_last_reading(self):
        self.t.feed('zigbee2mqtt/kuchnia {"temperature":20}')
        self.t.feed('zigbee2mqtt/kuchnia {"temperature":')
        self.assertEqual(self.sensors()[0]['temperature'], 20)

    def test_devices_without_temperature_are_ignored(self):
        self.t.feed('zigbee2mqtt/gniazdko {"state":"ON","linkquality":80}')
        self.t.feed('zigbee2mqtt/dziwny {"temperature":"ciepło"}')
        self.t.feed('zigbee2mqtt/logiczny {"temperature":true}')
        self.t.feed('inny/temat {"temperature":20}')
        self.t.feed('zigbee2mqtt/lista [1,2]')
        self.assertEqual(self.sensors(), [])

    def test_sorted_by_name(self):
        for name in ('salon', 'Biuro', 'kuchnia'):
            self.t.feed('zigbee2mqtt/%s {"temperature":20}' % name)
        self.assertEqual([s['label'] for s in self.sensors()], ['Biuro', 'Kuchnia', 'Salon'])

    def test_newer_reading_replaces_older(self):
        self.t.feed('zigbee2mqtt/kuchnia {"temperature":20,"humidity":50}')
        self.t.feed('zigbee2mqtt/kuchnia {"temperature":21.5}')
        s = self.sensors()
        self.assertEqual(len(s), 1)
        self.assertEqual((s[0]['temperature'], s[0]['humidity']), (21.5, None))

    def test_empty_payload_removes_sensor(self):
        # tak Zigbee2MQTT kasuje temat po zmianie nazwy albo usunięciu urządzenia
        self.t.feed('zigbee2mqtt/termometr {"temperature":20}')
        self.t.feed('zigbee2mqtt/termometr (null)')
        self.assertEqual(self.sensors(), [])
        self.t.feed('zigbee2mqtt/termometr {"temperature":20}')
        self.t.feed('zigbee2mqtt/termometr \n')
        self.assertEqual(self.sensors(), [])

    def test_stale_after_long_silence(self):
        self.t.feed('zigbee2mqtt/kuchnia {"temperature":20}')
        self.now += termometry.STALE_S
        self.assertFalse(self.sensors()[0]['stale'])
        self.now += 1
        self.assertTrue(self.sensors()[0]['stale'])

    def test_run_reconnects_after_source_ends_or_fails(self):
        calls, sleeps = [], []

        def source():
            calls.append(1)
            if len(calls) == 1:
                return ['zigbee2mqtt/kuchnia {"temperature":20}']
            if len(calls) == 2:
                raise OSError('brak mosquitto_sub')
            return ['zigbee2mqtt/salon {"temperature":21}']

        def sleep(s):
            sleeps.append(s)
            if len(sleeps) == 3:
                raise StopLoop

        t = termometry.Thermometers(source=source, clock=lambda: self.now, sleep=sleep)
        with self.assertLogs('termometry'):
            self.assertRaises(StopLoop, t.run)
        self.assertEqual(sleeps, [termometry.RETRY_S] * 3)
        self.assertEqual([s['id'] for s in t.snapshot()['sensors']], ['kuchnia', 'salon'])


if __name__ == '__main__':
    unittest.main()
