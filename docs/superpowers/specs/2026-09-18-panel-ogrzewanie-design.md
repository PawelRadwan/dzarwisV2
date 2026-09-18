# Zakładka Ogrzewanie — projekt i plan

Data: 2026-09-18. Status: zaakceptowany (pompa CWU odłożona — podłączona do przekaźnika sprężarki, do przełożenia na osobne wyjście).

## Zakres

- Podgląd: stan sterownika i awaria, sprężarka (moc), pompy CO / kolektora, czujniki PWR/HP/LP, taryfa, temperatury czujników (bieżące, min/max 24 h), energia [kWh], aktywny program i jego harmonogram, ostatnie akcje, przesunięcie zegara sterownika.
- Zmiana aktywnego programu 1–4.
- Same pompy: CO, kolektora, obie — domyślnie 15 min, zmienialne; licznik odliczający; stop.
- Ręczne grzanie: domyślnie 1 h, zmienialne (0,5–8 h); licznik odliczający.

Poza zakresem: pompa CWU, edycja harmonogramów, zegar sterownika, konfiguracja.

## Komunikacja

Tylko przez `kotek_rpi --adres 192.168.1.31` (`/home/pi/dzarwisV2/kotek_rpi`), wywoływany z `subprocess` pod blokadą (jedno wywołanie naraz), timeout 20 s. Błąd = kod ≠ 0, wyjątek lub tekst `ERROR(` w wyjściu (przy braku łączności `kotek` kończy się kodem 0 z `ERROR(... Brak powierdzenia ...)`).

| Cel | Polecenie |
|---|---|
| status | `-b -x 0 status` (XML na stdout) |
| temperatury | `-b -x 0 odczytczujnikow` |
| harmonogram aktywnego | `czytajprogram 0` (tekst, linie `AK. n: ...`) |
| lista programów | `listaprogramow` |
| ostatnie akcje | `wykonaneakcje` |
| zmiana programu | `wlaczprogram <1..4>`, potwierdzenie przez `aktprogram` do 20 s (zmiana działa z opóźnieniem) |
| pompy | `samepompy <min kolektora> <min CO>` (0–120), stop: `samepompy 0 0` |
| ręczne grzanie | `program <plik>` z programem S wygenerowanym przez panel |

Żadne inne polecenia nie są wywoływane. Parametry wyliczane i sprawdzane w panelu.

### Ręczne grzanie

1. Czas sterownika z `status` (`<czas godzina data>`), nie czas Pi (zegar sterownika się spóźnia).
2. Start = czas sterownika + 1 min (+2 min, jeśli sekundy ≥ 45), z przejściem przez północ.
3. Plik `data/pompa-S-reczne.xml`:
   `<pompa CfgVer="1.0"><program numer="S" opis="reczne grzanie"><akcja data="RRRR/MM/DD" czas="GG:MM"><grzanie czas="<minuty>"/></akcja></program></pompa>`
   — akcja z datą wykonuje się raz; temperatura z ustawień sterownika (powrót CO 35 °C).
4. `program <plik>`; panel zapamiętuje „zaplanowane na GG:MM (czas sterownika), do …”.

Nadpisuje program S (od 2026-09-18 pusty).

## Stan w panelu

- Odczyt `status` + `odczytczujnikow` co 5 s; harmonogram, lista programów, akcje co 60 s i po każdej zmianie.
- Pompy i ręczne grzanie: panel zapisuje `do kiedy` w `data/pompa-stan.json` (licznik przetrwa restart i jest wspólny dla telefonów).
- Grzanie trwające: pozostały czas z `status` (`czasPracyMin doKonca`), inaczej z zapisu panelu.
- Energia: impulsy / 1000 = kWh (wg opisu konfiguracji sterownika).
- Program aktywny: w XML liczony od zera → +1.

## API

| Żądanie | Treść | Odpowiedź |
|---|---|---|
| `GET /api/heat` | — | stan (`503`, dopóki nie ma odczytu) |
| `POST /api/heat/program` | `{"program": 1..4}` | stan |
| `POST /api/heat/pumps` | `{"co_min": 0..120, "kol_min": 0..120}` (co najmniej jedna > 0) | stan |
| `POST /api/heat/pumps/stop` | — | stan |
| `POST /api/heat/manual` | `{"hours": 0.5..8}` | stan |

Błędy: `400` złe parametry, `503` brak łączności ze sterownikiem.

## Strona

Zakładka Ogrzewanie: paski (awaria — czerwony, brak łączności — czerwony, zegar przesunięty > 5 min — żółty); kafelki (stan, moc sprężarki, taryfa, program); karta Sterowanie (ręczne grzanie z polem godzin, pompy z polem minut i trzema przyciskami, stop, wybór programu — wszystko z potwierdzeniem i licznikami odliczającymi co 1 s); temperatury; pompy i czujniki; harmonogram; ostatnie akcje (powtórzenia zwinięte); energia; informacja o pompie CWU. Odświeżanie co 5 s tylko na otwartej zakładce.

## Plan

1. `scripts/pompa.py` + `tests/test_pompa.py` (TDD): parsowanie na nagranych odpowiedziach (`tests/dane_pompy/`), walidacja parametrów, generowanie programu S (także przez północ), liczniki, błędy `kotek`, blokada niedozwolonych poleceń.
2. `web_panel.py`: trasy `/api/heat*`, wątek odczytu; testy HTTP.
3. `index.html`: zakładka; test w przeglądarce na symulowanym sterowniku.
4. Dokumentacja (`docs/panel-www.md`, `docs/pompa-ciepla.md`), commit, wdrożenie, podgląd na żywo. Sterowanie na prawdziwej pompie — dopiero po zgodzie użytkownika.
