#!/usr/bin/python3
# -*- coding: utf-8 -*-
# panel WWW do włączania/wyłączania świateł z telefonu. Opis: docs/panel-www.md

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import dzarwis_global_vars as dgv
import energia
from lights_v2_ import ModbusError, MODBUS_TIMEOUT, read_registers
from pyModbusTCP.client import ModbusClient

# kolejność i nazwy na stronie: (nazwa wyjścia z dgv.PLC.Douts, nazwa wyświetlana)
SWIATLA = [
    ('swiatlo wiatrolap', 'Wiatrołap'),
    ('swiatlo hol', 'Hol'),
    ('swiatlo kuchnia', 'Kuchnia'),
    ('swiatlo jadalnia', 'Jadalnia'),
    ('swiatlo salon', 'Salon'),
    ('swiatlo salon kinkiety', 'Salon – kinkiety'),
    ('swiatlo spizarnia', 'Spiżarnia'),
    ('swiatlo pralnia', 'Pralnia'),
    ('swiatlo lazienka', 'Łazienka'),
    ('swiatlo biuro', 'Biuro'),
    ('swiatlo nad schodami', 'Nad schodami'),
    ('swiatlo przejscie', 'Przejście'),
    ('swiatlo lazienka gora', 'Łazienka góra'),
    ('swiatlo sypialnia', 'Sypialnia'),
    ('swiatlo Natka', 'Natka'),
    ('swiatlo Natka 2', 'Natka 2'),
    ('swiatlo Ola', 'Ola'),
    ('swiatlo Pawel', 'Paweł'),
]

PORT = int(os.environ.get('DZARWIS_WEB_PORT', 80))
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
# minutowe pomiary energii (poza repozytorium - .gitignore)
ENERGY_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'energia.db')

# jedyne pliki, które serwer wydaje: ścieżka URL -> (plik w WEB_DIR, typ)
STATIC = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/index.html': ('index.html', 'text/html; charset=utf-8'),
    '/manifest.json': ('manifest.json', 'application/manifest+json'),
    '/icon-192.png': ('icon-192.png', 'image/png'),
    '/icon-512.png': ('icon-512.png', 'image/png'),
}

log = logging.getLogger('web')


