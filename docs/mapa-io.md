# Mapa wejść/wyjść i rejestrów Modbus

## WAGO 750 — przestrzeń adresowa

| Rejestry (holding, FC3/FC6) | Zawartość | Użycie w kodzie |
|---|---|---|
| 0–3 | obraz wejść cyfrowych, 16 wejść na rejestr | `lights_v2_.py` czyta 4 rejestry, używa 0 i 1 |
| 512–767 | obraz wyjść cyfrowych (odczyt i zapis) | `PLC.out_start_reg` / `PLC.out_stop_reg` |

Kolejność bitów: **bit 0 (najmłodszy) = pierwszy kanał**. Numer „`out_num_sw`” z konfiguracji to numer bitu w całym obrazie wyjść:

```
rejestr = 512 + out_num_sw // 16
bit     = out_num_sw % 16
```

## Wyjścia (`dzarwis_global_vars.PLC.Douts`)

| `out_num_sw` | Rejestr.bit | Nazwa | `card_num` / `out_num_hw` |
|---|---|---|---|
| 0 | 512.0 | swiatlo lazienka | 1 / 1 |
| 1 | 512.1 | swiatlo biuro | 1 / 2 |
| 2 | 512.2 | swiatlo kuchnia | – |
| 3 | 512.3 | swiatlo salon | – |
| 4 | 512.4 | swiatlo hol | – |
| 5 | 512.5 | swiatlo spizarnia | – |
| 6 | 512.6 | swiatlo jadalnia | – |
| 7 | 512.7 | swiatlo Natka | – |
| 8 | 512.8 | swiatlo Ola | – |
| 9 | 512.9 | swiatlo Pawel | – |
| 10 | 512.10 | swiatlo pralnia | – |
| 11 | 512.11 | swiatlo nad schodami | – |
| 12 | 512.12 | swiatlo sypialnia | – |
| 13 | 512.13 | swiatlo salon kinkiety | – |
| 14 | 512.14 | swiatlo wiatrolap | – |
| 15 | 512.15 | swiatlo Natka 2 | – |
| 16 | 513.0 | swiatlo lazienka gora | – |
| 17 | 513.1 | swiatlo przejscie | – |
| 18 | 513.2 | bojler mieszadlo | – |
| 19 | 513.3 | bojler grzanie | – |

`card_num` i `out_num_hw` (numer karty i zacisku) są wypełnione tylko dla dwóch pierwszych wyjść i **nie są używane przez kod** — służą jako opis okablowania. Warto je uzupełnić przy okazji przeglądu szafy.

Nazwa wyjścia to klucz używany w kodzie i w kolejce — musi się zgadzać co do znaku (wielkość liter, spacje).

## Przyciski → lampy (`lights_v2_.py`)

Kanał = numer bitu + 1 (kolejne wejście DI w obrazie procesu).

### Rejestr 0

| Bit | Kanał | Lampa |
|---|---|---|
| 0 | 1 | swiatlo lazienka |
| 1 | 2 | swiatlo biuro |
| 2 | 3 | swiatlo kuchnia |
| 3 | 4 | swiatlo salon kinkiety |
| 4 | 5 | swiatlo wiatrolap |
| 5 | 6 | swiatlo jadalnia |
| 6 | 7 | swiatlo nad schodami |
| 7 | 8 | swiatlo hol |
| 8 | 9 | swiatlo Ola |
| 9 | 10 | swiatlo Pawel |
| 10 | 11 | swiatlo Natka |
| 11 | 12 | swiatlo Natka 2 |
| 12 | 13 | swiatlo pralnia |
| 13 | 14 | swiatlo sypialnia |
| 14 | 15 | *nieprzypisany* |
| 15 | 16 | *nieprzypisany w v2* — w `lihgts.py` (v1) drugi przycisk „nad schodami” |

### Rejestr 1

| Bit | Kanał | Lampa |
|---|---|---|
| 0 | 17 | swiatlo salon |
| 1 | 18 | swiatlo przejscie |
| 2 | 19 | swiatlo spizarnia |
| 3 | 20 | swiatlo lazienka gora |

Rejestry 2–3 są czytane, ale nieużywane. Kolejność przycisków **nie jest** taka sama jak kolejność wyjść — przypisanie jest w słowniku `PRZYCISKI` na początku `lights_v2_.py`.

## Bramka 192.168.8.40 — Growatt (unit id 2)

Odczyt: input registers (FC4) 3000–3049 oraz 3105–3106.

| Rejestr | Pole | Skala | Zapis do InfluxDB |
|---|---|---|---|
| 3000 | status falownika | – | `growat.Status` |
| 3026 | napięcie sieci Vac1 | ×0,1 V | `growat.Grid_V` |
| 3027 | prąd Iac1 | ×0,1 A | `growat.Grid_I` |
| 3028 | moc Pac1 — słowo starsze | ×0,1 W | nie zapisywane |
| 3029 | moc Pac1 — słowo młodsze | ×0,1 W | `growat.Grid_P` (tylko to słowo!) |
| 3105 | kod błędu | – | `growat.Fault_code` |
| 3106 | kod ostrzeżenia | – | `growat.Warning_code` |

Panel WWW (`energia.py`) czyta dodatkowo: moc DC i stringi (3001–3010: U, I, P dla 2 stringów), moc AC 3023–3024, częstotliwość 3025 (×0,01 Hz), produkcję dziś 3049–3050 i łącznie 3051–3052 (×0,1 kWh), temperaturę 3093 (×0,1 °C). Pełna tabela: [specyfikacja zakładki PV](superpowers/specs/2026-09-18-panel-pv-design.md).

## Bramka 192.168.8.40 — licznik (unit id 3)

Licznik to **Eastron SDM630** (układ rejestrów zgodny; potwierdzone odczytem 2026-09-18).

Odczyt: input registers 0–19, liczby `float32`, big-endian (bajty i słowa).

| Rejestry | Pole | Zapis do InfluxDB |
|---|---|---|
| 0–1, 2–3, 4–5 | napięcia V1, V2, V3 | `licznik.V1..V3` |
| 6–7, 8–9, 10–11 | prądy I1, I2, I3 | `read_power.py`: dekodowane, nie zapisywane; panel WWW: karta „Moc na fazach” |
| 12–13, 14–15, 16–17 | moce P1, P2, P3 | `licznik.P1..P3` |
| 52–53 | moc łączna (ujemna = oddawanie) | panel WWW |
| 72–73 / 74–75 | energia pobrana / oddana łącznie [kWh] | panel WWW |

**Ujemna moc = oddawanie do sieci** — potwierdzone 2026-09-18 (falownik 3,6 kW, licznik −3,2 kW). `bojler_ster.py` korzysta z tej konwencji (`P1 < -2000`).
