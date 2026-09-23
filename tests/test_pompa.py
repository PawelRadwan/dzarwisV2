# testy obsługi pompy ciepła przez kotek_rpi: python3 -m unittest discover -s tests
import re
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import pompa  # noqa: E402

DANE = os.path.join(ROOT, 'tests', 'dane_pompy')


def dane(nazwa):
    with open(os.path.join(DANE, nazwa), encoding='utf-8', errors='replace') as f:
        return f.read()


STATUS = dane('status.xml')             # nagrane 2026-09-18 13:03:57 (czas sterownika), awaria PWR, program 3
CZUJNIKI = dane('czujniki.xml')
PROGRAM_4 = dane('program-4.txt')
AKCJE = dane('wykonaneakcje.txt')
LISTA = dane('listaprogramow.txt')

AKTPROGRAM = 'Aktywny program nr ... {nr}\nOpis ................. x\nStatus ............... poprawny\n'


def strip_opts(args):
    # polecenie bez opcji -b / -x <plik>
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a == '-x':
            skip = True
        elif a != '-b':
            out.append(a)
    return out


def status_grzanie(do_konca='00:47:12', stan='GRZANIE'):
    s = STATUS.replace('doKonca="00:00:00"', 'doKonca="%s"' % do_konca)
    return s.replace('nazwa="AWARIA"', 'nazwa="%s"' % stan).replace('opis="Awaria           "', 'opis="Grzanie"')


class FakeKotek:
    # nagrane odpowiedzi kotek_rpi; zapisuje wywołania
    def __init__(self):
        self.calls = []
        self.status = STATUS
        self.fail = False
        self.active = 3
        self.program_files = []
        self.program_s = 'Program nr ........... 17\nOpis ................. brak\n'
        self.saved_days = None                 # np. 'codziennie' - kotek zapisał inaczej, niż wysłano

    def __call__(self, args):
        self.calls.append(list(args))
        if self.fail:
            raise pompa.KotekError('Brak powierdzenia na wyslane polecenia')
        cmd = strip_opts(args)[0]
        if cmd == 'status':
            return self.status
        if cmd == 'odczytczujnikow':
            return CZUJNIKI
        if cmd == 'czytajprogram':
            if args[-1] == 'S':
                return self.program_s
            return PROGRAM_4
        if cmd == 'wykonaneakcje':
            return AKCJE
        if cmd == 'listaprogramow':
            return LISTA
        if cmd == 'aktprogram':
            return AKTPROGRAM.format(nr=self.active)
        if cmd == 'wlaczprogram':
            self.active = int(args[-1])
            return 'setActPrg.programNr=%d [2]\n' % (self.active - 1)
        if cmd == 'samepompy':
            return ''
        if cmd == 'program':
            with open(args[-1]) as f:
                self.program_files.append(f.read())
            # wydruk jak z prawdziwego czytajprogram: dni jako maska, np. "..S...." = środa
            m = re.search(r'dni="(\w\w)" czas="(\d\d:\d\d)"><grzanie czas="(\d+)"', self.program_files[-1])
            if m:
                i = pompa.DAYS.index(m.group(1))
                mask = ''.join(d[0] if n == i else '.' for n, d in enumerate(pompa.DAYS))
                self.program_s = ('Program nr ........... 17\nOpis ................. reczne grzanie\n'
                                  'AK. 1: Grzanie %s    %s pco=      zew=      czas= %smin \r\n'
                                  % (self.saved_days or mask, m.group(2), m.group(3)))
            elif 'numer="S" opis="brak"' in self.program_files[-1]:
                self.program_s = 'Program nr ........... 17\nOpis ................. brak\n'
            return ''
        raise AssertionError('niedozwolone polecenie: %r' % (args,))


