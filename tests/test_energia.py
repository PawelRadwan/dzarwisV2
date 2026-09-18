# testy odczytu PV/licznika i bilansu dnia: python3 -m unittest discover -s tests
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import energia  # noqa: E402

# prawdziwe rejestry odczytane 2026-09-18 ok. 12:50
GROWATT_3000 = [1, 0, 36621, 2490, 54, 0, 13544, 4242, 54, 0, 23077, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                35969, 5000, 2477, 144, 0, 36016, 0, 0, 0, 0, 0, 0, 0, 0, 2477, 0, 0, 0, 0, 0, 0, 0, 0, 2469,
                20850, 0, 123, 4, 34947, 4, 40442, 0, 60, 1, 17695, 0]
GROWATT_3093 = [475]
GROWATT_3105 = [0, 0]
METER_0 = [17271, 35291, 17268, 63983, 17269, 23973, 16733, 18375, 16185, 14092, 16013, 50841, 50517, 53365,
           17190, 8504, 17014, 28550]
METER_52 = [50503, 44652]
METER_72 = [18208, 23503, 18097, 48514]


class FakeGateway:
    # bramka Modbus: rejestry wejściowe per unit id, błędy per unit id
    def __init__(self):
        self.unit_id = 1
        self.regs = {2: {}, 3: {}}
        self.fail = set()
        self.last_error = 0
        self.load(GROWATT_3000, GROWATT_3093, GROWATT_3105, METER_0, METER_52, METER_72)

    def load(self, g0, g93, g105, m0, m52, m72):
        for base, block in ((3000, g0), (3093, g93), (3105, g105)):
            for i, v in enumerate(block):
                self.regs[2][base + i] = v
        for base, block in ((0, m0), (52, m52), (72, m72)):
            for i, v in enumerate(block):
                self.regs[3][base + i] = v

    def read_input_registers(self, start, count):
        if self.unit_id in self.fail:
            self.last_error = 4
            return None
        try:
            return [self.regs[self.unit_id][start + i] for i in range(count)]
        except KeyError:
            self.last_error = 2
            return None

    def close(self):
        pass


def f32_regs(value):
    import struct
    hi, lo = struct.unpack('>HH', struct.pack('>f', value))
    return [hi, lo]


class DecodeTest(unittest.TestCase):
    def test_decode_growatt(self):
        g = energia.decode_growatt(GROWATT_3000, GROWATT_3093, GROWATT_3105)
        self.assertEqual(g['status'], 1)
        self.assertEqual(g['status_text'], 'Praca')
        self.assertAlmostEqual(g['ac_w'], 3596.9)
        self.assertAlmostEqual(g['freq_hz'], 50.0)
        self.assertAlmostEqual(g['today_kwh'], 12.3)
        self.assertAlmostEqual(g['total_kwh'], 29709.1)
        self.assertAlmostEqual(g['temp_c'], 47.5)
        self.assertEqual((g['fault'], g['warning']), (0, 0))
        self.assertEqual(g['strings'], [{'w': 1354.4, 'v': 249.0, 'a': 5.4}, {'w': 2307.7, 'v': 424.2, 'a': 5.4}])

    def test_decode_meter(self):
        m = energia.decode_meter(METER_0, METER_52, METER_72)
        self.assertAlmostEqual(m['grid_w'], -3194.9, places=1)
        self.assertAlmostEqual(m['import_kwh'], 41051.809, places=2)
        self.assertAlmostEqual(m['export_kwh'], 22750.754, places=2)
        self.assertEqual([round(v, 2) for v in m['phase_w']], [-3421.03, 166.13, 61.61])
        self.assertEqual([round(v, 2) for v in m['voltages']], [247.54, 244.98, 245.37])

    def test_status_text_unknown(self):
        regs = list(GROWATT_3000)
        regs[0] = 7
        self.assertEqual(energia.decode_growatt(regs, GROWATT_3093, GROWATT_3105)['status_text'], 'Kod 7')


