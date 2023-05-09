from pyModbusTCP.client import ModbusClient
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.constants import Endian
import time as t
from datetime import datetime
from influxdb import InfluxDBClient

 
# przerwa w odczytywaniu 
s=10
#ip bramki
ip = '192.168.8.40'
# licznik
E_uid = 3
#growat 
G_uid = 2 
G_start_reg = 3000
G_cout_reg = 50


G_status_adrr = 3000
G_Vac1 = 3026
G_Iac1 = 3027
G_Pac1_H = 3028
G_Pac1_L= 3029

G_status_off = G_status_adrr - G_start_reg
G_Vac1_off = G_Vac1 - G_start_reg
G_Iac1_off = G_Iac1 - G_start_reg
G_Pac1_H_off = G_Pac1_H - G_start_reg
G_Pac1_L_off = G_Pac1_L - G_start_reg

G = ModbusClient(host=ip, port=502, unit_id=G_uid, auto_open=True, auto_close= True)
E = ModbusClient(host=ip, port=502, unit_id=E_uid, auto_open=True, auto_close= True)

db = InfluxDBClient('127.0.0.1', 8086, 'pi', 'pi', 'Energia')


while True:
    # zapytaj growat 
    G_regs = G.read_input_registers(G_start_reg, G_cout_reg)
    print(G_regs)
    # zapytaj growat błędy
    G_errors = G.read_input_registers(3105,2)

    # zapytaj licznik
    E_regs = E.read_input_registers(0, 20)
   
    now = datetime.now()
    print (now)
    now = int(now.timestamp()) * 1000
    try:
        #dekoduj growat
        G_v  = G_regs[G_Vac1_off] / 10
        G_I  = G_regs[G_Iac1_off] /10
        G_Ph = G_regs[G_Pac1_H_off] /10
        G_Pl = G_regs[G_Pac1_L_off] /10
        G_status = G_regs[G_status_off]
    except:
        print('problem')
    #dekodduj licznik 
    try:
        dekoder = BinaryPayloadDecoder.fromRegisters(E_regs,byteorder = Endian.Big,  wordorder = Endian.Big)
        licznik ={
            'v1' : round(dekoder.decode_32bit_float(),2),
            'v2' : round(dekoder.decode_32bit_float(),2),
            'v3' : round(dekoder.decode_32bit_float(),2),
            'I1' : round(dekoder.decode_32bit_float(),2),
            'I2' : round(dekoder.decode_32bit_float(),2),
            'I3' : round(dekoder.decode_32bit_float(),2),
            'P1' : round(dekoder.decode_32bit_float(),2),
            'P2' : round(dekoder.decode_32bit_float(),2),
            'P3' : round(dekoder.decode_32bit_float(),2)
            
        }
    
        print ('growat V',G_v,'growatP',G_Pl,'growat status',G_status, 'licznik',licznik['v1'],'moc',licznik['P1'])
        
        growat_json = [
            {

            "measurement":'growat',
            "time": now,
            "fields":{
                "Grid_V" : G_v,
                "Grid_I" : G_I,
                "Grid_P" : G_Pl,
                "Status" : G_status,
                "Fault_code" : G_errors[0],
                "Warning_code": G_errors[1]

            }

        },
        {
        "measurement":'licznik',
            "time": now,
            "fields":{
                "V1" : licznik['v1'],
                "V2" : licznik['v2'],
                "V3" : licznik['v3'],
                "P1" : licznik['P1'],
                "P2" : licznik['P2'],
                "P3" : licznik['P3']

            }}

        ]
        db.write_points(growat_json, time_precision = 'ms')
        t.sleep(s)
    except:
        print('problem')