class ParseTest(unittest.TestCase):
    def test_status(self):
        s = pompa.parse_status(STATUS)
        self.assertEqual(s['state'], 'AWARIA')
        self.assertEqual(s['state_text'], 'Awaria')
        self.assertEqual(s['fault'], 'Presostaty lub PWR')
        self.assertEqual(s['clock'], '2026/09/18 13:03:57')
        self.assertEqual(s['program'], 3)           # w XML nr="2" - liczone od zera
        self.assertEqual(s['pumps'], {'co': False, 'kol': False})
        self.assertEqual(s['sensors'], {'pwr': False, 'hp': False, 'lp': False})
        self.assertEqual(s['tariff'], 'niska')
        self.assertEqual(s['power_w'], 0)
        self.assertEqual(s['heating_left_s'], 0)
        self.assertEqual(s['energy_kwh'], {'niska': 30887.591, 'wysoka': 1088.216, 'razem': 31975.807})
        self.assertEqual((s['co_on'], s['cwu_on']), (True, False))

    def test_power_minus_one_means_no_measurement(self):
        # sterownik wysyła -1, gdy brak impulsów licznika energii (pompa stoi) - to nie jest moc
        s = pompa.parse_status(STATUS.replace('<moc wartosc="0" />', '<moc wartosc="-1" />'))
        self.assertIsNone(s['power_w'])

    def test_status_heating(self):
        s = pompa.parse_status(status_grzanie('01:02:03'))
        self.assertEqual(s['heating_left_s'], 3723)
        self.assertIsNone(s['fault'])

    def test_sensors(self):
        t = pompa.parse_sensors(CZUJNIKI)
        self.assertEqual([x['funkcja'] for x in t], ['zco', 'pco', 'zko', 'pko', 'par'])  # kolejność wyświetlania
        self.assertEqual(t[0], {'funkcja': 'zco', 'nazwa': 'Zasilanie CO', 't': 19.3, 'tmin': 19.6, 'tmax': 20.3})

    def test_program(self):
        p = pompa.parse_program(PROGRAM_4)
        self.assertEqual(p['opis'], '8h')
        self.assertEqual(p['akcje'], [
            'codziennie 03:30–06:00 grzanie, powrót CO do 24,0 °C',      # czas ujemny: grzanie DO godziny akcji
            'codziennie 06:10 pompy: kolektor 5 min, CO 5 min',
            'codziennie 10:00–13:00 grzanie, powrót CO do 24,0 °C',
            'codziennie 13:10 pompy: kolektor 5 min, CO 5 min',
            'codziennie 22:00–00:30 grzanie, powrót CO do 24,0 °C',
            'codziennie 00:40 pompy: kolektor 5 min, CO 5 min',
        ])

    def test_program_other_lines(self):
        text = ('Opis ................. specjal 24\n'
                'AK. 1: Grzanie codziennie 08:21 pco= 24.0 zew=      czas=  0min \n'
                'AK. 2: Cos innego 12:00 x=1\n')
        self.assertEqual(pompa.parse_program(text)['akcje'],
                         ['codziennie od 08:21 grzanie do temperatury, powrót CO 24,0 °C', 'Cos innego 12:00 x=1'])

    def test_program_list(self):
        lst = pompa.parse_program_list(LISTA)
        self.assertEqual(lst[0], {'nr': 1, 'opis': '6h', 'aktywny': False})
        self.assertEqual([p['nr'] for p in lst], list(range(1, 17)))       # 5-16 puste sloty
        self.assertTrue(lst[3]['aktywny'])

    def test_actions_collapsed(self):
        a = pompa.parse_actions(AKCJE)
        self.assertEqual(a[0], {'data': '09/18', 'od': '10:00', 'do': '10:00', 'program': '4', 'akcja': '3', 'ile': 1})
        run = next(x for x in a if x['ile'] > 1)
        self.assertEqual((run['od'], run['do'], run['program'], run['akcja']), ('01:17', '03:20', '4', '1'))
        self.assertEqual(run['ile'], 124)
        self.assertEqual([(x['od'], x['program'], x['akcja']) for x in a[1:4]],
                         [('08:21', 'S', '1'), ('06:10', '4', '2'), ('06:00', '4', '1')])

    def test_kotek_error_detected(self):
        with self.assertRaises(pompa.KotekError):
            pompa.check_output('ERROR(  kotustmain.c/  553) Brak powierdzenia na wyslane polecenia\n')


