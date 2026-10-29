# Work log

Raw notes used later for the README (prompts, AI usage, bugs found and fixed).

## AI tools
- Claude Sonnet 5.5 (Anthropic) via the Claude app: design, code, tests.
- Human: runs the code, reviews it, tries to break it, decides.

## Prompts used
1. "Build a time tracking web app from this brief. Propose a stack and break the work into small steps."
   -> Result: FastAPI + SQLite + plain HTML, 8 steps.
2. "Add a step 0: system design before any code."
   -> Result: data model, rules, API list, error cases.
3. "Start." -> Result: project skeleton and database layer (app/db.py).
4. "This is my project readme file, read it, analyze it and lets start working on it" -> Result: review of the design (timestamp normalisation, injectable clock, entry-duration semantics, race on start), then service layer, routes and tests (steps 3 and 6, first part).
5. (Uploaded requirements.txt and a screenshot of the folder) "Here is the req file, and tell me where to put these files, i also attached current state of the project" -> Result: file placement; the tests were re-run on the exact pinned versions in a clean environment.
6. "I started this with uvicorn whats next?" -> Result: step 5, the UI (static/index.html), served by main.py at `/`.
7. "wait not all 40 tests passed from the previous version, on test said warning" -> Result: explained that the single warning is a library deprecation notice, not a failed test, and that 39 vs 40 was only the old test file.
8. "Everything is working without a hinch, but I didn't like the period inserter field to filter the days to see what worker did that day. Its to complicated to write on it..." -> Result: the datetime fields were replaced by date pickers, quick buttons and arrows.
9. "thats better lets move on to seed.py" -> Result: seed.py with fictional demo data, plus tests.
10. "This is my gitignore, what should I add. Also could you tell me what bugs should I look for and log them in?" -> Result: .gitignore additions; the assistant probed the running app and found five real bugs (see below).
11. "Should we add delete employee button to the ui?" -> Result: advised against a plain delete button (see design decisions); nothing was built.
12. "Lets move into readme file" -> Result: the final README.md.
13. "Yes do that then tell me what to add into log" -> Result: final check of the repository in a clean copy (all tests pass on the pinned requirements, server and seed script start), and this log update.

## Design decisions
- The period picker uses whole-day date fields, quick buttons (today, yesterday, last 7 days, this month) and arrows that move the range by its own length, because typing into datetime fields was inconvenient. "To" is included in the UI and sent to the server as the next local midnight.
- The seed data is relative to the current time, never in the future, and goes through the same service functions as the API. It deliberately includes a running timer, an employee with no entries and a shift that crosses midnight, to show clipping and the zero row. It refuses to run on a non-empty database unless `--reset` is given.
- No delete-employee button: it is not required, it would destroy recorded history with one click and no authorization, and the database foreign key forces a decision about existing entries. Listed as a possible improvement (archive or delete only employees without entries).
- Period is picked in whole local days in the UI; the server receives local midnights converted to UTC.
- Accepted years are limited to 1970-2200; names are limited to 100 and tasks to 500 characters.
- Period totals clip entries to the period boundaries (chosen over counting by start time).
- One running timer per employee, enforced by a unique partial index in the database.
- All times stored in UTC.
- `from`/`to` query values are parsed and converted to the storage format before comparison; a value without a time zone is treated as UTC.
- Entries show their full `duration_seconds` and the clipped `counted_seconds`; the total is the sum of the clipped part.
- Service functions take an optional `now` so tests can control the clock.
- One database connection per request (a shared connection is not safe across threads).
- Known limitation: `COLLATE NOCASE` only folds ASCII letters, so "Иван" and "иван" count as different employees (verified by running it).

## Human review
- The human ran the interface in the browser after the UI was built: everything worked, and the only complaint was the period field (changed, see design decisions).
- The human ran `pytest` on Windows (Python 3.12.5, pytest 8.3.3): 39 passed with one deprecation warning from starlette/anyio, which is not a failure. That run was before the UI test and the bug-fix tests were added.

## Bugs found and fixed
Found in a review pass where the assistant sent adversarial requests to the running app (extreme ids, dates, text). Each was reproduced first with a failing test, then fixed. The human should re-run these before submitting.

1. **Huge employee id crashed with HTTP 500.**
   Wrong: `GET /employees/99999999999999999999/entries` (and start/stop) raised an OverflowError, because Python integers larger than 2^63-1 cannot be bound to an SQLite integer.
   Found: probe request returned 500; test `test_huge_employee_id_is_not_found_not_a_crash`.
   Fix: `_employee_row` treats ids outside 1..2^63-1 as "not found" (404).
2. **Extreme dates crashed with HTTP 500.**
   Wrong: `to=9999-12-31T23:59:59-05:00` and `from=0001-01-01T00:00:00+05:00` overflowed while converting to UTC.
   Found: probe requests returned 500; test `test_extreme_years_are_rejected`.
   Fix: `normalize_time` catches the overflow and returns 422.
3. **Years below 1000 silently broke the time comparison.**
   Wrong: `from=0999-01-01T00:00:00Z` was accepted and stored as `999-01-01...` (no zero padding on this platform). The fixed-width format that makes string comparison correct was broken, so `from` sorted after every 2026 entry and the report showed 0 hours with no error.
   Found: the probe echoed `"from":"999-01-01T00:00:00.000000Z"`.
   Fix: only years 1970 to 2200 are accepted, anything else is 422.
4. **A name of only invisible characters was accepted.**
   Wrong: a name made of a zero-width space passed the "not empty" check (`strip()` does not remove it) and created an employee that looks blank in the UI.
   Found: probe returned 201; test `test_name_made_only_of_invisible_characters_is_rejected`.
   Fix: names and tasks must contain at least one visible character.
5. **No length limit on names and tasks.**
   Wrong: a 100,000-character task was accepted and would break the page layout.
   Found: probe returned 201; test `test_too_long_name_and_task_are_rejected`.
   Fix: names are limited to 100 characters and tasks to 500 (422 above that), and the UI inputs have the same `maxlength`.

Checked and fine: 20 simultaneous start requests for one employee gave exactly one 201 and nineteen 409 (the database index plus the IntegrityError handling).

## Known limitations
- `COLLATE NOCASE` only folds ASCII letters, so "Иван" and "иван" count as different employees.
- In a raw URL a `+` offset must be written as `%2B` (or use `Z`): `from=2026-10-28T14:00:00+05:00` is read as a space and rejected with 422. The UI always sends `Z`, so it is not affected.
- The records table does not refresh by itself while a timer runs (the clock does).