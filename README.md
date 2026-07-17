# Modern Greek Conjugation Quiz

A small Python console app for drilling common Modern Greek verb forms. It uses only the Python standard library and saves every attempt to SQLite.

## Run

```bash
python3 GreekVerbsQuiz.py
```

Running the script with no options opens an interactive menu. From there you can choose categories, choose words, set the quiz length, start a quiz, view progress, view stats, or list the available prompts. This is the same flow you get when double-clicking the `.py` file.

Useful options:

```bash
python3 GreekVerbsQuiz.py -n 20 --categories present,simple_past
python3 GreekVerbsQuiz.py --stats
python3 GreekVerbsQuiz.py --progress
python3 GreekVerbsQuiz.py --progress --progress-period week --progress-limit 12
python3 GreekVerbsQuiz.py --progress --categories simple_past,future_simple
python3 GreekVerbsQuiz.py --list
python3 GreekVerbsQuiz.py --categories-list
python3 GreekVerbsQuiz.py --color always
python3 GreekVerbsQuiz.py --verbs γράφω,λέω --categories simple_past,future_simple
```

The default database is stored in the user's app data folder. On Windows, that is `%APPDATA%\GreekQuiz\GreekVerbsQuiz.sqlite3`. It stores both stats and your last selected categories, words, and quiz length. Use `--db path/to/file.sqlite3` to store everything somewhere else.

`--stats` shows your overall accuracy by category and verb. `--progress` shows accuracy over time by category, grouped by day by default. Use `--progress-period day`, `week`, or `month` to change the time bucket, and `--progress-limit` to control how many recent periods are shown.

Console output is colorized automatically in terminals. Use `--color always` to force ANSI colors or `--color never` to disable them.

## What It Drills

The app includes 30 high-frequency verbs and prompts across the categories that are available for each verb:

- Ενεστώτας οριστικής (present indicative)
- Παρατατικός (past continuous / imperfect indicative)
- Αόριστος οριστικής (simple past / aorist indicative)
- Μέλλοντας διαρκείας (continuous future)
- Στιγμιαίος μέλλοντας (simple future)
- Υποθετικός διαρκείας (conditional / would be doing)
- Υποτακτική ενεστώτα (present subjunctive)
- Υποτακτική αορίστου (aorist subjunctive)
- Παρακείμενος (present perfect)
- Υπερσυντέλικος (past perfect)
- Συντελεσμένος μέλλοντας (future perfect)
- Προστακτική διαρκείας (continuous imperative)
- Στιγμιαία προστακτική (simple imperative)

Answers are checked case-insensitively, but accents are required. For finite forms, both the bare verb phrase and the pronoun plus verb phrase are accepted, for example `γράφω` and `εγώ γράφω`.

Some verbs naturally do not have every category in common use, so the quiz skips unavailable forms instead of forcing rare or awkward conjugations.
