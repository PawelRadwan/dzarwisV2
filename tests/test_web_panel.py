# testy panelu WWW na symulowanym WAGO: python3 -m unittest discover -s tests
import json
import os
import sys
import threading
import types
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))


class FakeModbusClient:
    # zamiast prawdziwego pyModbusTCP: rejestry w słowniku, błędy włączane flagami
    def __init__(self, **kw):
        self.kw = kw
        self.regs = {i: 0 for i in range(1024)}
        self.fail = False
        self.last_error = 0
        self.writes = []
        self.closes = 0

    def read_holding_registers(self, start, count):
        if self.fail:
            self.last_error = 2
            return None
        return [self.regs[start + i] for i in range(count)]

    def write_single_register(self, reg, value):
        if self.fail:
            self.last_error = 2
            return None
        self.regs[reg] = value
        self.writes.append((reg, value))
        return True

    def close(self):
        self.closes += 1


fake_pkg = types.ModuleType('pyModbusTCP')
fake_client = types.ModuleType('pyModbusTCP.client')
fake_client.ModbusClient = FakeModbusClient
fake_pkg.client = fake_client
sys.modules.setdefault('pyModbusTCP', fake_pkg)
sys.modules.setdefault('pyModbusTCP.client', fake_client)

import dzarwis_global_vars as dgv  # noqa: E402
import web_panel  # noqa: E402


def out(nazwa):
    return next(o for o in dgv.PLC.Douts if o.nazwa == nazwa)


def is_on(mb, nazwa):
    o = out(nazwa)
    return mb.regs[dgv.PLC.out_start_reg + o.out_num_sw // 16] >> (o.out_num_sw % 16) & 1


def turn_on(mb, nazwa):
    o = out(nazwa)
    mb.regs[dgv.PLC.out_start_reg + o.out_num_sw // 16] |= 1 << (o.out_num_sw % 16)


class PanelTest(unittest.TestCase):
    def setUp(self):
        self.mb = FakeModbusClient()
        self.panel = web_panel.Panel(self.mb)

    def test_every_light_exists_in_douts(self):
        names = {o.nazwa for o in dgv.PLC.Douts}
        for light_id, label in web_panel.SWIATLA:
            self.assertIn(light_id, names)
        self.assertEqual(len(web_panel.SWIATLA), 18)
        self.assertEqual(web_panel.SWIATLA[0], ('swiatlo wiatrolap', 'Wiatrołap'))

    def test_lights_reports_state_in_order(self):
        turn_on(self.mb, 'swiatlo kuchnia')
        turn_on(self.mb, 'swiatlo lazienka gora')  # rejestr 513
        lights = self.panel.lights()
        self.assertEqual([l['id'] for l in lights], [i for i, _ in web_panel.SWIATLA])
        on = {l['id'] for l in lights if l['on']}
        self.assertEqual(on, {'swiatlo kuchnia', 'swiatlo lazienka gora'})
        self.assertEqual(lights[2], {'id': 'swiatlo kuchnia', 'label': 'Kuchnia', 'on': True})

    def test_set_light_on_and_off(self):
        self.panel.set_light('swiatlo hol', True)
        self.assertEqual(is_on(self.mb, 'swiatlo hol'), 1)
        self.panel.set_light('swiatlo hol', False)
        self.assertEqual(is_on(self.mb, 'swiatlo hol'), 0)

    def test_set_light_keeps_other_bits(self):
        turn_on(self.mb, 'swiatlo biuro')
        turn_on(self.mb, 'bojler grzanie')
        self.panel.set_light('swiatlo hol', True)
        self.assertEqual(is_on(self.mb, 'swiatlo biuro'), 1)
        self.assertEqual(is_on(self.mb, 'bojler grzanie'), 1)

    def test_no_write_when_state_unchanged(self):
        turn_on(self.mb, 'swiatlo hol')
        self.panel.set_light('swiatlo hol', True)
        self.panel.set_light('swiatlo salon', False)
        self.assertEqual(self.mb.writes, [])

    def test_all_off_only_lights_one_write_per_register(self):
        for name in ('swiatlo kuchnia', 'swiatlo biuro', 'swiatlo lazienka gora', 'bojler grzanie', 'bojler mieszadlo'):
            turn_on(self.mb, name)
        self.panel.all_off()
        self.assertFalse(any(l['on'] for l in self.panel.lights()))
        self.assertEqual(is_on(self.mb, 'bojler grzanie'), 1)
        self.assertEqual(is_on(self.mb, 'bojler mieszadlo'), 1)
        self.assertEqual(sorted(r for r, _ in self.mb.writes), [512, 513])

    def test_unknown_light(self):
        with self.assertRaises(KeyError):
            self.panel.set_light('bojler grzanie', True)

    def test_modbus_failure_raises_and_closes(self):
        self.mb.fail = True
        with self.assertRaises(web_panel.ModbusError):
            self.panel.lights()
        self.assertGreaterEqual(self.mb.closes, 1)


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.mb = FakeModbusClient()
        handler = web_panel.make_handler(web_panel.Panel(self.mb), web_panel.WEB_DIR)
        self.server = web_panel.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = 'http://127.0.0.1:%d' % self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method='POST' if data is not None else 'GET')
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.headers.get('Content-Type'), r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get('Content-Type'), e.read()

    def test_get_lights(self):
        turn_on(self.mb, 'swiatlo salon')
        status, ctype, body = self.request('/api/lights')
        self.assertEqual(status, 200)
        self.assertIn('application/json', ctype)
        lights = json.loads(body)['lights']
        self.assertEqual(len(lights), 18)
        self.assertTrue(next(l for l in lights if l['id'] == 'swiatlo salon')['on'])

    def test_post_light(self):
        status, _, body = self.request('/api/lights', {'id': 'swiatlo kuchnia', 'on': True})
        self.assertEqual(status, 200)
        self.assertEqual(is_on(self.mb, 'swiatlo kuchnia'), 1)
        self.assertTrue(next(l for l in json.loads(body)['lights'] if l['id'] == 'swiatlo kuchnia')['on'])

    def test_post_all_off(self):
        turn_on(self.mb, 'swiatlo kuchnia')
        status, _, body = self.request('/api/lights/all-off', raw=b'')
        self.assertEqual(status, 200)
        self.assertFalse(any(l['on'] for l in json.loads(body)['lights']))

    def test_bad_requests(self):
        self.assertEqual(self.request('/api/lights', {'id': 'nie ma', 'on': True})[0], 400)
        self.assertEqual(self.request('/api/lights', {'id': 'swiatlo hol', 'on': 'tak'})[0], 400)
        self.assertEqual(self.request('/api/lights', raw=b'{zly json')[0], 400)
        self.assertEqual(self.mb.writes, [])

    def test_wago_unavailable(self):
        self.mb.fail = True
        status, _, body = self.request('/api/lights')
        self.assertEqual(status, 503)
        self.assertIn('error', json.loads(body))
        self.assertEqual(self.request('/api/lights', {'id': 'swiatlo hol', 'on': True})[0], 503)

    def test_static_files(self):
        status, ctype, body = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn('text/html', ctype)
        self.assertIn(b'<html', body)
        status, ctype, _ = self.request('/manifest.json')
        self.assertEqual(status, 200)
        self.assertEqual(self.request('/icon-192.png')[1], 'image/png')

    def test_not_found(self):
        for path in ('/../lights_v2_.py', '/lights_v2_.py', '/api/nic', '/web_panel.py'):
            self.assertEqual(self.request(path)[0], 404, path)


if __name__ == '__main__':
    unittest.main()
