import time
import dzarwis_global_vars as dgv
from pyModbusTCP.client import ModbusClient

def interprate_outputs(ob):
    #print(ob)
    on_optputs_names = []
    index = 0
    for o in ob:
        if o==1:
            for out in dgv.PLC.Douts:
                if index == out.out_num_sw:
                    on_optputs_names.append(out.nazwa)
        index +=1
    return on_optputs_names

def wago_read_outputs(mb):
    # wyjścia wgo są dostępne na holdingach w przestrzni adresowej 512-767
    outputs = []
    start_reg = dgv.PLC.out_start_reg
    lrc = 125
    while lrc > 0:
        outputs.extend(mb.read_holding_registers(start_reg, lrc))
        # print(f'start:{start_reg} ilość  do odczytu:{lrc}')
        start_reg += lrc
        if start_reg + lrc > dgv.PLC.out_stop_reg:
            lrc = dgv.PLC.out_stop_reg - start_reg
    # print(outputs)
    ob = []
    for o in outputs:
        add = list("{0:016b}".format(o))[::-1]
        # print(add)
        ob.extend(add)
    obb = []
    for i in ob:
        obb.append(int(i))

    return (obb)

def wago_set_outputs(mb,outs_sw_nums):
    #print('set')
    current_status = wago_read_outputs(mb)
    #print(current_status)
    set_list = wago_read_outputs(mb)
    for o in outs_sw_nums:
        set_list[o['sw_num']] = o['state']
    i=0
    while i < len(current_status):
        iter=set_list[i:i+16]
        if iter != current_status[i:i+16]:
            #print(iter)
            reg_v = int("".join(str(x) for x in iter[::-1]), 2)
            #print(reg_v)
            reg_num=(dgv.PLC.out_start_reg + int(i/16))
            # print(f'zapisuje wartość {reg_v} od rejestru {reg_num}')
            write = mb.write_single_register(reg_num,reg_v)
            # print(write)
        i += 16


def set_light(w_mb,nazwa,state):
    for o in dgv.PLC.Douts:
        if o.nazwa == nazwa:
            onum = o.out_num_sw
            # print(f'załącz numer wyjścia:{onum}')
            wago_set_outputs(w_mb, [{'sw_num': onum, 'state': state}])


w_mb = ModbusClient(host = dgv.PLC.ip, unit_id=dgv.PLC.uid, port=dgv.PLC.port,auto_open=True,auto_close=True)
old_inputs = inputs = w_mb.read_holding_registers(0, 4)

while True:
    try:
        inputs = w_mb.read_holding_registers(0, 4)
    except:
        print(' mb read error ')
        time.sleep(0.5)
        continue
    for i in range(len(inputs)):
        if inputs[i] != old_inputs[i]:
            new = list(format(inputs[i], '016b'))
            old = list(format(old_inputs[i], '016b'))
            for x in range(len(new)):
                if new[x] != old[x] and old[x] == '1':
                    outs = wago_read_outputs(w_mb)
                    lights = interprate_outputs(outs)
                    if i == 0:
                        if 16 - x == 1:
                            if 'swiatlo lazienka' in lights:
                                set_light(w_mb, 'swiatlo lazienka', 0)
                            else:
                                set_light(w_mb, 'swiatlo lazienka', 1)
                        elif 16 - x == 2:
                            if 'swiatlo biuro' in lights:
                                set_light(w_mb, 'swiatlo biuro', 0)
                            else:
                                set_light(w_mb, 'swiatlo biuro', 1)
                        elif 16 - x == 3:
                            if 'swiatlo kuchnia' in lights:
                                set_light(w_mb, 'swiatlo kuchnia', 0)
                            else:
                                set_light(w_mb, 'swiatlo kuchnia', 1)
                        elif 16 - x == 4:
                            if 'swiatlo salon kinkiety' in lights:
                                set_light(w_mb, 'swiatlo salon kinkiety', 0)
                            else:
                                set_light(w_mb, 'swiatlo salon kinkiety', 1)
                        elif 16 - x == 5:
                            if 'swiatlo wiatrolap' in lights:
                                set_light(w_mb, 'swiatlo wiatrolap', 0)
                            else:
                                set_light(w_mb, 'swiatlo wiatrolap', 1)
                        elif 16 - x == 6:
                            if 'swiatlo jadalnia' in lights:
                                set_light(w_mb, 'swiatlo jadalnia', 0)
                            else:
                                set_light(w_mb, 'swiatlo jadalnia', 1)
                        elif 16 - x == 7:
                            if 'swiatlo nad schodami' in lights:
                                set_light(w_mb, 'swiatlo nad schodami', 0)
                            else:
                                set_light(w_mb, 'swiatlo nad schodami', 1)
                        elif 16 - x == 8:
                            if 'swiatlo hol' in lights:
                                set_light(w_mb, 'swiatlo hol', 0)
                            else:
                                set_light(w_mb, 'swiatlo hol', 1)
                        elif 16 - x == 9:
                            if 'swiatlo Ola' in lights:
                                set_light(w_mb, 'swiatlo Ola', 0)
                            else:
                                set_light(w_mb, 'swiatlo Ola', 1)
                        elif 16 - x == 10:
                            if 'swiatlo Pawel' in lights:
                                set_light(w_mb, 'swiatlo Pawel', 0)
                            else:
                                set_light(w_mb, 'swiatlo Pawel', 1)
                        elif 16 - x == 11:
                            if 'swiatlo Natka' in lights:
                                set_light(w_mb, 'swiatlo Natka', 0)
                            else:
                                set_light(w_mb, 'swiatlo Natka', 1)
                        elif 16 - x == 12:
                            if 'swiatlo Natka 2' in lights:
                                set_light(w_mb, 'swiatlo Natka 2', 0)
                            else:
                                set_light(w_mb, 'swiatlo Natka 2', 1)
                        elif 16 - x == 13:
                            if 'swiatlo pralnia' in lights:
                                set_light(w_mb, 'swiatlo pralnia', 0)
                            else:
                                set_light(w_mb, 'swiatlo pralnia', 1)
                        elif 16 - x == 14:
                            if 'swiatlo sypialnia' in lights:
                                set_light(w_mb, 'swiatlo sypialnia', 0)
                            else:
                                set_light(w_mb, 'swiatlo sypialnia', 1)
                    elif i == 1:
                        if 16 - x == 1:
                            if 'swiatlo salon' in lights:
                                set_light(w_mb, 'swiatlo salon', 0)
                            else:
                                set_light(w_mb, 'swiatlo salon', 1)
                        elif 16 - x == 2:
                            if 'swiatlo przejscie' in lights:
                                set_light(w_mb, 'swiatlo przejscie', 0)
                            else:
                                set_light(w_mb, 'swiatlo przejscie', 1)
                        elif 16 - x == 3:
                            if 'swiatlo spizarnia' in lights:
                                set_light(w_mb, 'swiatlo spizarnia', 0)
                            else:
                                set_light(w_mb, 'swiatlo spizarnia', 1)
                        elif 16 - x == 4:
                            if 'swiatlo lazienka gora' in lights:
                                set_light(w_mb, 'swiatlo lazienka gora', 0)
                            else:
                                set_light(w_mb, 'swiatlo lazienka gora', 1)
                    # print(f'{i}_{x}')
    old_inputs = inputs
    time.sleep(0.05)


print(b_inputs_1)
