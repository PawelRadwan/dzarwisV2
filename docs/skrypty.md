# Opis skryptów i funkcji

Wszystkie skrypty są w `scripts/` i importują konfigurację jako `import dzarwis_global_vars as dgv`, więc trzeba je uruchamiać z katalogu `scripts/` (albo z nim w `PYTHONPATH`).

---

## `dzarwis_global_vars.py` — konfiguracja

Moduł bez logiki, tylko stałe.

| Nazwa | Wartość | Znaczenie |
|---|---|---|
| `influx_ip`, `influx_port` | `127.0.0.1`, `8086` | InfluxDB 1.x |
| `influx_user`, `influx_password` | `pi` / `pi` | dane logowania do InfluxDB |
| `influx_energia_db_name` | `Energia` | baza z pomiarami energii |
| `NT_day_start`, `NT_day_stop` | `13`, `15` | dzienna niska taryfa, pełne godziny [start, stop) |
| `mix_hour` | `10` | godzina porannego mieszania bojlera |
| `mix_time` | `10` | czas mieszania w minutach |

**`DO`** (dataclass) — opis jednego wyjścia:

| Pole | Typ | Znaczenie |
|---|---|---|
| `card_num` | int | numer karty wyjść w węźle WAGO (opisowo, nieużywane) |
| `out_num_hw` | int | numer zacisku na karcie (opisowo, nieużywane) |
| `out_num_sw` | int | numer bitu w obrazie wyjść — **tego używa kod** |
| `nazwa` | str | nazwa wyjścia, klucz w kodzie i w kolejce |

**`PLC`** — parametry sterownika: `ip`, `port`, `uid`, zakres rejestrów wyjść `out_start_reg`–`out_stop_reg` oraz lista `Douts`. Pełna tabela wyjść: [mapa-io.md](mapa-io.md).

Dodanie nowego wyjścia = dopisanie `DO(...)` do `Douts` z kolejnym `out_num_sw`.

---

## Wspólne funkcje obsługi WAGO (`wago_750_comunication.py`, `lihgts.py`)

Te same funkcje są skopiowane do `wago_750_comunication.py` i `lihgts.py` (oraz `brudnopis.py`). Zmiana w jednym pliku **nie** przenosi się do pozostałych. `lights_v2_.py` od 2026-09-18 ma własną, prostszą obsługę — patrz niżej.

### `wago_read_outputs(mb) -> list[int]`

Czyta obraz wyjść od rejestru 512 w paczkach po maks. 125 rejestrów (limit Modbusa), razem 255 rejestrów (512–766), i zwraca płaską listę bitów `0/1`. Element `n` listy to stan wyjścia o `out_num_sw == n`.

- `mb` — `pyModbusTCP.client.ModbusClient` połączony z WAGO.
- Przy błędzie komunikacji `read_holding_registers` zwraca `None`, a funkcja kończy się wyjątkiem `TypeError`.

### `interprate_outputs(ob) -> list[str]`

Zamienia listę bitów z `wago_read_outputs` na listę **nazw** włączonych wyjść (tylko tych opisanych w `PLC.Douts`).

### `wago_set_outputs(mb, outs_sw_nums)`

Ustawia wybrane wyjścia.

- `outs_sw_nums` — lista słowników `{'sw_num': int, 'state': 0|1}`.
- Czyta obraz wyjść, nakłada zmiany, a następnie zapisuje (`write_single_register`) **tylko rejestry, w których coś się zmieniło**, każdy jako całe 16 bitów.

### `set_light(w_mb, nazwa, state)` — tylko w `lihgts.py`

Wyszukuje wyjście po nazwie i wywołuje `wago_set_outputs` dla jednego bitu. Nieznana nazwa = brak działania.

---

## `lights_v2_.py` — obsługa przycisków (produkcyjny)

Przepisany 2026-09-18 (zachowanie przycisków bez zmian, poprawiona odporność na błędy).

### Działanie

1. Tworzy jedno stałe połączenie z WAGO (`auto_open=True`, `auto_close=False`, timeout 2 s).
2. Co `POLL_INTERVAL` (50 ms) czyta rejestry wejść 0–3.
3. Pierwszy udany odczyt tylko zapamiętuje stan (`old_inputs`) — nie przełącza niczego.
4. Przy kolejnych odczytach dla każdego bitu, który zmienił się z `1` na `0` (puszczenie przycisku), szuka pozycji `(rejestr, bit)` w tabeli `PRZYCISKI` i przełącza przypisaną lampę. Bity bez przypisania są ignorowane.
5. **Każdy błąd** (odczyt, zapis, wyjątek) jest logowany, połączenie zamykane, a po `ERROR_DELAY` (1 s) skrypt zaczyna od kroku 3. Proces się nie kończy. Zmiany wejść z czasu przerwy nie przełączają lamp.

### Stałe

