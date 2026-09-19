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

    def test_implausible_inverter_reading_rejected(self):
        # 2026-09-19 06:20 przy starcie falownika: moc AC ~390 MW -> odczyt odrzucony, nie trafia do bilansów
        gw = FakeGateway()
        gw.regs[2][3023], gw.regs[2][3024] = 0x3A2F, 0x1234          # ~97 MW
        self.assertIsNone(energia.read_growatt(gw))
        gw.regs[2][3023], gw.regs[2][3024] = 0, 35969                 # 3596.9 W - prawidłowy
        self.assertIsNotNone(energia.read_growatt(gw))

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

    def polls(self, start, grid_w, count, step=5):
        # kolejne odczyty co step sekund z tą samą mocą sieci
        for i in range(count):
            self.now = start + i * step
            self.set_meter(grid_w, 41000.0, 22740.0)
            self.col.poll()
        return start + count * step

    def test_balanced_import_export(self):
        # bilansowanie faz: dodatnia moc łączna -> pobór, ujemna -> oddanie; moc x czas od poprzedniego odczytu
        t = self.polls(local_ts(12, 0), 36000, 3)             # 2 przedziały po 5 s x 36 kW = 100 Wh
        self.polls(t, -72000, 2)                              # 2 x 5 s x 72 kW = 200 Wh
        today = self.col.snapshot()['today']
        self.assertAlmostEqual(today['import_kwh'], 0.1, places=3)
        self.assertAlmostEqual(today['export_kwh'], 0.2, places=3)

    def test_balance_pv_integrated_like_grid(self):
        # produkcja w bilansie liczona tak samo jak pobór/oddanie (moc x czas), a nie z licznika falownika co 0.1 kWh
        self.set_pv_today(12.3)
        self.polls(local_ts(12, 0), -1000, 3)                 # falownik 3596.9 W, 2 x 5 s
        d = self.col.snapshot()['today']
        pv = 3596.9 * 10 / 3600 / 1000
        self.assertAlmostEqual(d['balance_pv_kwh'], pv, places=3)
        self.assertAlmostEqual(d['export_kwh'], 1000 * 10 / 3600 / 1000, places=3)
        self.assertAlmostEqual(d['home_kwh'], pv - 1000 * 10 / 3600 / 1000, places=3)
        self.assertEqual(d['pv_kwh'], 12.3)                   # kafelek "Produkcja dziś" - licznik falownika

    def test_all_summaries_agree(self):
        # bilans dnia, "Łącznie" i miesiąc za ten sam okres muszą się zgadzać (także z bieżącą, niezapisaną minutą)
        t = self.polls(local_ts(12, 0, 30), -1000, 8)        # przez granicę minuty
        self.polls(t, 500, 3)
        d = self.col.snapshot()['today']
        m = self.col.months()
        for s in (m['totals'], m['months'][0]):
            self.assertAlmostEqual(s['import_kwh'], d['import_kwh'], places=3)
            self.assertAlmostEqual(s['export_kwh'], d['export_kwh'], places=3)
            self.assertAlmostEqual(s['pv_kwh'], d['balance_pv_kwh'], places=3)
            self.assertAlmostEqual(s['home_kwh'], d['home_kwh'], places=3)
            self.assertEqual(s['self_use_pct'], d['self_use_pct'])

    def test_rows_without_pv_energy_not_in_day_balance(self):
        # minuty zapisane przed wprowadzeniem bal_pv_wh (niepełne) nie mogą trafiać do bilansu dnia
        self.store.add(int(local_ts(12, 0)), 3000, -2000, 1000, 5.0, 29700.0, 41000, 22740, 500.0, 900.0)
        self.polls(local_ts(12, 30), -1000, 3)
        d = self.col.snapshot()['today']
        m = self.col.months()
        self.assertAlmostEqual(d['import_kwh'], m['totals']['import_kwh'], places=3)
        self.assertAlmostEqual(d['export_kwh'], m['totals']['export_kwh'], places=3)
        self.assertAlmostEqual(d['import_kwh'], 0.0, places=3)

    def test_gap_not_integrated(self):
        self.polls(local_ts(12, 0), 36000, 1)
        self.polls(local_ts(12, 2), 36000, 1)                 # 120 s przerwy - nie doliczamy
        self.assertAlmostEqual(self.col.snapshot()['today']['import_kwh'], 0.0)

    def test_day_balance(self):
        self.set_pv_today(0)
        t = self.polls(local_ts(0, 0, 30), 36000, 3)          # pobór 0.1 kWh
        self.set_pv_today(12.3)
        self.polls(t, -72000, 2)                              # oddanie 0.2 kWh
        d = self.col.snapshot()['today']
        pv = 3596.9 * 20 / 3600 / 1000                        # 4 przedziały po 5 s
        self.assertAlmostEqual(d['balance_pv_kwh'], pv, places=3)
        self.assertAlmostEqual(d['pv_kwh'], 12.3)
        self.assertAlmostEqual(d['home_kwh'], max(pv + 0.1 - 0.2, 0), places=3)   # dane testowe: dom obcięty do 0
        self.assertEqual(d['since'], int(local_ts(0, 0, 30)))

    def test_day_balance_survives_restart(self):
        t = self.polls(local_ts(6, 0), 36000, 3)              # 0.1 kWh w minucie 6:00
        self.polls(local_ts(6, 1, 5), 36000, 1)               # nowa minuta -> zapis 6:00 do bazy (przerwa > 30 s)
        col2 = energia.Collector(self.gw, self.store, clock=lambda: self.now)
        self.col = col2
        self.polls(local_ts(13, 0), 36000, 3)                 # kolejne 0.1 kWh
        d = col2.snapshot()['today']
        self.assertAlmostEqual(d['import_kwh'], 0.2, places=3)
        self.assertEqual(d['since'], int(local_ts(6, 0)))

    def test_started_mid_day_balance_covers_same_period(self):
        # start zbierania o 13:10 - produkcja od północy (12.8) nie może trafić do bilansu od 13:10
        self.set_pv_today(12.8)
        t = self.polls(local_ts(13, 10), -36000, 1)
        d = self.col.snapshot()['today']
        self.assertAlmostEqual(d['pv_kwh'], 12.8)
        self.assertAlmostEqual(d['balance_pv_kwh'], 0.0)
        self.assertAlmostEqual(d['home_kwh'], 0.0)
        self.assertIsNone(d['self_use_pct'])
        self.set_pv_today(13.1)
        self.polls(t, -1000, 2)
        d = self.col.snapshot()['today']
        self.assertAlmostEqual(d['pv_kwh'], 13.1)
        self.assertAlmostEqual(d['balance_pv_kwh'], 3596.9 * 10 / 3600 / 1000, places=3)

    def test_balance_starts_with_balanced_data(self):
        # wiersze sprzed wprowadzenia bilansowania (bez bal_*) nie mogą wyznaczać początku bilansu dnia
        self.store.add(int(local_ts(13, 10)), 3000, -2000, 1000, 12.8, 29700.0, 41000.0, 22740.0)
        self.set_pv_today(19.8)
        self.polls(local_ts(15, 12), -36000, 3)               # oddanie 0.1 kWh
        d = self.col.snapshot()['today']
        self.assertEqual(d['since'], int(local_ts(15, 12)))
        self.assertAlmostEqual(d['balance_pv_kwh'], 3596.9 * 10 / 3600 / 1000, places=3)

    def test_new_day_resets_balance(self):
        t = self.polls(local_ts(23, 59, 50), 36000, 2)        # 50 Wh jeszcze 18.09
        self.polls(local_ts(0, 0, 0, day=19), 36000, 1)       # 50 Wh już 19.09
        d = self.col.snapshot()['today']
        self.assertAlmostEqual(d['import_kwh'], 0.05, places=3)
        self.assertEqual(d['since'], int(local_ts(0, 0, 0, day=19)))

    def test_months_and_totals(self):
        s = self.store
        # wrzesień: 2 minuty, październik: 1 minuta; produkcja z licznika falownika (pv_total_kwh)
        s.add(int(local_ts(12, 0, day=18)), 3000, -2000, 1000, 5.0, 29700.0, 41000, 22740, 100.0, 2000.0, 20000.0)
        s.add(int(local_ts(12, 1, day=30)), 3000, -2000, 1000, 9.0, 29760.0, 41000, 22740, 400.0, 3000.0, 40000.0)
        s.add(int(time.mktime((2026, 10, 2, 12, 0, 0, 0, 0, -1))), 0, 500, 500, 1.0, 29790.0, 41000, 22740,
              500.0, 0.0, 30000.0)
        m = self.col.months()
        self.assertEqual([x['month'] for x in m['months']], ['2026-10', '2026-09'])
        oct_, sep = m['months']
        self.assertAlmostEqual(sep['import_kwh'], 0.5)
        self.assertAlmostEqual(sep['export_kwh'], 5.0)
        self.assertAlmostEqual(sep['pv_kwh'], 60.0)              # 20 + 40 kWh (moc x czas)
        self.assertAlmostEqual(sep['home_kwh'], 60.0 + 0.5 - 5.0)
        self.assertEqual(sep['self_use_pct'], round((60.0 - 5.0) / 60.0 * 100))
        self.assertEqual(sep['from_day'], 18)
        self.assertAlmostEqual(oct_['pv_kwh'], 30.0)
        self.assertEqual(oct_['from_day'], 2)
        self.assertAlmostEqual(m['totals']['import_kwh'], 1.0)
        self.assertAlmostEqual(m['totals']['export_kwh'], 5.0)
        self.assertAlmostEqual(m['totals']['pv_kwh'], 90.0)
        self.assertEqual(m['since'], int(local_ts(12, 0, day=18)))

    def test_old_database_migrated(self):
        import sqlite3
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), 'energia.db')
        db = sqlite3.connect(path)
        db.execute('CREATE TABLE samples (ts INTEGER PRIMARY KEY, pv_w REAL, grid_w REAL, home_w REAL, '
                   'pv_today_kwh REAL, pv_total_kwh REAL, import_kwh REAL, export_kwh REAL)')
        db.execute('INSERT INTO samples VALUES (1, 2, 3, 4, 5, 6, 7, 8)')
        db.commit()
        db.close()
        st = energia.EnergyStore(path)
        st.add(60, 1, 2, 3, 4, 5, 6, 7, 10.0, 20.0, 30.0)
        rows = st.db.execute('SELECT ts, pv_w, bal_import_wh, bal_export_wh, bal_pv_wh FROM samples ORDER BY ts').fetchall()
        self.assertEqual(rows, [(1, 2.0, None, None, None), (60, 1.0, 10.0, 20.0, 30.0)])

    def test_phases(self):
        # falownik jednofazowy na L1: dom na L1 = sieć L1 + produkcja, na L2/L3 = sieć
        self.col.poll()
        ph = self.col.snapshot()['phases']
        self.assertEqual([p['name'] for p in ph], ['L1', 'L2', 'L3'])
        self.assertEqual([p['grid_w'] for p in ph], [-3421.0, 166.1, 61.6])
        self.assertEqual([p['home_w'] for p in ph], [round(-3421.03 + 3596.9, 1), 166.1, 61.6])
        self.assertEqual([p['v'] for p in ph], [247.5, 245.0, 245.4])
        self.assertAlmostEqual(ph[0]['a'], energia.decode_meter(METER_0, METER_52, METER_72)['currents'][0], places=1)
        self.assertEqual([p['inverter'] for p in ph], [True, False, False])

    def test_phases_meter_down(self):
        self.gw.fail = {3}
        self.col.poll()
        self.assertEqual(self.col.snapshot()['phases'], [])

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

    def test_day_for_selected_date(self):
        self.store.add(int(local_ts(12, 0, day=17)), 1000, 0, 1000, 1, 1, 1, 1, 0, 0, 16.7)
        self.store.add(int(local_ts(13, 0, day=18)), 2000, 0, 2000, 1, 1, 1, 1, 0, 0, 33.3)
        d = self.col.day('2026-09-17')
        self.assertEqual(d['date'], '2026-09-17')
        self.assertEqual([p[1] for p in d['points']], [1000])
        self.assertEqual(d['first_date'], '2026-09-17')
        self.assertEqual(d['today'], '2026-09-18')
        self.assertEqual(self.col.day()['date'], '2026-09-18')
        for bad in ('2026-13-01', 'wczoraj', '2026-09-18; drop', ''):
            with self.assertRaises(ValueError):
                self.col.day(bad)

    def test_store_error_does_not_break_live(self):
        self.store.add = lambda *a: (_ for _ in ()).throw(RuntimeError('dysk'))
        self.col.poll()
        self.now += 65
        self.col.poll()
        self.assertTrue(self.col.snapshot()['meter_ok'])


if __name__ == '__main__':
    unittest.main()