class ScheduleTest(unittest.TestCase):
    # status z programem 4 (jak w nagranym harmonogramie i dzienniku akcji), zegar sterownika 13:03:57
    def setUp(self):
        self.kotek = FakeKotek()
        self.kotek.status = STATUS.replace('nr="2" opis="bez grzania"', 'nr="3" opis="8h"')
        self.now = time.mktime((2026, 9, 18, 14, 5, 0, 0, 0, -1))
        self.hp = pompa.HeatPump(self.kotek, tempfile.mkdtemp(), clock=lambda: self.now, sleep=lambda s: None)
        self.hp.poll(full=True)

    def test_items_times(self):
        items = pompa.parse_program(PROGRAM_4)['items']
        self.assertEqual([(i['nr'], i['start'], i['end']) for i in items],
                         [(1, '03:30', '06:00'), (2, '06:10', '06:15'), (3, '10:00', '13:00'),
                          (4, '13:10', '13:15'), (5, '22:00', '00:30'), (6, '00:40', '00:45')])

    def test_schedule_status(self):
        sch = {i['nr']: i for i in self.hp.snapshot()['schedule']}
        self.assertEqual(sch[1]['status'], 'done')
        self.assertEqual(sch[1]['done_at'], '06:00')
        self.assertEqual(sch[2]['status'], 'done')
        self.assertEqual(sch[3]['status'], 'done')
        self.assertEqual(sch[3]['done_at'], '10:00')
        self.assertEqual(sch[4]['status'], 'next')
        self.assertEqual(sch[4]['in_min'], 6)            # 13:10 - 13:03:57
        self.assertEqual(sch[5]['status'], 'later')
        self.assertEqual(sch[6]['status'], 'unknown')    # 00:40 - dziennik sterownika zaczyna się później

    def test_program_changed_today_not_missed(self):
        # program 3 wgrany po 10:00 - dziś nic nie wykonywał, więc 10:00 nie jest "nie wykonano"; następne jutro
        items = pompa.parse_program('Opis ... x\nAK. 1: Pompy   codziennie 10:00 CZ.KOL="15" CZ.CO="15"\n')['items']
        rows = [('09/18', '10:00', '4', '3'), ('09/18', '06:00', '4', '1')]
        import datetime
        now = datetime.datetime(2026, 9, 18, 13, 51, 44)
        sch = pompa.build_schedule(items, rows, 3, now, -62)
        self.assertEqual(sch[0]['status'], 'unknown')
        self.assertEqual(sch[0]['tomorrow_in_min'], (24 * 60 - (13 * 60 + 51)) + 10 * 60 - 1)
        self.assertEqual(pompa.build_schedule(items, rows + [('09/18', '11:00', '3', '9')], 3, now, 0)[0]['status'],
                         'missed')

    def test_schedule_now(self):
        self.now += 7 * 60                                # zegar sterownika ~13:11 - w oknie pomp 13:10-13:15
        sch = {i['nr']: i for i in self.hp.snapshot()['schedule']}
        self.assertEqual(sch[4]['status'], 'now')
        self.assertEqual(sch[5]['status'], 'next')

    def test_actions_described(self):
        # "program 4, akcja 3" zamienione na opis zadania z treści programu
        a = self.hp.snapshot()['actions']
        self.assertEqual(a[0], {'kiedy': 'dziś 10:00', 'opis': 'grzanie 10:00–13:00, powrót CO do 24,0 °C',
                                'program': '4 · 8h', 'ile': 1})
        self.assertEqual(a[1]['opis'], 'zadanie nr 1 — już usunięte z programu')
        self.assertEqual(a[1]['program'], 'specjalny (S) · brak')
        self.assertEqual(a[2]['opis'], 'pompy: kolektor 5 min, CO 5 min')
        run = next(x for x in a if x['ile'] > 1)
        self.assertEqual((run['kiedy'], run['ile']), ('dziś 01:17–03:20', 124))
        self.assertIn(['czytajprogram', 'S'], [strip_opts(c) for c in self.kotek.calls])

    def test_activity(self):
        self.assertEqual(self.hp.snapshot()['activity'], 'Awaria: Presostaty lub PWR')
        self.kotek.status = status_grzanie('00:47:12').replace('<pompa id="co"  stan="0"/>', '<pompa id="co"  stan="1"/>')
        self.hp.poll()
        self.assertEqual(self.hp.snapshot()['activity'], 'Grzanie, pracuje pompa CO')
        self.kotek.status = STATUS.replace('nazwa="AWARIA"', 'nazwa="CZEKA"').replace(
            '<pompa id="kol"  stan="0"/>', '<pompa id="kol"  stan="1"/>')
        self.hp.poll()
        self.assertEqual(self.hp.snapshot()['activity'], 'Pracuje pompa kolektora')
        self.kotek.status = STATUS.replace('nazwa="AWARIA"', 'nazwa="CZEKA"').replace('opis="Awaria           "', 'opis="Oczekiwanie"')
        self.hp.poll()
        self.assertEqual(self.hp.snapshot()['activity'], 'Spoczynek')


