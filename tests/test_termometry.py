# testy termometrów Zigbee bez brokera MQTT: python3 -m unittest discover -s tests
import os
import sys
import time
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



class HistoryTest(unittest.TestCase):
    def setUp(self):
        # 2026-10-13 12:00 czasu lokalnego
        self.now = time.mktime((2026, 10, 13, 12, 0, 0, 0, 0, -1))
        self.store = termometry.TempStore(':memory:')
        self.t = termometry.Thermometers(source=lambda: [], clock=lambda: self.now, store=self.store)

    def feed(self, name, temp, ago_s, humidity=50):
        self.t.feed('zigbee2mqtt/%s {"temperature":%s,"humidity":%s,"last_seen":%d}'
                    % (name, temp, humidity, (self.now - ago_s) * 1000))

    def test_last_24h_is_default(self):
        self.feed('kuchnia', 19, 25 * 3600)
        self.feed('kuchnia', 20, 23 * 3600)
        self.feed('kuchnia', 22.5, 60, humidity=48)
        self.feed('salon', 30, 60)
        h = self.t.history('kuchnia')
        self.assertEqual(h['points'], [[self.now - 23 * 3600, 20, 50], [self.now - 60, 22.5, 48]])
        self.assertEqual((h['min'], h['max'], h['date'], h['today']), (20, 22.5, None, '2026-10-13'))
        self.assertEqual((h['start'], h['end']), (self.now - 86400, self.now + 1))
        self.assertEqual((h['id'], h['label'], h['first_date']), ('kuchnia', 'Kuchnia', '2026-10-12'))

    def test_earlier_day_is_calendar_day(self):
        self.feed('kuchnia', 18, 12 * 3600 + 1)        # 12.10 23:59:59
        self.feed('kuchnia', 21, 12 * 3600)            # 13.10 00:00:00
        self.feed('kuchnia', 17, 36 * 3600)            # 12.10 00:00:00
        self.feed('kuchnia', 16, 36 * 3600 + 1)        # 11.10 23:59:59
        h = self.t.history('kuchnia', '2026-10-12')
        self.assertEqual([p[1] for p in h['points']], [17, 18])
        self.assertEqual((h['date'], h['end'] - h['start'], h['first_date']), ('2026-10-12', 86400, '2026-10-11'))

    def test_today_or_future_date_means_last_24h(self):
        self.feed('kuchnia', 20, 13 * 3600)            # wczoraj 23:00 - w ostatnich 24 h, poza dzisiejszą dobą
        for date in ('2026-10-13', '9999-12-31'):
            h = self.t.history('kuchnia', date)
            self.assertEqual((h['date'], len(h['points'])), (None, 1))

    def test_no_data(self):
        h = self.t.history('strych')
        self.assertEqual((h['points'], h['min'], h['max'], h['first_date']), ([], None, None, None))
        self.assertEqual(termometry.Thermometers(source=lambda: [], clock=lambda: self.now).history('kuchnia')['points'], [])

    def test_date_out_of_range(self):
        # na 32-bitowym Pi mktime rzuca OverflowError poza latami 1901-2038
        real = termometry.time.mktime

        def overflow(_):
            raise OverflowError('mktime argument out of range')

        termometry.time.mktime = overflow
        try:
            self.assertRaises(ValueError, self.t.history, 'kuchnia', '1800-01-01')
            self.assertIsNone(self.t.history('kuchnia', '9999-12-31')['date'])
        finally:
            termometry.time.mktime = real

    def test_bad_date(self):
        for date in ('wczoraj', '2026-13-01', ''):
            self.assertRaises(ValueError, self.t.history, 'kuchnia', date)

    def test_repeated_message_is_stored_once(self):
        # broker przysyła zapamiętaną wartość po każdym restarcie panelu
        self.feed('kuchnia', 20, 600)
        self.feed('kuchnia', 20, 600)
        self.assertEqual(len(self.t.history('kuchnia')['points']), 1)

    def test_history_survives_restart(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'data', 'termometry.db')
            store = termometry.TempStore(path)
            store.add('kuchnia', int(self.now) - 60, 21.4, 55)
            store.db.close()
            t = termometry.Thermometers(source=lambda: [], clock=lambda: self.now, store=termometry.TempStore(path))
            self.assertEqual(t.history('kuchnia')['points'], [[self.now - 60, 21.4, 55]])
            t.store.db.close()


if __name__ == '__main__':
    unittest.main()
