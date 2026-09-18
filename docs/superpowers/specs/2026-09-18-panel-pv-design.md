# Zakładka PV w panelu WWW — projekt

Data: 2026-09-18. Status: zaakceptowany.

## Cel

Zakładka PV w panelu (`http://192.168.8.18/#pv`): bieżąca produkcja, sieć, zużycie domu, wykres dzisiejszego dnia, bilans dnia, stringi PV, stan falownika.

## Źródła danych (sprawdzone na żywo 2026-09-18)

Bramka Modbus TCP `192.168.8.40:502`.

**Growatt, unit 2, input registers** (przesunięcie od 3000; `H/L` = 32 bity, słowo starsze pierwsze):

| Rej. | Pole | Skala | Odczyt testowy |
|---|---|---|---|
| 3000 | status (0 oczekiwanie, 1 praca, 3 awaria) | – | 1 |
| 3001–3002 | moc DC łącznie | 0,1 W | 3646,6 W |
| 3003 / 3004 / 3005–3006 | string 1: U / I / P | 0,1 V / 0,1 A / 0,1 W | 249,9 V / 5,4 A / 1351,6 W |
| 3007 / 3008 / 3009–3010 | string 2: U / I / P | jw. | 424,6 V / 5,4 A / 2295,0 W |
| 3023–3024 | moc AC oddawana przez falownik | 0,1 W | 3597,3 W |
| 3025 | częstotliwość | 0,01 Hz | 50,01 Hz |
| 3049–3050 | produkcja dziś | 0,1 kWh | 11,8 kWh |
| 3051–3052 | produkcja łącznie | 0,1 kWh | 29 708,6 kWh |
| 3093 | temperatura | 0,1 °C | 46,9 °C |
| 3105 / 3106 | kod błędu / ostrzeżenia | – | 0 / 0 |

**Licznik Eastron SDM630, unit 3, input registers, float32 big-endian:**

| Rej. | Pole | Odczyt testowy |
|---|---|---|
| 0, 2, 4 | napięcie L1–L3 [V] | 248,2 / 244,6 / 245,6 |
| 12, 14, 16 | moc L1–L3 [W] | −3437,6 / 166,3 / 60,7 |
| 52 | moc łączna [W] (ujemna = oddawanie do sieci) | −3222,4 |
| 72 | energia pobrana łącznie [kWh] | 41 051,8 |
| 74 | energia oddana łącznie [kWh] | 22 750,2 |

Odczyt 80 rejestrów licznika naraz jest odrzucany, 60 działa — zapytania dzielone.

## Architektura

```
web_panel.py (web.service)
 ├─ Panel (światła, WAGO)                      — bez zmian
 └─ energia.Collector (wątek, co 5 s) ──Modbus──► bramka 192.168.8.40 (Growatt, SDM630)
        ├─ latest (pamięć)  ──► GET /api/pv
        └─ co 60 s: średnie ──► SQLite data/energia.db ──► GET /api/pv/day, bilans dnia
```

- `scripts/energia.py` — dekodowanie rejestrów (funkcje czyste), odczyt urządzeń, `EnergyStore` (SQLite), `Collector` (wątek).
- `web_panel.py` — uruchamia `Collector`, nowe trasy API. Osobny `ModbusClient` dla bramki (WAGO bez zmian).
- Baza: `data/energia.db` w katalogu repo (w `.gitignore`), tabela `samples`: `ts` (początek minuty, epoch s), `pv_w`, `grid_w`, `home_w` (średnie z minuty), `pv_today_kwh`, `pv_total_kwh`, `import_kwh`, `export_kwh` (ostatnie wartości w minucie; `NULL` gdy brak odczytu).

## Zasady obliczeń

- `home_w = pv_w + grid_w` (grid ujemne przy oddawaniu).
- Falownik nie odpowiada, licznik tak → `inverter_ok = false`, `pv_w = 0`, status „Nie odpowiada” (w nocy normalne), bez czerwonego paska.
- Licznik nie odpowiada → `meter_ok = false`, pasek „Brak połączenia z licznikiem energii”; wartości sieci/domu = `null`.
- Bilans dnia (doba wg czasu lokalnego Pi):
  - `import_today = import_now − import` z pierwszej próbki doby (`since` = czas tej próbki);
  - `export_today` analogicznie;
  - `pv_today` = produkcja dziś z falownika, a gdy nie odpowiada — ostatnia zapisana dziś wartość, inaczej 0;
  - `home_today = pv_today + import_today − export_today`;
  - `self_use_pct = (pv_today − export_today) / pv_today × 100` (gdy `pv_today > 0`, obcięte do 0–100).
- Błąd zapisu do bazy jest logowany i nie zatrzymuje odczytów na żywo.

## API

`GET /api/pv` → `503`, dopóki nie ma żadnego odczytu; potem:

```json
{
  "updated": 1789727000,
  "meter_ok": true, "inverter_ok": true,
  "now": {"pv_w": 3597.3, "grid_w": -3222.4, "home_w": 374.9},
  "today": {"pv_kwh": 11.8, "import_kwh": 1.2, "export_kwh": 8.1, "home_kwh": 4.9, "self_use_pct": 31, "since": 1789682400},
  "strings": [{"w": 1351.6, "v": 249.9, "a": 5.4}, {"w": 2295.0, "v": 424.6, "a": 5.4}],
  "inverter": {"status": 1, "status_text": "Praca", "temp_c": 46.9, "freq_hz": 50.01, "fault": 0, "warning": 0},
  "totals": {"pv_kwh": 29708.6, "import_kwh": 41051.8, "export_kwh": 22750.2}
}
```

`GET /api/pv/day` → `{"date": "2026-09-18", "points": [[ts, pv_w, home_w], ...]}` — dzisiejsze minuty z bazy.

## Strona

- 4 duże kafelki: Produkcja teraz [kW], Sieć („Pobór x kW” / „Oddawanie x kW”, różne kolory), Zużycie domu [kW], Produkcja dziś [kWh].
- Wykres dnia (inline SVG, bez bibliotek): oś 0–24 h, produkcja — wypełnione pole, zużycie domu — linia, legenda, oś Y w kW.
- Bilans dnia: pobrano / oddano / zużycie domu [kWh], autokonsumpcja [%], „od HH:MM”, jeśli pierwsza próbka doby jest po 00:05.
- Stringi PV: moc, napięcie, prąd.
- Stan falownika: status, temperatura, częstotliwość, kody błędów, liczniki łączne.
- Odświeżanie: `/api/pv` co 5 s, `/api/pv/day` co 60 s — tylko gdy zakładka PV jest widoczna.

## Testy

- Dekodowanie na zrzutach rejestrów z 2026-09-18 (wartości z tabel powyżej).
- `EnergyStore`: zapis, seria dnia, bilans dnia; uśpiony falownik; brak licznika.
- API przez prawdziwy serwer HTTP z podmienionymi urządzeniami.
- Przeglądarka: zrzuty ekranu PV (jasny/ciemny), na Pi odczyt na żywo.