class ManualProgramTest(unittest.TestCase):
    def test_program_s_day_of_week(self):
        xml, start = pompa.manual_heating_program('2026/09/18', '13:03:57', 60)     # piątek
        self.assertEqual(start, '2026/09/18 13:05')      # sekundy >= 45 -> +2 min
        self.assertIn('<program numer="S"', xml)
        self.assertIn('<akcja dni="PI" czas="13:05"><grzanie czas="60"/></akcja>', xml)
        self.assertNotIn('data=', xml)                   # kotek psuje rok 2016-2031

    def test_program_s_early_seconds(self):
        self.assertEqual(pompa.manual_heating_program('2026/09/18', '13:03:10', 30)[1], '2026/09/18 13:04')

    def test_program_s_over_midnight(self):
        xml, start = pompa.manual_heating_program('2026/09/20', '23:59:50', 90)   # niedziela -> poniedziałek
        self.assertEqual(start, '2026/09/21 00:01')
        self.assertIn('dni="PN" czas="00:01"', xml)

    def test_check_saved_program(self):
        text = 'AK. 1: Grzanie ..S....    11:02 pco=      zew=      czas= 60min \r\n'
        pompa.check_manual_program(text, '2026/09/23 11:02')
        pompa.check_manual_program(text.replace('11:02', ' 9:02'), '2026/09/23 09:02')

    def test_check_saved_program_wrong(self):
        with self.assertRaisesRegex(pompa.KotekError, r'\.\.\.C\.\.\. 11:02 zamiast SR 11:02'):
            pompa.check_manual_program('AK. 1: Grzanie ...C...    11:02 pco= zew= czas= 60min\n', '2026/09/23 11:02')
        with self.assertRaises(pompa.KotekError):         # inna godzina
            pompa.check_manual_program('AK. 1: Grzanie ..S....    11:03 pco= zew= czas= 60min\n', '2026/09/23 11:02')
        with self.assertRaises(pompa.KotekError):         # "codziennie" - po odrzuconej dacie
            pompa.check_manual_program('AK. 1: Grzanie codziennie 00:00 pco= zew= czas= 60min\n', '2026/09/23 11:02')
        with self.assertRaises(pompa.KotekError):
            pompa.check_manual_program('Program nr ........... 17\n', '2026/09/23 11:02')