class ReadTest(unittest.TestCase):
    def test_reads_use_small_blocks(self):
        gw = FakeGateway()
        calls = []
        orig = gw.read_input_registers
        gw.read_input_registers = lambda s, n: calls.append((gw.unit_id, s, n)) or orig(s, n)
        self.assertIsNotNone(energia.read_growatt(gw))
        self.assertIsNotNone(energia.read_meter(gw))
        self.assertTrue(all(n <= 60 for _, _, n in calls))
        self.assertEqual({u for u, _, _ in calls}, {2, 3})

    def test_read_failure_returns_none(self):
        gw = FakeGateway()
        gw.fail = {2}
        self.assertIsNone(energia.read_growatt(gw))
        self.assertIsNotNone(energia.read_meter(gw))


def local_ts(h, m=0, s=0, day=18):
    return time.mktime((2026, 9, day, h, m, s, 0, 0, -1))


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.gw = FakeGateway()
        self.store = energia.EnergyStore(':memory:')
        self.now = local_ts(12, 50)
        self.col = energia.Collector(self.gw, self.store, clock=lambda: self.now)

    def set_pv_today(self, kwh):
        v = int(round(kwh * 10))
        self.gw.regs[2][3049], self.gw.regs[2][3050] = v >> 16, v & 0xffff

    def set_meter(self, grid_w, import_kwh, export_kwh):
        for base, block in ((52, f32_regs(grid_w)), (72, f32_regs(import_kwh) + f32_regs(export_kwh))):
            for i, v in enumerate(block):
                self.gw.regs[3][base + i] = v

    def test_no_data_before_first_poll(self):
        self.assertIsNone(self.col.snapshot())

    def test_snapshot_now(self):
        self.col.poll()
        s = self.col.snapshot()
        self.assertTrue(s['meter_ok'] and s['inverter_ok'])
        self.assertAlmostEqual(s['now']['pv_w'], 3596.9)
        self.assertAlmostEqual(s['now']['grid_w'], -3194.9, places=1)
        self.assertAlmostEqual(s['now']['home_w'], 3596.9 - 3194.9, places=0)
        self.assertEqual(s['inverter']['status_text'], 'Praca')
        self.assertEqual(len(s['strings']), 2)
        self.assertAlmostEqual(s['totals']['pv_kwh'], 29709.1)

    def test_day_balance(self):
        self.now = local_ts(0, 0, 30)
        self.set_pv_today(0)
        self.set_meter(300, 41000.0, 22740.0)
        self.col.poll()
        self.now = local_ts(12, 50)
        self.set_pv_today(12.3)
        self.set_meter(-3000, 41002.5, 22748.0)
        self.col.poll()
        t = self.col.snapshot()['today']
        self.assertAlmostEqual(t['balance_pv_kwh'], 12.3)
        self.assertAlmostEqual(t['import_kwh'], 2.5, places=2)
        self.assertAlmostEqual(t['export_kwh'], 8.0, places=2)
        self.assertAlmostEqual(t['pv_kwh'], 12.3)
        self.assertAlmostEqual(t['home_kwh'], 12.3 + 2.5 - 8.0, places=2)
        self.assertEqual(t['self_use_pct'], round((12.3 - 8.0) / 12.3 * 100))
        self.assertEqual(t['since'], int(local_ts(0, 0, 30)))

    def test_day_balance_survives_restart(self):
        self.now = local_ts(6, 0)
        self.set_meter(300, 41000.0, 22740.0)
        self.col.poll()
        self.now = local_ts(6, 1, 5)
        self.col.poll()                       # nowa minuta -> zapis do bazy
        col2 = energia.Collector(self.gw, self.store, clock=lambda: self.now)
        self.now = local_ts(13, 0)
        self.set_meter(-3000, 41001.0, 22745.0)
        col2.poll()
        t = col2.snapshot()['today']
        self.assertAlmostEqual(t['import_kwh'], 1.0, places=2)
        self.assertEqual(t['since'], int(local_ts(6, 0)))

    def test_started_mid_day_balance_covers_same_period(self):
        # start zbierania o 13:10 - produkcja od północy (12.8) nie może trafić do bilansu od 13:10
        self.now = local_ts(13, 10)
        self.set_pv_today(12.8)
        self.set_meter(-3000, 41000.0, 22740.0)
        self.col.poll()
        t = self.col.snapshot()['today']
        self.assertAlmostEqual(t['pv_kwh'], 12.8)
        self.assertAlmostEqual(t['balance_pv_kwh'], 0.0)
        self.assertAlmostEqual(t['home_kwh'], 0.0)
        self.assertIsNone(t['self_use_pct'])
        self.now = local_ts(14, 10)
        self.set_pv_today(15.8)
        self.set_meter(-2500, 41000.1, 22742.5)
        self.col.poll()
        t = self.col.snapshot()['today']
        self.assertAlmostEqual(t['balance_pv_kwh'], 3.0)
        self.assertAlmostEqual(t['home_kwh'], 3.0 + 0.1 - 2.5, places=2)
        self.assertEqual(t['self_use_pct'], round((3.0 - 2.5) / 3.0 * 100))

    def test_new_day_resets_balance(self):
        self.now = local_ts(23, 59)
        self.set_meter(300, 41000.0, 22740.0)
        self.col.poll()
        self.now = local_ts(0, 1, day=19)
        self.set_meter(300, 41000.2, 22740.0)
        self.col.poll()
        t = self.col.snapshot()['today']
        self.assertAlmostEqual(t['import_kwh'], 0.0)
        self.assertEqual(t['since'], int(local_ts(0, 1, day=19)))

    def test_inverter_asleep(self):
        self.col.poll()                       # dzień: produkcja dziś 12.3
        self.now += 120
        self.col.poll()
        self.gw.fail = {2}
        self.now += 120
        self.col.poll()
        s = self.col.snapshot()
        self.assertFalse(s['inverter_ok'])
        self.assertTrue(s['meter_ok'])
        self.assertEqual(s['now']['pv_w'], 0)
        self.assertAlmostEqual(s['now']['home_w'], s['now']['grid_w'])
        self.assertAlmostEqual(s['today']['pv_kwh'], 12.3)
        self.assertEqual(s['inverter']['status_text'], 'Nie odpowiada')
        self.assertEqual(s['strings'], [])

    def test_meter_down(self):
        self.gw.fail = {3}
        self.col.poll()
        s = self.col.snapshot()
        self.assertFalse(s['meter_ok'])
        self.assertIsNone(s['now']['grid_w'])
        self.assertIsNone(s['now']['home_w'])
        self.assertAlmostEqual(s['now']['pv_w'], 3596.9)

    def test_minute_averages_and_day_points(self):
        base = local_ts(12, 0)
        for i, grid in enumerate((-3000, -3200, -3400)):
            self.now = base + i * 5
            self.set_meter(grid, 41000.0, 22740.0)
            self.col.poll()
        self.now = base + 65                  # następna minuta -> zapis poprzedniej
        self.col.poll()
        pts = self.col.day()['points']
        self.assertEqual(len(pts), 1)
        ts, pv, home = pts[0]
        self.assertEqual(ts, int(base))
        self.assertAlmostEqual(pv, 3596.9)
        self.assertAlmostEqual(home, 3596.9 - 3200, places=0)
        self.assertEqual(self.col.day()['date'], '2026-09-18')

    def test_store_error_does_not_break_live(self):
        self.store.add = lambda *a: (_ for _ in ()).throw(RuntimeError('dysk'))
        self.col.poll()
        self.now += 65
        self.col.poll()
        self.assertTrue(self.col.snapshot()['meter_ok'])


if __name__ == '__main__':
    unittest.main()
