# moduł komunkacyjny do do wago 750 - obsługa domu 
# dane do modułu dostarczane za pomcą kolejki rapidMQ 

from pyModbusTCP.client import ModbusClient
import dzarwis_global_vars as dgv
import sys
from time import sleep
import pika
import json

def wago_read_outputs(mb):
    # wyjścia wgo są dostępne na holdingach w przestrzni adresowej 512-767
    outputs = []
    start_reg = dgv.PLC.out_start_reg
    lrc=125
    while lrc>0:
        outputs.extend(mb.read_holding_registers(start_reg,lrc))
       # print(f'start:{start_reg} ilość  do odczytu:{lrc}')
        start_reg +=lrc
        if start_reg + lrc> dgv.PLC.out_stop_reg:
            lrc = dgv.PLC.out_stop_reg-start_reg
    #print(outputs)
    ob = []
    for o in outputs:
        add = list("{0:016b}".format(o))[::-1]
        #print(add)
        ob.extend(add)
    obb= []
    for i in ob:
        obb.append(int(i))
    
    return(obb)

def wago_set_outputs(mb,outs_sw_nums:list[dict['sw_num':int,'state':int]]):
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
         
def main():
    w_mb = ModbusClient(host = dgv.PLC.ip, unit_id=dgv.PLC.uid, port=dgv.PLC.port,auto_open=True,auto_close=True)
    
    connection = pika.BlockingConnection(pika.ConnectionParameters(host='localhost'))
    channel = connection.channel()
    channel.queue_declare(queue='wago')
    def callback(ch, method, properties, body):
        message = json.loads(body)
        print(f"Received {message}")
        komenda = message['command']
        o = wago_read_outputs(w_mb)
        o_names = interprate_outputs(o)
        if komenda  == 'set_ON':
            #sprawdz czy dane wyjście nie jest już załcznone jeżeli jest to załącz
            if message['output_name'] not in o_names:
                for o in dgv.PLC.Douts:
                    if o.nazwa == message['output_name']:
                        onum = o.out_num_sw
                        print(f'załącz numer wyjścia:{onum}')
                        wago_set_outputs(w_mb,[{'sw_num':onum,'state':1}])
            else: 
                print(f'wyjście już załącznone{o_names}')
        if komenda == 'set_OFF':
            #sprawdz czy dane wyjście jest aktywne
            if message['output_name'] not in o_names:
                print (f'wyjjście nie aktywne{o_names}')
            else:
                for o in dgv.PLC.Douts:
                    if o.nazwa == message['output_name']:
                        onum = o.out_num_sw
                        print(f'załącz numer wyjścia:{onum}')
                        wago_set_outputs(w_mb,[{'sw_num':onum,'state':0}])
        if komenda == 'check_outputs':
            print(o_names)

    channel.basic_consume(queue='wago', on_message_callback=callback, auto_ack=True)

    print(' [*] Waiting for messages. To exit press CTRL+C')
    channel.start_consuming()

    

if __name__ == "__main__":
   try:
    main()
   except KeyboardInterrupt:
        print('Interrupted')
        sys.exit(0)