class Panel:
    # stan i sterowanie światłami z listy SWIATLA; jedno połączenie Modbus dla wszystkich wątków
    def __init__(self, mb):
        self.mb = mb
        self.lock = threading.Lock()
        douts = {o.nazwa: o for o in dgv.PLC.Douts}
        # nazwa -> (rejestr, bit)
        self.addr = {}
        for light_id, _ in SWIATLA:
            o = douts[light_id]
            self.addr[light_id] = (dgv.PLC.out_start_reg + o.out_num_sw // 16, o.out_num_sw % 16)
        self.first_reg = min(reg for reg, _ in self.addr.values())
        self.reg_count = max(reg for reg, _ in self.addr.values()) - self.first_reg + 1

    def _modbus(self, fn, *args):
        # po błędzie zamknij połączenie - następne żądanie otworzy nowe
        with self.lock:
            try:
                return fn(*args)
            except ModbusError:
                self.mb.close()
                raise

    def _write(self, reg, value):
        if not self.mb.write_single_register(reg, value):
            raise ModbusError(f'zapis rejestru {reg} nieudany (kod błędu {self.mb.last_error})')

    def _lights(self):
        regs = read_registers(self.mb, self.first_reg, self.reg_count)
        return [{'id': light_id, 'label': label,
                 'on': bool(regs[self.addr[light_id][0] - self.first_reg] >> self.addr[light_id][1] & 1)}
                for light_id, label in SWIATLA]

    def _set_light(self, light_id, on):
        reg, bit = self.addr[light_id]
        value = read_registers(self.mb, reg, 1)[0]
        new_value = value | (1 << bit) if on else value & ~(1 << bit)
        if new_value != value:
            self._write(reg, new_value)

    def _all_off(self):
        masks = {}
        for reg, bit in self.addr.values():
            masks[reg] = masks.get(reg, 0) | (1 << bit)
        for reg, mask in sorted(masks.items()):
            value = read_registers(self.mb, reg, 1)[0]
            if value & mask:
                self._write(reg, value & ~mask)

    def lights(self):
        return self._modbus(self._lights)

    def set_light(self, light_id, on):
        if light_id not in self.addr:
            raise KeyError(light_id)
        self._modbus(self._set_light, light_id, on)

    def all_off(self):
        self._modbus(self._all_off)


def make_handler(panel, web_dir, energy=None):
    # energy: energia.Collector albo None (zakładka PV wyłączona)
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body, ctype):
            self.send_response(status)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, data):
            self._send(status, json.dumps(data, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')

        def _api(self, action):
            try:
                action()
                self._json(200, {'lights': panel.lights()})
            except ValueError as e:
                self._json(400, {'error': str(e)})
            except ModbusError as e:
                log.error('WAGO: %s', e)
                self._json(503, {'error': 'Brak połączenia ze sterownikiem'})
            except Exception:
                log.exception('nieobsłużony błąd')
                self._json(500, {'error': 'Błąd serwera'})

        def _pv(self, data):
            if data is None:
                self._json(503, {'error': 'Brak danych z licznika i falownika'})
            else:
                self._json(200, data)

        def do_GET(self):
            if self.path == '/api/lights':
                self._api(lambda: None)
            elif self.path == '/api/pv':
                self._pv(energy.snapshot() if energy else None)
            elif self.path == '/api/pv/day':
                self._pv(energy.day() if energy else None)
            elif self.path in STATIC:
                name, ctype = STATIC[self.path]
                with open(os.path.join(web_dir, name), 'rb') as f:
                    self._send(200, f.read(), ctype)
            else:
                self._json(404, {'error': 'Nie znaleziono'})

        def do_POST(self):
            length = int(self.headers.get('Content-Length') or 0)
            raw = self.rfile.read(length)
            if self.path == '/api/lights':
                self._api(lambda: self._set_light(raw))
            elif self.path == '/api/lights/all-off':
                log.info('%s: wyłącz wszystko', self.client_address[0])
                self._api(panel.all_off)
            else:
                self._json(404, {'error': 'Nie znaleziono'})

        def _set_light(self, raw):
            try:
                req = json.loads(raw.decode('utf-8'))
                light_id, on = req['id'], req['on']
            except (ValueError, KeyError, TypeError):
                raise ValueError('oczekiwano {"id": ..., "on": true/false}')
            if not isinstance(on, bool):
                raise ValueError('"on" musi być true albo false')
            try:
                panel.set_light(light_id, on)
            except KeyError:
                raise ValueError(f'nieznany obwód: {light_id}')
            log.info('%s: %s -> %s', self.client_address[0], light_id, 'włącz' if on else 'wyłącz')

        def log_message(self, fmt, *args):
            # odświeżanie co 2 s zaśmiecałoby dziennik - żądania tylko na poziomie DEBUG
            log.debug('%s %s', self.client_address[0], fmt % args)

    return Handler


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    mb = ModbusClient(host=dgv.PLC.ip, unit_id=dgv.PLC.uid, port=dgv.PLC.port,
                      auto_open=True, auto_close=False, timeout=MODBUS_TIMEOUT)
    gateway = ModbusClient(host=energia.GATEWAY_IP, port=energia.GATEWAY_PORT,
                           auto_open=True, auto_close=False, timeout=energia.MODBUS_TIMEOUT)
    collector = energia.Collector(gateway, energia.EnergyStore(ENERGY_DB))
    collector.start()
    server = ThreadingHTTPServer(('', PORT), make_handler(Panel(mb), WEB_DIR, collector))
    log.info('panel WWW na porcie %s, WAGO %s:%s, energia %s', PORT, dgv.PLC.ip, dgv.PLC.port, energia.GATEWAY_IP)
    server.serve_forever()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted')
