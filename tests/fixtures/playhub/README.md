`event_174256.html` is a reduced regression fixture derived from the public
Play Hub event page downloaded on 2026-09-13. It retains only the event ID
and description, serialized in the observed Next.js `self.__next_f.push`
envelope. It is not a full copy of the page. The adjacent JSON file contains
the expected decoded values. The old replacement-based parser fails on
this description's escaped newlines.

Run the isolated, offline parser tests from the repository root:

```sh
python -B -m unittest discover -s tests -v
```

The former `test_database.py` is now `experiments.legacy_database_sample`;
it is not an automated test and writes against the configured database.
