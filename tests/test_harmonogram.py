# testy harmonogramu świateł na atrapie panelu i sztucznym zegarze: python3 -m unittest discover -s tests
import datetime
import json
import logging
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import harmonogram  # noqa: E402

LIGHTS = [('swiatlo hol', 'Hol'), ('swiatlo kuchnia', 'Kuchnia')]
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
MONDAY = datetime.datetime(2026, 11, 2, 12, 0, 0)  # poniedziałek


def setUpModule():
    logging.disable(logging.CRITICAL)   # testy celowo wywołują błędy łączności i uszkodzone pliki


def tearDownModule():
    logging.disable(logging.NOTSET)


class FakePanel:
    # zapisuje polecenia; fail = symulowany brak łączności z WAGO
    def __init__(self):
        self.calls = []
        self.fail = False

    def _do(self, call):
        if self.fail:
            raise OSError('brak WAGO')
        self.calls.append(call)

    def set_light(self, light_id, on):
        self._do(('set', light_id, on))

    def all_on(self):
        self._do(('all_on',))

    def all_off(self):
        self._do(('all_off',))


def event(**kw):
    e = {'time': '12:30', 'on': False, 'target': 'all', 'days': ALL_DAYS}
    e.update(kw)
    return e


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, 'data', 'harmonogram.json')
        self.now = MONDAY
        self.panel = FakePanel()
        self.s = self.make()

    def make(self):
        return harmonogram.Scheduler(self.panel, LIGHTS, self.path, clock=lambda: self.now)

    def at(self, hh, mm, ss=0, date=None):
        self.now = datetime.datetime.combine(date or self.now.date(), datetime.time(hh, mm, ss))
        self.s.tick()


class FiringTest(Base):
    def test_all_off_at_its_minute_only(self):
        self.s.add(event(time='12:30'))
        self.at(12, 29, 59)
        self.assertEqual(self.panel.calls, [])
        self.at(12, 30, 0)
        self.assertEqual(self.panel.calls, [('all_off',)])
        self.at(12, 31, 0)
        self.assertEqual(self.panel.calls, [('all_off',)])

    def test_fires_once_within_the_minute(self):
        self.s.add(event(time='12:30'))
        for ss in (0, 5, 10, 55):
            self.at(12, 30, ss)
        self.assertEqual(self.panel.calls, [('all_off',)])

    def test_each_action_goes_to_the_right_command(self):
        self.s.add(event(time='12:30', on=True, target='all'))
        self.s.add(event(time='12:31', on=True, target='swiatlo kuchnia'))
        self.s.add(event(time='12:32', on=False, target='swiatlo hol'))
        self.at(12, 30)
        self.at(12, 31)
        self.at(12, 32)
        self.assertEqual(self.panel.calls, [('all_on',), ('set', 'swiatlo kuchnia', True), ('set', 'swiatlo hol', False)])

    def test_only_on_selected_weekdays(self):
        self.s.add(event(time='12:30', days=[1]))  # wtorek
        self.at(12, 30)  # poniedziałek
        self.assertEqual(self.panel.calls, [])
        self.at(12, 30, date=datetime.date(2026, 11, 3))
        self.assertEqual(len(self.panel.calls), 1)

    def test_midnight_belongs_to_the_new_day(self):
        # zdarzenie na wtorek o 00:00 wykonuje się w nocy z poniedziałku na wtorek, a nie z wtorku na środę
        self.s.add(event(time='00:00', days=[1]))
        self.at(0, 0, date=datetime.date(2026, 11, 3))
        self.assertEqual(len(self.panel.calls), 1)
        self.at(0, 0, date=datetime.date(2026, 11, 4))
        self.assertEqual(len(self.panel.calls), 1)

    def test_repeats_the_next_day(self):
        self.s.add(event(time='12:30'))
        self.at(12, 30)
        self.at(12, 30, date=datetime.date(2026, 11, 3))
        self.assertEqual(len(self.panel.calls), 2)

    def test_disabled_event_does_not_fire(self):
        self.s.add(event(time='12:30', enabled=False))
        self.at(12, 30)
        self.assertEqual(self.panel.calls, [])

    def test_clock_moved_back_does_not_repeat_the_same_day(self):
        # zmiana czasu jesienią: 02:30 zdarza się tej nocy dwa razy
        self.s.add(event(time='02:30'))
        self.at(2, 30)
        self.at(2, 59)
        self.at(2, 30)
        self.assertEqual(len(self.panel.calls), 1)

    def test_moved_to_later_after_firing_fires_again_today(self):
        e = self.s.add(event(time='12:30'))
        self.at(12, 30)
        self.s.update(e['id'], {'time': '12:45'})
        self.at(12, 45)
        self.assertEqual(len(self.panel.calls), 2)

    def test_missed_time_is_not_caught_up_after_restart(self):
        self.s.add(event(time='12:30'))
        self.now = datetime.datetime(2026, 11, 2, 12, 40)
        restarted = self.make()
        restarted.tick()
        self.assertEqual(self.panel.calls, [])