| Nazwa | Wartość | Znaczenie |
|---|---|---|
| `PRZYCISKI` | słownik `(rejestr, bit) -> nazwa wyjścia` | przypisanie przycisków do lamp, pełna tabela: [mapa-io.md](mapa-io.md#przyciski--lampy-lights_v2_py) |
| `IN_START_REG`, `IN_REG_COUNT` | `0`, `4` | czytane rejestry wejść |
| `POLL_INTERVAL` | `0.05` s | okres odpytywania |
| `ERROR_DELAY` | `1` s | przerwa po błędzie |
| `MODBUS_TIMEOUT` | `2` s | limit czasu zapytania (domyślny w pyModbusTCP to 30 s) |

### Funkcje

- **`read_registers(mb, start, count) -> list[int]`** — odczyt rejestrów holding; zamiast zwracać `None` rzuca `ModbusError`.
- **`toggle_light(mb, nazwa)`** — przełącza lampę: czyta **jeden** rejestr wyjść, w którym jest jej bit, odwraca bit (XOR) i zapisuje rejestr. Nieudany zapis → `ModbusError`. Nieznana nazwa → ostrzeżenie w logu.
- **`released_buttons(old_inputs, inputs)`** — generator pozycji `(rejestr, bit)` ze zboczem opadającym.
- **`main()`** — pętla opisana wyżej. Logi (`logging`, poziom INFO) trafiają na stderr, a stamtąd do `journalctl -u lights.service`.

### Przykładowy log

```
INFO start, WAGO 192.168.8.5:502
INFO połączenie z WAGO OK
INFO swiatlo kuchnia: włączone
ERROR ModbusError: odczyt rejestrów 0-3 nieudany (kod błędu 2) - ponowna próba za 1 s
INFO połączenie z WAGO OK
```

### Zmiana przypisania przycisku

Edytuj słownik `PRZYCISKI` na początku pliku, np. drugi przycisk schodów na bicie 15 rejestru 0:

```python
    (0, 15): 'swiatlo nad schodami',
```

Nazwa musi istnieć w `dgv.PLC.Douts`. Po zmianie: `sudo systemctl restart lights.service`.

## `lihgts.py` — poprzednia wersja (v1)

Różnice względem v2:

- reaguje na **stan** wejścia (`== '1'`), nie na zbocze — trzymanie przycisku przełącza lampę co ~100 ms;
- czyta 40 rejestrów wejść, wypisuje w każdym obiegu stan wszystkich wejść i lamp (przydatne do diagnostyki okablowania);
- światło „nad schodami” reaguje na dwa przyciski: bit 6 **i bit 15** rejestru 0.

Nie należy go uruchamiać razem z v2.

## `wago_750_comunication.py` — konsument kolejki

`main()` łączy się z WAGO i z RabbitMQ (`localhost`), deklaruje kolejkę `wago` i przetwarza wiadomości w `callback`. Polecenia i format: [kolejka.md](kolejka.md). Wypisuje na konsolę każdy zapis rejestru i wynik zapisu. `Ctrl+C` kończy program.

## `queue_tester.py` — test kolejki

Wysyła do kolejki `wago` dwie wiadomości: `set_OFF` dla `bojler mieszadlo` i `check_outputs`. Treść do edycji ręcznej. Importy `email.message` i `tkinter` są zbędne (na Pi bez `python3-tk` skrypt się nie uruchomi).

## `read_power.py` — rejestrator energii

Konfiguracja jest w samym pliku (nie w `dzarwis_global_vars`): `s = 10` (okres w sekundach), `ip = '192.168.8.40'`, unit id Growatta `2` i licznika `3`, dane InfluxDB wpisane na sztywno.

Co 10 s:

1. Czyta z Growatta rejestry 3000–3049 i kody błędów 3105–3106.
2. Czyta z licznika 20 rejestrów i dekoduje 9 liczb `float32` (`BinaryPayloadDecoder`, big-endian).
3. Zapisuje dwa punkty (`growat`, `licznik`) do bazy `Energia` z precyzją ms.

Rejestry i pola: [mapa-io.md](mapa-io.md#bramka-19216840--growatt-unit-id-2). Błąd w dekodowaniu lub zapisie wypisuje `problem`, pętla trwa dalej.

## `bojler_ster.py` — sterowanie bojlerem (niedokończone)

- `read_return_power(db_client) -> float` — średnia z pola `P1` pomiaru `licznik` z ostatnich 5 minut.
- `main()` co 60 s:
  - w oknie `mix_hour` … `mix_hour + mix_time` min wypisuje „start mieszanie”,
  - w oknie taryfy dziennej `NT_day_start`–`NT_day_stop` wypisuje „włącz grzanie”,
  - poza taryfą: jeśli średnie `P1 < -2000` W (oddawanie > 2 kW) — „załącz grzanie”, w przeciwnym razie „wyłącz grzanie”.

Skrypt **niczego nie przełącza** — tylko wypisuje decyzje. Naturalny następny krok: wysyłanie `set_ON`/`set_OFF` dla `bojler grzanie` / `bojler mieszadlo` do kolejki `wago`.