class HeatPumpTest(unittest.TestCase):
    def setUp(self):
        self.kotek = FakeKotek()
        self.tmp = tempfile.mkdtemp()
        self.now = time.mktime((2026, 9, 18, 14, 5, 0, 0, 0, -1))
        self.hp = pompa.HeatPump(self.kotek, self.tmp, clock=lambda: self.now, sleep=lambda s: None)

    def cmds(self):
        return [strip_opts(c) for c in self.kotek.calls]

    def test_snapshot(self):
        self.assertIsNone(self.hp.snapshot())
        self.hp.poll(full=True)
        s = self.hp.snapshot()
        self.assertTrue(s['ok'])
        self.assertEqual(s['state'], 'AWARIA')
        self.assertEqual(s['program']['nr'], 3)
        self.assertEqual([p['nr'] for p in s['programs']], [1, 2, 3, 4])
        self.assertEqual(len(s['temps']), 5)
        self.assertEqual(s['clock_diff_min'], -61)          # 13:03:57 wobec 14:05:00
        self.assertEqual(s['manual'], {'pumps_co_until': None, 'pumps_kol_until': None,
                                       'heating_start': None, 'heating_start_ts': None, 'heating_until': None})

    def test_connection_lost(self):
        self.hp.poll(full=True)
        self.kotek.fail = True
        self.hp.poll()
        s = self.hp.snapshot()
        self.assertFalse(s['ok'])
        self.assertIn('Brak', s['error'])

    def test_set_program(self):
        self.hp.poll(full=True)
        self.hp.set_program(4)
        self.assertIn(['wlaczprogram', '4'], self.cmds())
        self.assertIn(['aktprogram'], self.cmds())

    def test_set_program_validation(self):
        for bad in (0, 5, '2', None, 3.5):
            with self.assertRaises(ValueError):
                self.hp.set_program(bad)
        self.assertNotIn('wlaczprogram', [c[0] for c in self.cmds()])

    def test_set_program_not_confirmed(self):
        self.kotek.active = 3
        orig = self.kotek.__call__
        self.hp.runner = lambda args: '' if 'wlaczprogram' in args else orig(args)
        with self.assertRaises(pompa.KotekError):
            self.hp.set_program(1)

    def test_pumps(self):
        self.hp.poll(full=True)
        self.hp.pumps(co_min=15, kol_min=0)
        self.assertIn(['samepompy', '0', '15'], self.cmds())    # samepompy <kolektor> <CO>
        m = self.hp.snapshot()['manual']
        self.assertEqual(m['pumps_co_until'], int(self.now + 15 * 60))
        self.assertIsNone(m['pumps_kol_until'])

    def test_pumps_both_and_persisted(self):
        self.hp.pumps(co_min=20, kol_min=20)
        self.assertIn(['samepompy', '20', '20'], self.cmds())
        hp2 = pompa.HeatPump(self.kotek, self.tmp, clock=lambda: self.now, sleep=lambda s: None)
        hp2.poll(full=True)
        self.assertEqual(hp2.snapshot()['manual']['pumps_kol_until'], int(self.now + 20 * 60))

    def test_pumps_validation(self):
        for co, kol in ((0, 0), (121, 0), (-1, 5), (15.5, 0), ('15', 0), (True, 0)):
            with self.assertRaises(ValueError):
                self.hp.pumps(co_min=co, kol_min=kol)
        self.assertNotIn('samepompy', [c[0] for c in self.cmds()])

    def test_stop_pumps(self):
        self.hp.pumps(co_min=15, kol_min=15)
        self.hp.stop_pumps()
        self.assertEqual([c for c in self.cmds() if c[0] == 'samepompy'][-1], ['samepompy', '0', '0'])
        self.hp.poll(full=True)
        m = self.hp.snapshot()['manual']
        self.assertIsNone(m['pumps_co_until'])
        self.assertIsNone(m['pumps_kol_until'])

    def test_expired_pumps_cleared(self):
        self.hp.pumps(co_min=1, kol_min=0)
        self.now += 120
        self.hp.poll(full=True)
        self.assertIsNone(self.hp.snapshot()['manual']['pumps_co_until'])

    def test_manual_heating(self):
        self.hp.poll(full=True)
        self.hp.manual_heating(1)
        self.assertEqual(len(self.kotek.program_files), 1)
        self.assertIn('<akcja dni="PI" czas="13:05"><grzanie czas="60"/></akcja>', self.kotek.program_files[0])
        m = self.hp.snapshot()['manual']
        self.assertEqual(m['heating_start'], '13:05')
        # start za ~63 s wg zegara sterownika (13:03:57 -> 13:05:00), koniec godzinę później
        self.assertEqual(m['heating_start_ts'], int(self.now + 63))
        self.assertEqual(m['heating_until'], int(self.now + 63 + 3600))

    def test_manual_heating_program_s_cleared_after_end(self):
        # akcja z dniem tygodnia - po końcu grzania S wyczyszczony, żeby nie grzało za tydzień
        self.hp.poll(full=True)
        self.hp.manual_heating(1)
        self.now += 30 * 60
        self.hp.poll()
        self.assertIn('AK.', self.kotek.program_s)          # w trakcie grzania S zostaje
        self.now += 40 * 60
        self.hp.poll()
        self.assertNotIn('AK.', self.kotek.program_s)
        self.assertIsNone(self.hp.snapshot()['manual']['heating_until'])

    def test_manual_heating_clear_retried(self):
        # brak łączności przy końcu grzania - stan zostaje, czyszczenie przy kolejnym odczycie
        self.hp.poll(full=True)
        self.hp.manual_heating(1)
        self.now += 2 * 3600
        self.kotek.fail = True
        self.hp.poll()
        self.assertIsNotNone(self.hp.manual['heating_until'])
        self.kotek.fail = False
        self.hp.poll()
        self.assertNotIn('AK.', self.kotek.program_s)
        self.assertIsNone(self.hp.manual['heating_until'])

    def test_manual_heating_not_saved(self):
        # kotek zapisał akcję inaczej (np. "codziennie") - błąd, program S wyczyszczony, bez udawania grzania
        self.kotek.saved_days = 'codziennie'
        self.hp.poll(full=True)
        with self.assertRaisesRegex(pompa.KotekError, 'pompa nie ruszy'):
            self.hp.manual_heating(1)
        self.assertIn('numer="S" opis="brak"', self.kotek.program_files[-1])
        self.assertNotIn('AK.', self.kotek.program_s)
        self.assertIsNone(self.hp.snapshot()['manual']['heating_until'])

    def test_manual_heating_validation(self):
        self.hp.poll(full=True)
        for bad in (0, 0.25, 8.5, '1', None):
            with self.assertRaises(ValueError):
                self.hp.manual_heating(bad)
        self.assertEqual(self.kotek.program_files, [])

    def test_manual_heating_needs_status(self):
        with self.assertRaises(pompa.KotekError):
            self.hp.manual_heating(1)                     # brak odczytu czasu sterownika

    def test_only_allowed_commands(self):
        self.hp.poll(full=True)
        self.hp.set_program(2)
        self.hp.pumps(co_min=5, kol_min=5)
        self.hp.stop_pumps()
        self.hp.manual_heating(0.5)
        allowed = {'status', 'odczytczujnikow', 'czytajprogram', 'listaprogramow', 'wykonaneakcje',
                   'aktprogram', 'wlaczprogram', 'samepompy', 'program'}
        self.assertTrue({c[0] for c in self.cmds()} <= allowed)
        self.assertEqual(pompa.kotek_args(['status']), ['--adres', '192.168.1.31', 'status'])


if __name__ == '__main__':
    unittest.main()
