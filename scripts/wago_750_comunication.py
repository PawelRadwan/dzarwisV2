# moduł komunkacyjny do do wago 750 - obsługa domu 
# dane do modułu dostarczane za pomcą kolejki rapidMQ 

from pyModbusTCP.client import ModbusClient
import dzarwis_global_vars as dgv


def wago_read_outputs(mb):
    # wyjścia wgo są dostępne na holdingach w przestrzni adresowej 512-767
    outputs = []
    start_reg = 512
    stop_reg = 767
    lrc=125
    while lrc>0:
        outputs.extend(mb.read_holding_registers(start_reg,lrc))
        print(f'start:{start_reg} ilość  do odczytu:{lrc}')
        start_reg +=lrc
        if start_reg + lrc> stop_reg:
            lrc = stop_reg-start_reg
    #print(outputs)
    ob = []
    for o in outputs:
        ob.extend(list(bin(o).replace("0b", ""))[::-1])
    return(ob)

def interprate_outputs(ob):
    print(ob)

def main():
    w_mb = ModbusClient(host = dgv.wago_ip, unit_id=dgv.wago_u_id, port=dgv.wago_mb_port,auto_open=True,auto_close=True)
    o = wago_read_outputs(w_mb)
    interprate_outputs(o)

if __name__ == "__main__":
    main()