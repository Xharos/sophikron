# Local demonstration data

From the repository root, with the local API running and migrations applied:

```powershell
.venv\Scripts\python.exe script\seed_demo_data.py --dry-run
.venv\Scripts\python.exe script\seed_demo_data.py
```

The script asks for a permanent administrator's email and password. Alternatively set
`SOPHIKRON_SEED_EMAIL` and `SOPHIKRON_SEED_PASSWORD` in the current process environment.
Passwords are never written to the script or printed. Accounts remain pending activation;
no invitations or emails are sent. Only the local HTTP API is used, never direct SQL.

Edit `CONFIG` in **seed_demo_data.py** to change class sizes, teacher/khôlleur counts by
subject, weekly course/TD/TP volumes, filled-calendar indexes, rooms and publication state.
The `Settings` defaults live in **demo_data/configuration.py**.

```powershell
.venv\Scripts\python.exe script\seed_demo_data.py --dry-run --classes 4 --students 30 --namespace trial-4
.venv\Scripts\python.exe script\seed_demo_data.py --classes 4 --students 30 --namespace trial-4
```

A non-default namespace prefixes promotion/calendar names and account emails. Use a new namespace
when changing an existing scenario's roster or timetable. Compatible retries reuse all accounts,
groups, calendar identities and recurrences; they do not duplicate series or redraw German groups.
Foreign identities, rosters, edited recurrences and incompatible calendar settings cause an error
instead of overwriting data. Successful earlier API operations remain available after an interruption.

Defaults create PTSI and PT, 45 distinct pupils each, eight subjects, nine teachers and four
khôlleurs. All staff belong to both promotions. SI/maths teachers also teach Informatique;
SI/maths/Physique-chimie teachers also teach TIPE. Each promotion has halves, thirds, groups
of three for khôlles, and ten reproducibly sampled pupils in a named Allemand group.

The calendars **1 année** (PTSI) and **2 année** (PT) span **2026-09-07 through 2027-07-30**.
Only the PTSI calendar is filled by default; calendars initially have diffusion switched off.
Its weekly pupil volumes are maths 9 h, SI 8 h, Physique-chimie 8 h, English 2 h, Informatique
2 h, French 2 h. Both halves receive identical lab durations on the same weekdays, preserving
annual group balance even on holiday-shortened weeks. Rooms and teachers never overlap.
Each event is a one-hour pedagogical session of 55 minutes, recurring every teaching week
from the first week. Lunch is left free. Five rooms are created/reused: B208, C105, C106, D202, E301.

TIPE and khôlle sessions have no invented hourly quota. Set `german_option_hours=1` to add one
weekly German-option session; its default is zero, keeping the required core timetable at 31 h.

Zone C dates come from the [official 2026–2027 school calendar](https://www.education.gouv.fr/calendrier-scolaire-toutes-les-dates-des-cours-et-des-vacances-100148?annee=308).
The included periods are Toussaint, Christmas, winter, spring, Ascension and summer. Inclusive
end dates stop on the Sunday before a Monday resumption. Summer starts on July 3: the agenda
extends through July 30, but no courses take place after July 2. Set
`include_summer_holidays=False` to intentionally teach through July 30 instead. Other national
public holidays are not automatically inferred; add exclusions to `holidays` when needed.
Actual annual totals account for every excluded date; a holiday-shortened week is not counted
as a full week's subject hours. No alternating multiweek cycle or isolated exception is generated.

Modules: **client.py** (HTTP/session), **identities.py** (names and staff), **catalog.py**
(preflight/accounts/subjects), **groups.py** (partitions/options), **planning.py** (pure weekly
allocation), **timetables.py** (annual API writes), **runner.py** (orchestration).
