# Protokół kolejki RabbitMQ

`wago_750_comunication.py` konsumuje kolejkę **`wago`** na RabbitMQ `localhost` (domyślny exchange, domyślne dane logowania `guest`). Wiadomość to obiekt JSON w treści (body).

## Polecenia

### `set_ON` — włącz wyjście

```json
{"command": "set_ON", "output_name": "swiatlo kuchnia"}
```

Jeśli wyjście już jest włączone, nic nie jest zapisywane.

### `set_OFF` — wyłącz wyjście

```json
{"command": "set_OFF", "output_name": "bojler grzanie"}
```

Jeśli wyjście już jest wyłączone, nic nie jest zapisywane.

### `check_outputs` — pokaż włączone wyjścia

```json
{"command": "check_outputs"}
```

Wypisuje listę nazw włączonych wyjść **na standardowe wyjście konsumenta**. Nic nie jest odsyłane nadawcy — to polecenie diagnostyczne.

`output_name` musi dokładnie odpowiadać polu `nazwa` w `PLC.Douts` (lista: [mapa-io.md](mapa-io.md#wyjścia-dzarwis_global_varsplcdouts)). Nieznana nazwa jest po cichu ignorowana. Nieznane `command` również.

## Wysłanie polecenia

Z Pythona (jak w `queue_tester.py`):

```python
import json, pika

conn = pika.BlockingConnection(pika.ConnectionParameters(host="localhost"))
ch = conn.channel()
ch.queue_declare(queue="wago")
ch.basic_publish(exchange="", routing_key="wago",
                 body=json.dumps({"command": "set_ON", "output_name": "swiatlo hol"}))
conn.close()
```

Z konsoli (wymaga `rabbitmqadmin`):

```bash
rabbitmqadmin publish exchange=amq.default routing_key=wago \
  payload='{"command":"set_OFF","output_name":"swiatlo hol"}'
```

## Uwagi

- Wiadomości są potwierdzane automatycznie (`auto_ack=True`) — przy błędzie przetwarzania wiadomość przepada.
- Wyjątek w obsłudze wiadomości (np. niepoprawny JSON, brak klucza `command`, błąd Modbusa) **zatrzymuje konsumenta**. Proces trzeba uruchomić ponownie.
- Nie ma odpowiedzi ani potwierdzenia wykonania dla nadawcy.