class RetryTest(Base):
    def test_retries_until_wago_returns(self):
        self.s.add(event(time='12:30'))
        self.panel.fail = True
        self.at(12, 30)
        self.panel.fail = False
        self.at(12, 32)
        self.assertEqual(self.panel.calls, [('all_off',)])
        self.at(12, 33)
        self.assertEqual(self.panel.calls, [('all_off',)])

    def test_gives_up_after_five_minutes(self):
        self.s.add(event(time='12:30'))
        self.panel.fail = True
        self.at(12, 30)
        self.at(12, 34)
        self.panel.fail = False
        self.at(12, 35, 1)
        self.assertEqual(self.panel.calls, [])

    def test_still_retries_just_before_the_limit(self):
        self.s.add(event(time='12:30'))
        self.panel.fail = True
        self.at(12, 30)
        self.panel.fail = False
        self.at(12, 34, 59)
        self.assertEqual(self.panel.calls, [('all_off',)])

    def test_waits_between_retries(self):
        attempts = []
        original = self.panel._do

        def counting(call):
            attempts.append(self.now)
            original(call)
        self.panel._do = counting
        self.s.add(event(time='12:30'))
        self.panel.fail = True
        for ss in range(0, 60, 5):
            self.at(12, 30, ss)
        self.assertEqual(len(attempts), 2)  # próba w 0 s i ponowienie po 30 s

    def test_waiting_actions_run_in_order(self):
        # włączenie, które czekało na WAGO, nie może nadpisać późniejszego zgaszenia
        self.s.add(event(time='12:30', on=True, target='swiatlo hol'))
        self.s.add(event(time='12:31', on=False, target='swiatlo hol'))
        self.panel.fail = True
        self.at(12, 30)
        self.at(12, 31)
        self.panel.fail = False
        self.at(12, 32)
        self.assertEqual(self.panel.calls, [('set', 'swiatlo hol', True), ('set', 'swiatlo hol', False)])

    def test_deleted_event_is_not_retried(self):
        e = self.s.add(event(time='12:30'))
        self.panel.fail = True
        self.at(12, 30)
        self.s.delete(e['id'])
        self.panel.fail = False
        self.at(12, 32)
        self.assertEqual(self.panel.calls, [])

    def test_disabled_event_is_not_retried(self):
        e = self.s.add(event(time='12:30'))
        self.panel.fail = True
        self.at(12, 30)
        self.s.update(e['id'], {'enabled': False})
        self.panel.fail = False
        self.at(12, 32)
        self.assertEqual(self.panel.calls, [])


