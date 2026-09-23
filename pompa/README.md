# Programy pompy ciepła

Sterownik pompy (Quotek, `192.168.1.31`) programuje się narzędziem `kotek_rpi` na Pi — opis: [docs/pompa-ciepla.md](../docs/pompa-ciepla.md).

| Plik | Zawartość |
|---|---|
| `kopia-2026-09-18/` | kopia wszystkich programów (1–5, S) sprzed zmian z 2026-09-18, XML + tekst, status, dziennik akcji |
| `program-S-pusty.xml` | pusty program S (stały) — wgrany 2026-09-18 |
| `program-3-bez-grzania.xml` | program 3 bez akcji — wgrany 2026-09-18 (zastąpiony) |
| `program-3-pompy-10.xml` | program 3: codziennie 10:00 same pompy 15 min — wgrany i aktywny od 2026-09-18 |
| `stare/` | wcześniejsze pliki programów z katalogu głównego projektu |

## Stan od 2026-09-18

Pompa ma **nie grzać** (włączana z bezpiecznika po przerwie):

- aktywny program **3 „bez grzania, pompy”** (`program-3-pompy-10.xml`) — jedna akcja: **codziennie 10:00 pompa kolektora i pompa CO po 15 min** (bez sprężarki). Godzina wg zegara sterownika — ustawiony na czas Pi 2026-09-18 14:58;
- program **S** pusty. Wcześniej zawierał codzienne grzanie o 08:21 (`pompaspecjal.xml` ze stycznia 2026 bez daty w akcji — wykonywało się każdego dnia);
- programy 1, 2, 4 bez zmian. Program 3 „2h” nadpisany — oryginał w `kopia-2026-09-18/program-3.*`.

Powrót do grzania wg programu „8h”:

```bash
~/dzarwisV2/kotek_rpi --adres 192.168.1.31 wlaczprogram 4
```

Przywrócenie oryginalnego programu 3 lub S: `kotek_rpi --adres 192.168.1.31 program kopia-2026-09-18/program-3.xml`.

## Uwagi

- `wlaczprogram` działa z opóźnieniem kilku sekund — `aktprogram` zaraz po nim może jeszcze pokazać poprzedni program. `kotek` wypisuje numer wewnętrzny liczony od zera (`programNr=2` = program 3).
- Programy wykonują się wg **zegara sterownika**. Nie zmienia sam czasu letni/zimowy — poprawić po każdej zmianie czasu (polecenie w [docs/pompa-ciepla.md](../docs/pompa-ciepla.md#pułapki)).
- Akcja z samą godziną (`<akcja czas="08:21">`) wykonuje się **codziennie**; jednorazowa wymaga `data="RR/MM/DD"` — rok **dwucyfrowo**, pełny rok sterownik zapisuje błędnie (2026 → 2042, [pompa-ciepla.md](../docs/pompa-ciepla.md#pułapki)).
