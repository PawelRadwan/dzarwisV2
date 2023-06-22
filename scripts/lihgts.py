import dzarwis_global_vars as dgv
from pyModbusTCP.client import ModbusClient
from time import sleep


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
            print(f'zapisuje wartość {reg_v} od rejestru {reg_num}')
            write = mb.write_single_register(reg_num,reg_v)
            print(write)
        i += 16


def set_light(w_mb,nazwa,state):
    for o in dgv.PLC.Douts:
        if o.nazwa == nazwa:
            onum = o.out_num_sw
            print(f'załącz numer wyjścia:{onum}')
            wago_set_outputs(w_mb, [{'sw_num': onum, 'state': state}])


# def wago_read_inputs(mb):

def main():
    w_mb = ModbusClient(host = dgv.PLC.ip, unit_id=dgv.PLC.uid, port=dgv.PLC.port,auto_open=True,auto_close=True)
    # outs = wago_read_outputs(w_mb)
    # lights =  interprate_outputs(outs)
    # print (lights)
    # set_light(w_mb,'swiatlo lazienka',0)
    # set_light(w_mb, 'swiatlo kuchnia', 0)
    # set_light(w_mb, 'swiatlo jadalnia', 0)
    # set_light(w_mb, 'swiatlo salon', 0)
    # set_light(w_mb, 'swiatlo hol', 0)
    while True:
        inputs = w_mb.read_holding_registers(0,40)
        outs = wago_read_outputs(w_mb)
        lights =  interprate_outputs(outs)
        print (lights)
        b_inputs=(list(format(inputs[0],'016b')))
        print(b_inputs)
        if b_inputs[-1] == '1':
            if 'swiatlo lazienka' in lights:
                set_light(w_mb, 'swiatlo lazienka', 0)
            else:
                set_light(w_mb, 'swiatlo lazienka', 1)
        if b_inputs[-2] == '1':
            if 'swiatlo biuro' in lights:
                set_light(w_mb, 'swiatlo biuro', 0)
            else:
                set_light(w_mb, 'swiatlo biuro', 1)
        if b_inputs[-3] == '1':
            if 'swiatlo kuchnia' in lights:
                set_light(w_mb, 'swiatlo kuchnia', 0)
            else:
                set_light(w_mb, 'swiatlo kuchnia', 1)
        if b_inputs[-7] == '1' or b_inputs[-16] == '1':
            if 'swiatlo nad schodami' in lights:
                set_light(w_mb, 'swiatlo nad schodami', 0)
            else:
                set_light(w_mb, 'swiatlo nad schodami', 1)

        sleep(0.1)



if __name__ == "__main__":
   try:
    main()
   except KeyboardInterrupt:
        print('Interrupted')