class EditingTest(Base):
    def test_rejects_bad_input(self):
        bad = [
            event(time='25:00'), event(time='12:60'), event(time='7:30'), event(time=None),
            event(on='tak'), event(target='bojler grzanie'),
            event(days=[]), event(days=[7]), event(days=[-1]), event(days='pn'), event(days=[True]),
            event(enabled='tak'),
        ]
        for req in bad:
            with self.subTest(req=req), self.assertRaises(ValueError):
                self.s.add(req)
        self.assertEqual(self.s.snapshot()['events'], [])

    def test_missing_fields_rejected(self):
        for field in ('time', 'on', 'target', 'days'):
            req = event()
            del req[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.s.add(req)

    def test_24_00_is_saved_as_midnight(self):
        self.assertEqual(self.s.add(event(time='24:00'))['time'], '00:00')

    def test_days_are_sorted_without_duplicates(self):
        self.assertEqual(self.s.add(event(days=[4, 0, 4]))['days'], [0, 4])

    def test_new_event_is_enabled_with_unique_id(self):
        a, b = self.s.add(event()), self.s.add(event())
        self.assertTrue(a['enabled'])
        self.assertNotEqual(a['id'], b['id'])

    def test_list_sorted_by_time_with_labels(self):
        self.s.add(event(time='22:00', target='swiatlo kuchnia'))
        self.s.add(event(time='06:30', target='all'))
        events = self.s.snapshot()['events']
        self.assertEqual([e['time'] for e in events], ['06:30', '22:00'])
        self.assertEqual([e['label'] for e in events], ['Wszystkie', 'Kuchnia'])

    def test_update_changes_only_given_fields(self):
        e = self.s.add(event(time='12:30', target='swiatlo hol', days=[1, 2]))
        self.s.update(e['id'], {'enabled': False})
        got = self.s.snapshot()['events'][0]
        self.assertEqual((got['enabled'], got['time'], got['target'], got['days']), (False, '12:30', 'swiatlo hol', [1, 2]))

    def test_update_validates(self):
        e = self.s.add(event(time='12:30'))
        with self.assertRaises(ValueError):
            self.s.update(e['id'], {'time': '99:99'})
        self.assertEqual(self.s.snapshot()['events'][0]['time'], '12:30')

    def test_update_cannot_change_id(self):
        e = self.s.add(event())
        self.s.update(e['id'], {'id': 'inne'})
        self.assertEqual(self.s.snapshot()['events'][0]['id'], e['id'])

    def test_unknown_id_rejected(self):
        with self.assertRaises(ValueError):
            self.s.update('nie ma', {'enabled': False})
        with self.assertRaises(ValueError):
            self.s.delete('nie ma')

    def test_delete(self):
        a = self.s.add(event(time='10:00'))
        self.s.add(event(time='11:00'))
        self.s.delete(a['id'])
        self.assertEqual([e['time'] for e in self.s.snapshot()['events']], ['11:00'])

    def test_snapshot_lists_lights_for_the_form(self):
        self.assertEqual(self.s.snapshot()['lights'],
                         [{'id': 'swiatlo hol', 'label': 'Hol'}, {'id': 'swiatlo kuchnia', 'label': 'Kuchnia'}])


class NextEventTest(Base):
    def next(self):
        return self.s.snapshot()['next']

    def test_none_without_enabled_events(self):
        self.assertIsNone(self.next())
        self.s.add(event(enabled=False))
        self.assertIsNone(self.next())

    def test_later_today(self):
        e = self.s.add(event(time='12:30'))
        self.s.add(event(time='13:00'))
        self.s.add(event(time='11:00'))
        n = self.next()
        self.assertEqual((n['id'], n['time'], n['in_days']), (e['id'], '12:30', 0))

    def test_tomorrow_when_today_has_passed(self):
        self.s.add(event(time='11:00'))
        n = self.next()
        self.assertEqual((n['time'], n['in_days'], n['weekday']), ('11:00', 1, 1))

    def test_next_selected_weekday(self):
        self.s.add(event(time='11:00', days=[4]))  # piątek; dziś poniedziałek
        n = self.next()
        self.assertEqual((n['in_days'], n['weekday']), (4, 4))

    def test_only_todays_weekday_already_passed_means_a_week(self):
        self.s.add(event(time='11:00', days=[0]))
        self.assertEqual(self.next()['in_days'], 7)


class PersistenceTest(Base):
    def test_events_survive_restart_and_still_fire(self):
        e = self.s.add(event(time='12:30', target='swiatlo hol', days=[0]))
        again = self.make()
        self.assertEqual(again.snapshot()['events'][0]['id'], e['id'])
        self.now = datetime.datetime(2026, 11, 2, 12, 30)
        again.tick()
        self.assertEqual(self.panel.calls, [('set', 'swiatlo hol', False)])

    def test_update_and_delete_are_saved(self):
        e = self.s.add(event())
        self.s.update(e['id'], {'time': '08:15'})
        self.assertEqual(self.make().snapshot()['events'][0]['time'], '08:15')
        self.s.delete(e['id'])
        self.assertEqual(self.make().snapshot()['events'], [])

    def test_no_file_means_empty_schedule(self):
        self.assertEqual(self.s.snapshot()['events'], [])

    def test_damaged_file_is_kept_aside(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, 'w') as f:
            f.write('{zepsuty')
        s = self.make()
        self.assertEqual(s.snapshot()['events'], [])
        s.add(event())  # zapis nie może zniszczyć jedynej kopii starych zdarzeń
        with open(self.path + '.zly') as f:
            self.assertEqual(f.read(), '{zepsuty')

    def test_event_for_removed_light_is_skipped_on_load(self):
        os.makedirs(os.path.dirname(self.path))
        good = dict(event(time='10:00'), id='a', enabled=True)
        gone = dict(event(time='11:00', target='swiatlo usuniete'), id='b', enabled=True)
        with open(self.path, 'w') as f:
            json.dump({'events': [good, gone]}, f)
        self.assertEqual([e['id'] for e in self.make().snapshot()['events']], ['a'])

    def test_failed_save_leaves_list_unchanged(self):
        # katalog zamiast pliku - zapis się nie uda
        os.makedirs(self.path)
        s = self.make()
        with self.assertRaises(OSError):
            s.add(event())
        self.assertEqual(s.snapshot()['events'], [])


if __name__ == '__main__':
    unittest.main()
