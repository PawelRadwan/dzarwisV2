#!/usr/bin/python
# -*- coding: utf-8 -*-
# obsługa przycisków oświetlenia: puszczenie przycisku (zbocze 1 -> 0 na wejściu WAGO)
# przełącza przypisaną lampę. Opis: docs/skrypty.md, mapa wejść: docs/mapa-io.md

import logging
import time
import dzarwis_global_vars as dgv
from pyModbusTCP.client import ModbusClient

# (rejestr wejść, bit) -> nazwa wyjścia z dgv.PLC.Douts
PRZYCISKI = {
    (0, 0): 'swiatlo lazienka',
    (0, 1): 'swiatlo biuro',
    (0, 2): 'swiatlo kuchnia',
    (0, 3): 'swiatlo salon kinkiety',
    (0, 4): 'swiatlo wiatrolap',
    (0, 5): 'swiatlo jadalnia',
    (0, 6): 'swiatlo nad schodami',
    (0, 7): 'swiatlo hol',
    (0, 8): 'swiatlo Ola',
    (0, 9): 'swiatlo Pawel',
    (0, 10): 'swiatlo Natka',
    (0, 11): 'swiatlo Natka 2',
    (0, 12): 'swiatlo pralnia',
    (0, 13): 'swiatlo sypialnia',
    (1, 0): 'swiatlo salon',
    (1, 1): 'swiatlo przejscie',
    (1, 2): 'swiatlo spizarnia',
    (1, 3): 'swiatlo lazienka gora',
}

# wejścia wago są dostępne na holdingach od rejestru 0
IN_START_REG = 0
IN_REG_COUNT = 4

POLL_INTERVAL = 0.05    # s, okres odpytywania wejść
ERROR_DELAY = 1         # s, przerwa po błędzie komunikacji
MODBUS_TIMEOUT = 2      # s, domyślnie pyModbusTCP czeka 30 s

log = logging.getLogger('lights')


class ModbusError(Exception):
    pass


def read_registers(mb, start, count):
    # pyModbusTCP przy błędzie zwraca None zamiast rzucać wyjątek
    regs = mb.read_holding_registers(start, count)
    if regs is None:
        raise ModbusError(f'odczyt rejestrów {start}-{start + count - 1} nieudany (kod błędu {mb.last_error})')
    return regs


def toggle_light(mb, nazwa):
    out = next((o for o in dgv.PLC.Douts if o.nazwa == nazwa), None)
    if out is None:
        log.warning('brak wyjścia o nazwie %r w dgv.PLC.Douts', nazwa)
        return
    # wyjścia wago są dostępne na holdingach od rejestru 512, 16 wyjść na rejestr
    reg_num = dgv.PLC.out_start_reg + out.out_num_sw // 16
    bit = out.out_num_sw % 16
    value = read_registers(mb, reg_num, 1)[0]
    new_value = value ^ (1 << bit)
    if not mb.write_single_register(reg_num, new_value):
        raise ModbusError(f'zapis rejestru {reg_num} nieudany (kod błędu {mb.last_error})')
    log.info('%s: %s', nazwa, 'włączone' if new_value >> bit & 1 else 'wyłączone')


def released_buttons(old_inputs, inputs):
    # pozycje (rejestr, bit), na których wejście zmieniło się z 1 na 0
    for reg, (old, new) in enumerate(zip(old_inputs, inputs)):
        falling = old & ~new
        for bit in range(16):
            if falling >> bit & 1:
                yield reg, bit


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    w_mb = ModbusClient(host=dgv.PLC.ip, unit_id=dgv.PLC.uid, port=dgv.PLC.port,
                        auto_open=True, auto_close=False, timeout=MODBUS_TIMEOUT)
    log.info('start, WAGO %s:%s', dgv.PLC.ip, dgv.PLC.port)
    old_inputs = None
    while True:
        try:
            inputs = read_registers(w_mb, IN_START_REG, IN_REG_COUNT)
            if old_inputs is None:
                log.info('połączenie z WAGO OK')
            else:
                for pos in released_buttons(old_inputs, inputs):
                    if pos in PRZYCISKI:
                        toggle_light(w_mb, PRZYCISKI[pos])
            old_inputs = inputs
        except Exception as e:
            # nie kończ procesu - po odzyskaniu łączności stan wejść jest czytany od nowa,
            # żeby zmiany z czasu przerwy nie przełączyły lamp
            log.error('%s: %s - ponowna próba za %s s', type(e).__name__, e, ERROR_DELAY)
            w_mb.close()
            old_inputs = None
            time.sleep(ERROR_DELAY)
            continue
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted')
