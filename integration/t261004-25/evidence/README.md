# t261004-25 evidence — quarantined deliverable of t261004-18

Why these files are here (integration role, main side, 261004):

`t261004-18` delivered `server/engine/tests/test_t261004_18_grants_write_entry.py`
as its engine-side unit test. The stage path gate judged that path out of the
frozen write set (`server/engine/executor_grants.py`, `server/engine/client.py`,
`server/plugins/executor-panel/`, `integration/`) and moved the file aside five
times; each move left a copy under
`.lane/t261004-18/.sandbar/quarantine/unauth-implement-gen0*/server/engine/tests/`.
The file never reached a commit, so lane cleanup would destroy the only copies.

Preserved here as text (`.py.txt`, not collected by pytest or the scenario
registry) so the content survives lane cleanup and the carrier ticket can restore
it as a real test once the entry points are on main:

- `t261004-18_grants_write_entry.py.txt` — newest copy (quarantine gen0-5, 5090 B,
  md5 376a546f799fa230758d4ffd6fffb3a8)
- `t261004-18_grants_write_entry.gen0.py.txt` — first copy (quarantine gen0, 4620 B,
  md5 cdc41ba069d69d78ac83937ef4f8cccc), kept for comparison of the five generations

Same class, second instance: `t261004-19`'s engine test
`server/engine/tests/test_t261004_19_open_ticket_gate.py` IS committed on
`lane/t261004-19` (12772 B) and is refused by merge_check for the same reason.
Both are carried to main by t261004-28.
