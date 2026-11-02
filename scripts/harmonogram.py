#!/usr/bin/python3
# -*- coding: utf-8 -*-
# harmonogram świateł: zdarzenia o stałej godzinie w wybrane dni tygodnia. Opis: docs/panel-www.md

import datetime
import json
import logging
import os
import re
import threading
import time
import uuid

TICK_S = 5                  # co ile sprawdzać zegar; musi być dużo krótsze od minuty
RETRY_S = 30                # odstęp między próbami, gdy WAGO nie odpowiada
GIVE_UP_S = 5 * 60          # po tylu sekundach od wyznaczonej chwili zdarzenie przepada
ALL = 'all'
ALL_LABEL = 'Wszystkie'

TIME_RE = re.compile(r'([01][0-9]|2[0-3]):[0-5][0-9]')

log = logging.getLogger('web')


class Scheduler:
    # panel: obiekt z set_light(id, on), all_on(), all_off(); lights: lista (id, nazwa wyświetlana)
    def __init__(self, panel, lights, path, clock=datetime.datetime.now):
        self.panel = panel
        self.labels = dict(lights)
        self.lights = [{'id': i, 'label': label} for i, label in lights]
        self.path = path
        self.clock = clock
        self.lock = threading.Lock()    # chroni self.events (wątek harmonogramu i żądania HTTP)
        self.events = self._load()
        self.fired = {}                 # id -> (data, godzina) ostatniego uruchomienia; drugi raz nie w tej samej dobie
        self.queue = []                 # zdarzenia do wykonania, po kolei; używa tylko tick()
        self.retry_at = None

    # --- walidacja i zapis ---
    def _clean(self, req, base=None):
        e = dict(base or {'enabled': True})
        e.update((k, req[k]) for k in ('time', 'on', 'target', 'days', 'enabled') if k in req)
        if e.get('time') == '24:00':
            e['time'] = '00:00'
        if not isinstance(e.get('time'), str) or not TIME_RE.fullmatch(e['time']):
            raise ValueError('niepoprawna godzina')
        if not isinstance(e.get('on'), bool):
            raise ValueError('"on" musi być true albo false')
        if not isinstance(e.get('target'), str) or (e['target'] != ALL and e['target'] not in self.labels):
            raise ValueError('nieznany obwód')
        days = e.get('days')
        if not isinstance(days, list) or not days:
            raise ValueError('wybierz co najmniej jeden dzień')
        if not all(type(d) is int and 0 <= d <= 6 for d in days):
            raise ValueError('niepoprawny dzień tygodnia')
        e['days'] = sorted(set(days))
        if not isinstance(e['enabled'], bool):
            raise ValueError('"enabled" musi być true albo false')
        return e

    def _load(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                items = json.load(f)['events']
            if not isinstance(items, list):
                raise ValueError('events nie jest listą')
        except OSError:
            return []
        except (ValueError, KeyError, TypeError) as e:
            # odłóż na bok, żeby następny zapis nie zniszczył jedynej kopii
            log.error('harmonogram: uszkodzony plik %s (%s), zachowany jako .zly', self.path, e)
            os.replace(self.path, self.path + '.zly')
            return []
        events = []
        for item in items:
            try:
                events.append(dict(self._clean(item), id=item['id']))
            except (ValueError, KeyError, TypeError) as e:
                log.error('harmonogram: pomijam zdarzenie %s: %s', item, e)
        return events

    def _save(self, events):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'events': events}, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def _find(self, event_id):
        return next((e for e in self.events if e['id'] == event_id), None)

    # --- zmiany z panelu ---
    def add(self, req):
        event = dict(self._clean(req), id=uuid.uuid4().hex)
        with self.lock:
            self._save(self.events + [event])
            self.events = self.events + [event]
        return event

    def update(self, event_id, req):
        with self.lock:
            old = self._find(event_id)
            if old is None:
                raise ValueError('nie ma takiego zdarzenia')
            new = self._clean(req, old)
            events = [new if e is old else e for e in self.events]
            self._save(events)
            self.events = events
        return new

    def delete(self, event_id):
        with self.lock:
            if self._find(event_id) is None:
                raise ValueError('nie ma takiego zdarzenia')
            events = [e for e in self.events if e['id'] != event_id]
            self._save(events)
            self.events = events

    # --- odczyt dla strony ---
    def _label(self, event):
        return ALL_LABEL if event['target'] == ALL else self.labels[event['target']]

    def _next(self, now):
        # najbliższe uruchomienie po bieżącej minucie (d = 7: ten sam dzień tygodnia za tydzień)
        today = now.date()
        minute = now.strftime('%H:%M')
        best = None
        for e in self.events:
            if not e['enabled']:
                continue
            for d in range(8):
                day = today + datetime.timedelta(days=d)
                if day.weekday() in e['days'] and (d > 0 or e['time'] > minute):
                    if best is None or (d, e['time']) < (best['in_days'], best['time']):
                        best = dict(e, label=self._label(e), in_days=d, weekday=day.weekday())
                    break
        return best

    def snapshot(self):
        now = self.clock()
        with self.lock:
            events = [dict(e, label=self._label(e)) for e in sorted(self.events, key=lambda e: e['time'])]
            return {'events': events, 'lights': self.lights, 'next': self._next(now)}

    # --- wykonywanie ---
    def _describe(self, e):
        return '%s %s -> %s' % (e['time'], self._label(e), 'włącz' if e['on'] else 'wyłącz')

    def _run_action(self, e):
        if e['target'] != ALL:
            self.panel.set_light(e['target'], e['on'])
        elif e['on']:
            self.panel.all_on()
        else:
            self.panel.all_off()

    def _queue_due(self, now):
        minute = now.strftime('%H:%M')
        date = now.date()
        with self.lock:
            for e in self.events:
                # wpis (data, godzina) chroni przed powtórką w tej samej minucie i po cofnięciu zegara jesienią;
                # zmiana godziny zdarzenia na później tego samego dnia nadal zadziała
                if (e['enabled'] and e['time'] == minute and date.weekday() in e['days']
                        and self.fired.get(e['id']) != (date, minute)):
                    self.fired[e['id']] = (date, minute)
                    self.queue.append((e['id'], now + datetime.timedelta(seconds=GIVE_UP_S)))

    def tick(self):
        # bez nadrabiania: zdarzenie uruchamia się tylko w swojej minucie, ponawianie dotyczy tylko tych już zakolejkowanych
        now = self.clock()
        self._queue_due(now)
        if self.retry_at is not None and now < self.retry_at:
            return
        self.retry_at = None
        while self.queue:
            event_id, deadline = self.queue[0]
            with self.lock:
                e = self._find(event_id)
            if e is None or not e['enabled']:
                self.queue.pop(0)
            elif now > deadline:
                log.error('harmonogram: nie wykonano %s - brak łączności z WAGO', self._describe(e))
                self.queue.pop(0)
            else:
                try:
                    self._run_action(e)
                except Exception as err:
                    # kolejność ma znaczenie: późniejsze zdarzenia czekają, aż to się wykona albo przepadnie
                    log.warning('harmonogram: %s nieudane, ponawiam: %s', self._describe(e), err)
                    self.retry_at = now + datetime.timedelta(seconds=RETRY_S)
                    return
                log.info('harmonogram: %s', self._describe(e))
                self.queue.pop(0)

    def run(self):
        while True:
            try:
                self.tick()
            except Exception:
                log.exception('harmonogram: nieobsłużony błąd')
            time.sleep(TICK_S)

    def start(self):
        threading.Thread(target=self.run, name='harmonogram', daemon=True).start()
