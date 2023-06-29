import dzarwis_global_vars as dgv
from pyModbusTCP.client import ModbusClient

# def button_press_detector(list1, list2):
#     if len (list1) == len(list2):
#         for i in range(len(list1)):
#             if

w_mb = ModbusClient(host = dgv.PLC.ip, unit_id=dgv.PLC.uid, port=dgv.PLC.port,auto_open=True,auto_close=True)
inputs = await w_mb.read_holding_registers(0, 40)
b_inputs_1=list('{0:016b}'.format(inputs[0]))

print(b_inputs_1)
