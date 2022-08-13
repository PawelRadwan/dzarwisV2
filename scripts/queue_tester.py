#!/usr/bin/env python
from email.message import Message
from tkinter import ON
import pika
import dzarwis_global_vars as dgv
import json

connection = pika.BlockingConnection(
    pika.ConnectionParameters(host='localhost'))
channel = connection.channel()

channel.queue_declare(queue='wago')

message = {
    'command' : 'set_OFF',
    'output_name' : 'bojler mieszadlo'
    #'output_name' : 'swiatlo biuro'
}
channel.basic_publish(exchange='', routing_key='wago', body=json.dumps(message))
message2 = {
    'command' : 'check_outputs',
}
channel.basic_publish(exchange='', routing_key='wago', body=json.dumps(message2))

print(" [x] Sent 'Hello World!'")
connection.close()