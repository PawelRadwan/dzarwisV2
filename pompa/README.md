# Programy pompy ciepła

Sterownik pompy (Quotek, `192.168.1.31`) programuje się narzędziem `kotek_rpi` na Pi — opis: [docs/pompa-ciepla.md](../docs/pompa-ciepla.md).

| Plik | Zawartość |
|---|---|
| `kopia-2026-09-18/` | kopia wszystkich programów (1–5, S) sprzed zmian z 2026-09-18, XML + tekst, status, dziennik akcji |
| `program-S-pusty.xml` | pusty program S (stały) — wgrany 2026-09-18 |
| `program-3-bez-grzania.xml` | program 3 bez akcji — wgrany i aktywny od 2026-09-18 |
| `stare/` | wcześniejsze pliki programów z katalogu głównego projektu |

## Stan od 2026-09-18

Pompa ma **nie grzać** (włączana z bezpiecznika po przerwie):

- aktywny program **3 „bez grzania”** — brak akcji;
- program **S** pusty. Wcześniej zawierał codzienne grzanie o 08:21 (`pompaspecjal.xml` ze stycznia 2026 bez daty w akcji — wykonywało się każdego dnia);
- programy 1, 2, 4 bez zmian. Program 3 „2h” nadpisany — oryginał w `kopia-2026-09-18/program-3.*`.

Powrót do grzania wg programu „8h”:

```bash
~/dzarwisV2/kotek_rpi --adres 192.168.1.31 wlaczprogram 4
```

Przywrócenie oryginalnego programu 3 lub S: `kotek_rpi --adres 192.168.1.31 program kopia-2026-09-18/program-3.xml`.

## Uwagi

- `wlaczprogram` działa z opóźnieniem kilku sekund — `aktprogram` zaraz po nim może jeszcze pokazać poprzedni program. `kotek` wypisuje numer wewnętrzny liczony od zera (`programNr=2` = program 3).
- Programy wykonują się wg **zegara sterownika**, który 2026-09-18 spóźniał się o ~1 h (brak zmiany na czas letni).
- Akcja z samą godziną (`<akcja czas="08:21">`) wykonuje się **codziennie**; jednorazowa wymaga `data="RRRR/MM/DD"`.
