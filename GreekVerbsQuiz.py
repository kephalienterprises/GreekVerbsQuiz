#!/usr/bin/env python3
"""Εξάσκηση στη νεοελληνική κλίση ρημάτων με στατιστικά SQLite."""

from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


APP_NAME = "GreekQuiz"


def default_data_dir() -> Path:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


DB_FILENAME = "GreekVerbsQuiz.sqlite3"
DB_PATH = default_data_dir() / DB_FILENAME
LEGACY_CONFIG_PATH = Path(__file__).with_name("greek_quiz_config.json")
QUIZ_CONFIG_KEY = "quiz_config"

PERSONS = [
    ("1s", "εγώ", "α΄ ενικό"),
    ("2s", "εσύ", "β΄ ενικό"),
    ("3s", "αυτός/αυτή/αυτό", "γ΄ ενικό"),
    ("1p", "εμείς", "α΄ πληθυντικό"),
    ("2p", "εσείς", "β΄ πληθυντικό / ευγενικός τύπος"),
    ("3p", "αυτοί/αυτές/αυτά", "γ΄ πληθυντικό"),
]

COMMAND_PERSONS = [
    ("2s", "εσύ", "β΄ ενικό προστακτικής"),
    ("2p", "εσείς", "β΄ πληθυντικό / ευγενική προστακτική"),
]

HAVE_PRESENT = ["έχω", "έχεις", "έχει", "έχουμε", "έχετε", "έχουν"]
HAVE_IMPERFECT = ["είχα", "είχες", "είχε", "είχαμε", "είχατε", "είχαν"]
WANT_PRESENT = ["θέλω", "θέλεις", "θέλει", "θέλουμε", "θέλετε", "θέλουν"]
CONTINUE_PRESENT = ["συνεχίζω", "συνεχίζεις", "συνεχίζει", "συνεχίζουμε", "συνεχίζετε", "συνεχίζουν"]

CATEGORIES = {
    "present": "Ενεστώτας οριστικής",
    "past_continuous": "Παρατατικός",
    "simple_past": "Αόριστος οριστικής",
    "future_continuous": "Μέλλοντας διαρκείας",
    "future_simple": "Στιγμιαίος μέλλοντας",
    "conditional_continuous": "Υποθετικός διαρκείας",
    "present_subjunctive": "Υποτακτική ενεστώτα",
    "aorist_subjunctive": "Υποτακτική αορίστου",
    "present_perfect": "Παρακείμενος",
    "past_perfect": "Υπερσυντέλικος",
    "future_perfect": "Συντελεσμένος μέλλοντας",
    "imperative_continuous": "Προστακτική διαρκείας",
    "imperative_simple": "Στιγμιαία προστακτική",
}

PROGRESS_PERIODS = {
    "day": "date(attempted_at)",
    "week": "strftime('%Y-W%W', attempted_at)",
    "month": "strftime('%Y-%m', attempted_at)",
}

PROGRESS_PERIOD_LABELS = {
    "day": "ημέρα",
    "week": "εβδομάδα",
    "month": "μήνα",
}

COLOR_ENABLED = False


class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"


def supports_color(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never" or os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def color(text: object, *styles: str) -> str:
    rendered = str(text)
    if not COLOR_ENABLED or not styles:
        return rendered
    return f"{''.join(styles)}{rendered}{Style.RESET}"


def cell(text: object, width: int, *styles: str, align: str = "<") -> str:
    rendered = str(text)
    if len(rendered) > width:
        rendered = rendered[:width]
    if align == ">":
        rendered = rendered.rjust(width)
    else:
        rendered = rendered.ljust(width)
    return color(rendered, *styles)


def label(text: str) -> str:
    return color(text, Style.DIM)


def section(text: str) -> None:
    print(color(text, Style.BOLD, Style.CYAN))


class GreekArgumentParser(argparse.ArgumentParser):
    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "χρήση:")

    def format_help(self) -> str:
        return (
            super()
            .format_help()
            .replace("usage:", "χρήση:")
            .replace("options:", "επιλογές:")
            .replace("optional arguments:", "επιλογές:")
        )

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: σφάλμα: {message}\n")


class EmptyQuestionSelection(Exception):
    pass


@dataclass(frozen=True)
class Verb:
    lemma: str
    present: tuple[str, ...] | None = None
    imperfect: tuple[str, ...] | None = None
    aorist: tuple[str, ...] | None = None
    perfective: tuple[str, ...] | None = None
    participle: str | None = None
    imperative_continuous: tuple[str, str] | None = None
    imperative_simple: tuple[str, str] | None = None


VERBS = [
    Verb(
        "είμαι",
        present=("είμαι", "είσαι", "είναι", "είμαστε", "είστε", "είναι"),
        imperfect=("ήμουν", "ήσουν", "ήταν", "ήμασταν", "ήσασταν", "ήταν"),
    ),
    Verb(
        "έχω",
        present=("έχω", "έχεις", "έχει", "έχουμε", "έχετε", "έχουν"),
        imperfect=("είχα", "είχες", "είχε", "είχαμε", "είχατε", "είχαν"),
        imperative_continuous=("έχε", "έχετε"),
    ),
    Verb(
        "κάνω",
        present=("κάνω", "κάνεις", "κάνει", "κάνουμε", "κάνετε", "κάνουν"),
        imperfect=("έκανα", "έκανες", "έκανε", "κάναμε", "κάνατε", "έκαναν"),
        aorist=("έκανα", "έκανες", "έκανε", "κάναμε", "κάνατε", "έκαναν"),
        perfective=("κάνω", "κάνεις", "κάνει", "κάνουμε", "κάνετε", "κάνουν"),
        participle="κάνει",
        imperative_continuous=("κάνε", "κάνετε"),
        imperative_simple=("κάνε", "κάντε"),
    ),
    Verb(
        "λέω",
        present=("λέω", "λες", "λέει", "λέμε", "λέτε", "λένε"),
        imperfect=("έλεγα", "έλεγες", "έλεγε", "λέγαμε", "λέγατε", "έλεγαν"),
        aorist=("είπα", "είπες", "είπε", "είπαμε", "είπατε", "είπαν"),
        perfective=("πω", "πεις", "πει", "πούμε", "πείτε", "πουν"),
        participle="πει",
        imperative_continuous=("λέγε", "λέτε"),
        imperative_simple=("πες", "πείτε"),
    ),
    Verb(
        "πηγαίνω",
        present=("πηγαίνω", "πηγαίνεις", "πηγαίνει", "πηγαίνουμε", "πηγαίνετε", "πηγαίνουν"),
        imperfect=("πήγαινα", "πήγαινες", "πήγαινε", "πηγαίναμε", "πηγαίνατε", "πήγαιναν"),
        aorist=("πήγα", "πήγες", "πήγε", "πήγαμε", "πήγατε", "πήγαν"),
        perfective=("πάω", "πας", "πάει", "πάμε", "πάτε", "πάνε"),
        participle="πάει",
        imperative_continuous=("πήγαινε", "πηγαίνετε"),
        imperative_simple=("πήγαινε", "πηγαίνετε"),
    ),
    Verb(
        "έρχομαι",
        present=("έρχομαι", "έρχεσαι", "έρχεται", "ερχόμαστε", "έρχεστε", "έρχονται"),
        imperfect=("ερχόμουν", "ερχόσουν", "ερχόταν", "ερχόμασταν", "ερχόσασταν", "έρχονταν"),
        aorist=("ήρθα", "ήρθες", "ήρθε", "ήρθαμε", "ήρθατε", "ήρθαν"),
        perfective=("έρθω", "έρθεις", "έρθει", "έρθουμε", "έρθετε", "έρθουν"),
        participle="έρθει",
        imperative_simple=("έλα", "ελάτε"),
    ),
    Verb(
        "βλέπω",
        present=("βλέπω", "βλέπεις", "βλέπει", "βλέπουμε", "βλέπετε", "βλέπουν"),
        imperfect=("έβλεπα", "έβλεπες", "έβλεπε", "βλέπαμε", "βλέπατε", "έβλεπαν"),
        aorist=("είδα", "είδες", "είδε", "είδαμε", "είδατε", "είδαν"),
        perfective=("δω", "δεις", "δει", "δούμε", "δείτε", "δουν"),
        participle="δει",
        imperative_continuous=("βλέπε", "βλέπετε"),
        imperative_simple=("δες", "δείτε"),
    ),
    Verb(
        "ξέρω",
        present=("ξέρω", "ξέρεις", "ξέρει", "ξέρουμε", "ξέρετε", "ξέρουν"),
        imperfect=("ήξερα", "ήξερες", "ήξερε", "ξέραμε", "ξέρατε", "ήξεραν"),
    ),
    Verb(
        "θέλω",
        present=("θέλω", "θέλεις", "θέλει", "θέλουμε", "θέλετε", "θέλουν"),
        imperfect=("ήθελα", "ήθελες", "ήθελε", "θέλαμε", "θέλατε", "ήθελαν"),
        aorist=("θέλησα", "θέλησες", "θέλησε", "θελήσαμε", "θελήσατε", "θέλησαν"),
        perfective=("θελήσω", "θελήσεις", "θελήσει", "θελήσουμε", "θελήσετε", "θελήσουν"),
        participle="θελήσει",
    ),
    Verb(
        "μπορώ",
        present=("μπορώ", "μπορείς", "μπορεί", "μπορούμε", "μπορείτε", "μπορούν"),
        imperfect=("μπορούσα", "μπορούσες", "μπορούσε", "μπορούσαμε", "μπορούσατε", "μπορούσαν"),
        aorist=("μπόρεσα", "μπόρεσες", "μπόρεσε", "μπορέσαμε", "μπορέσατε", "μπόρεσαν"),
        perfective=("μπορέσω", "μπορέσεις", "μπορέσει", "μπορέσουμε", "μπορέσετε", "μπορέσουν"),
        participle="μπορέσει",
    ),
    Verb(
        "παίρνω",
        present=("παίρνω", "παίρνεις", "παίρνει", "παίρνουμε", "παίρνετε", "παίρνουν"),
        imperfect=("έπαιρνα", "έπαιρνες", "έπαιρνε", "παίρναμε", "παίρνατε", "έπαιρναν"),
        aorist=("πήρα", "πήρες", "πήρε", "πήραμε", "πήρατε", "πήραν"),
        perfective=("πάρω", "πάρεις", "πάρει", "πάρουμε", "πάρετε", "πάρουν"),
        participle="πάρει",
        imperative_continuous=("παίρνε", "παίρνετε"),
        imperative_simple=("πάρε", "πάρτε"),
    ),
    Verb(
        "δίνω",
        present=("δίνω", "δίνεις", "δίνει", "δίνουμε", "δίνετε", "δίνουν"),
        imperfect=("έδινα", "έδινες", "έδινε", "δίναμε", "δίνατε", "έδιναν"),
        aorist=("έδωσα", "έδωσες", "έδωσε", "δώσαμε", "δώσατε", "έδωσαν"),
        perfective=("δώσω", "δώσεις", "δώσει", "δώσουμε", "δώσετε", "δώσουν"),
        participle="δώσει",
        imperative_continuous=("δίνε", "δίνετε"),
        imperative_simple=("δώσε", "δώστε"),
    ),
    Verb(
        "βάζω",
        present=("βάζω", "βάζεις", "βάζει", "βάζουμε", "βάζετε", "βάζουν"),
        imperfect=("έβαζα", "έβαζες", "έβαζε", "βάζαμε", "βάζατε", "έβαζαν"),
        aorist=("έβαλα", "έβαλες", "έβαλε", "βάλαμε", "βάλατε", "έβαλαν"),
        perfective=("βάλω", "βάλεις", "βάλει", "βάλουμε", "βάλετε", "βάλουν"),
        participle="βάλει",
        imperative_continuous=("βάζε", "βάζετε"),
        imperative_simple=("βάλε", "βάλτε"),
    ),
    Verb(
        "βρίσκω",
        present=("βρίσκω", "βρίσκεις", "βρίσκει", "βρίσκουμε", "βρίσκετε", "βρίσκουν"),
        imperfect=("έβρισκα", "έβρισκες", "έβρισκε", "βρίσκαμε", "βρίσκατε", "έβρισκαν"),
        aorist=("βρήκα", "βρήκες", "βρήκε", "βρήκαμε", "βρήκατε", "βρήκαν"),
        perfective=("βρω", "βρεις", "βρει", "βρούμε", "βρείτε", "βρουν"),
        participle="βρει",
        imperative_continuous=("βρίσκε", "βρίσκετε"),
        imperative_simple=("βρες", "βρείτε"),
    ),
    Verb(
        "γίνομαι",
        present=("γίνομαι", "γίνεσαι", "γίνεται", "γινόμαστε", "γίνεστε", "γίνονται"),
        imperfect=("γινόμουν", "γινόσουν", "γινόταν", "γινόμασταν", "γινόσασταν", "γίνονταν"),
        aorist=("έγινα", "έγινες", "έγινε", "γίναμε", "γίνατε", "έγιναν"),
        perfective=("γίνω", "γίνεις", "γίνει", "γίνουμε", "γίνετε", "γίνουν"),
        participle="γίνει",
        imperative_simple=("γίνε", "γίνετε"),
    ),
    Verb(
        "τρώω",
        present=("τρώω", "τρως", "τρώει", "τρώμε", "τρώτε", "τρώνε"),
        imperfect=("έτρωγα", "έτρωγες", "έτρωγε", "τρώγαμε", "τρώγατε", "έτρωγαν"),
        aorist=("έφαγα", "έφαγες", "έφαγε", "φάγαμε", "φάγατε", "έφαγαν"),
        perfective=("φάω", "φας", "φάει", "φάμε", "φάτε", "φάνε"),
        participle="φάει",
        imperative_continuous=("τρώγε", "τρώτε"),
        imperative_simple=("φάε", "φάτε"),
    ),
    Verb(
        "πίνω",
        present=("πίνω", "πίνεις", "πίνει", "πίνουμε", "πίνετε", "πίνουν"),
        imperfect=("έπινα", "έπινες", "έπινε", "πίναμε", "πίνατε", "έπιναν"),
        aorist=("ήπια", "ήπιες", "ήπιε", "ήπιαμε", "ήπιατε", "ήπιαν"),
        perfective=("πιω", "πιεις", "πιει", "πιούμε", "πιείτε", "πιουν"),
        participle="πιει",
        imperative_continuous=("πίνε", "πίνετε"),
        imperative_simple=("πιες", "πιείτε"),
    ),
    Verb(
        "γράφω",
        present=("γράφω", "γράφεις", "γράφει", "γράφουμε", "γράφετε", "γράφουν"),
        imperfect=("έγραφα", "έγραφες", "έγραφε", "γράφαμε", "γράφατε", "έγραφαν"),
        aorist=("έγραψα", "έγραψες", "έγραψε", "γράψαμε", "γράψατε", "έγραψαν"),
        perfective=("γράψω", "γράψεις", "γράψει", "γράψουμε", "γράψετε", "γράψουν"),
        participle="γράψει",
        imperative_continuous=("γράφε", "γράφετε"),
        imperative_simple=("γράψε", "γράψτε"),
    ),
    Verb(
        "διαβάζω",
        present=("διαβάζω", "διαβάζεις", "διαβάζει", "διαβάζουμε", "διαβάζετε", "διαβάζουν"),
        imperfect=("διάβαζα", "διάβαζες", "διάβαζε", "διαβάζαμε", "διαβάζατε", "διάβαζαν"),
        aorist=("διάβασα", "διάβασες", "διάβασε", "διαβάσαμε", "διαβάσατε", "διάβασαν"),
        perfective=("διαβάσω", "διαβάσεις", "διαβάσει", "διαβάσουμε", "διαβάσετε", "διαβάσουν"),
        participle="διαβάσει",
        imperative_continuous=("διάβαζε", "διαβάζετε"),
        imperative_simple=("διάβασε", "διαβάστε"),
    ),
    Verb(
        "ακούω",
        present=("ακούω", "ακούς", "ακούει", "ακούμε", "ακούτε", "ακούνε"),
        imperfect=("άκουγα", "άκουγες", "άκουγε", "ακούγαμε", "ακούγατε", "άκουγαν"),
        aorist=("άκουσα", "άκουσες", "άκουσε", "ακούσαμε", "ακούσατε", "άκουσαν"),
        perfective=("ακούσω", "ακούσεις", "ακούσει", "ακούσουμε", "ακούσετε", "ακούσουν"),
        participle="ακούσει",
        imperative_continuous=("άκου", "ακούτε"),
        imperative_simple=("άκουσε", "ακούστε"),
    ),
    Verb(
        "μιλάω",
        present=("μιλάω", "μιλάς", "μιλάει", "μιλάμε", "μιλάτε", "μιλάνε"),
        imperfect=("μιλούσα", "μιλούσες", "μιλούσε", "μιλούσαμε", "μιλούσατε", "μιλούσαν"),
        aorist=("μίλησα", "μίλησες", "μίλησε", "μιλήσαμε", "μιλήσατε", "μίλησαν"),
        perfective=("μιλήσω", "μιλήσεις", "μιλήσει", "μιλήσουμε", "μιλήσετε", "μιλήσουν"),
        participle="μιλήσει",
        imperative_continuous=("μίλα", "μιλάτε"),
        imperative_simple=("μίλησε", "μιλήστε"),
    ),
    Verb(
        "αγαπάω",
        present=("αγαπάω", "αγαπάς", "αγαπάει", "αγαπάμε", "αγαπάτε", "αγαπάνε"),
        imperfect=("αγαπούσα", "αγαπούσες", "αγαπούσε", "αγαπούσαμε", "αγαπούσατε", "αγαπούσαν"),
        aorist=("αγάπησα", "αγάπησες", "αγάπησε", "αγαπήσαμε", "αγαπήσατε", "αγάπησαν"),
        perfective=("αγαπήσω", "αγαπήσεις", "αγαπήσει", "αγαπήσουμε", "αγαπήσετε", "αγαπήσουν"),
        participle="αγαπήσει",
        imperative_continuous=("αγάπα", "αγαπάτε"),
        imperative_simple=("αγάπησε", "αγαπήστε"),
    ),
    Verb(
        "δουλεύω",
        present=("δουλεύω", "δουλεύεις", "δουλεύει", "δουλεύουμε", "δουλεύετε", "δουλεύουν"),
        imperfect=("δούλευα", "δούλευες", "δούλευε", "δουλεύαμε", "δουλεύατε", "δούλευαν"),
        aorist=("δούλεψα", "δούλεψες", "δούλεψε", "δουλέψαμε", "δουλέψατε", "δούλεψαν"),
        perfective=("δουλέψω", "δουλέψεις", "δουλέψει", "δουλέψουμε", "δουλέψετε", "δουλέψουν"),
        participle="δουλέψει",
        imperative_continuous=("δούλευε", "δουλεύετε"),
        imperative_simple=("δούλεψε", "δουλέψτε"),
    ),
    Verb(
        "μένω",
        present=("μένω", "μένεις", "μένει", "μένουμε", "μένετε", "μένουν"),
        imperfect=("έμενα", "έμενες", "έμενε", "μέναμε", "μένατε", "έμεναν"),
        aorist=("έμεινα", "έμεινες", "έμεινε", "μείναμε", "μείνατε", "έμειναν"),
        perfective=("μείνω", "μείνεις", "μείνει", "μείνουμε", "μείνετε", "μείνουν"),
        participle="μείνει",
        imperative_continuous=("μένε", "μένετε"),
        imperative_simple=("μείνε", "μείνετε"),
    ),
    Verb(
        "φεύγω",
        present=("φεύγω", "φεύγεις", "φεύγει", "φεύγουμε", "φεύγετε", "φεύγουν"),
        imperfect=("έφευγα", "έφευγες", "έφευγε", "φεύγαμε", "φεύγατε", "έφευγαν"),
        aorist=("έφυγα", "έφυγες", "έφυγε", "φύγαμε", "φύγατε", "έφυγαν"),
        perfective=("φύγω", "φύγεις", "φύγει", "φύγουμε", "φύγετε", "φύγουν"),
        participle="φύγει",
        imperative_continuous=("φεύγε", "φεύγετε"),
        imperative_simple=("φύγε", "φύγετε"),
    ),
    Verb(
        "αγοράζω",
        present=("αγοράζω", "αγοράζεις", "αγοράζει", "αγοράζουμε", "αγοράζετε", "αγοράζουν"),
        imperfect=("αγόραζα", "αγόραζες", "αγόραζε", "αγοράζαμε", "αγοράζατε", "αγόραζαν"),
        aorist=("αγόρασα", "αγόρασες", "αγόρασε", "αγοράσαμε", "αγοράσατε", "αγόρασαν"),
        perfective=("αγοράσω", "αγοράσεις", "αγοράσει", "αγοράσουμε", "αγοράσετε", "αγοράσουν"),
        participle="αγοράσει",
        imperative_continuous=("αγόραζε", "αγοράζετε"),
        imperative_simple=("αγόρασε", "αγοράστε"),
    ),
    Verb(
        "ανοίγω",
        present=("ανοίγω", "ανοίγεις", "ανοίγει", "ανοίγουμε", "ανοίγετε", "ανοίγουν"),
        imperfect=("άνοιγα", "άνοιγες", "άνοιγε", "ανοίγαμε", "ανοίγατε", "άνοιγαν"),
        aorist=("άνοιξα", "άνοιξες", "άνοιξε", "ανοίξαμε", "ανοίξατε", "άνοιξαν"),
        perfective=("ανοίξω", "ανοίξεις", "ανοίξει", "ανοίξουμε", "ανοίξετε", "ανοίξουν"),
        participle="ανοίξει",
        imperative_continuous=("άνοιγε", "ανοίγετε"),
        imperative_simple=("άνοιξε", "ανοίξτε"),
    ),
    Verb(
        "κλείνω",
        present=("κλείνω", "κλείνεις", "κλείνει", "κλείνουμε", "κλείνετε", "κλείνουν"),
        imperfect=("έκλεινα", "έκλεινες", "έκλεινε", "κλείναμε", "κλείνατε", "έκλειναν"),
        aorist=("έκλεισα", "έκλεισες", "έκλεισε", "κλείσαμε", "κλείσατε", "έκλεισαν"),
        perfective=("κλείσω", "κλείσεις", "κλείσει", "κλείσουμε", "κλείσετε", "κλείσουν"),
        participle="κλείσει",
        imperative_continuous=("κλείνε", "κλείνετε"),
        imperative_simple=("κλείσε", "κλείστε"),
    ),
    Verb(
        "περπατάω",
        present=("περπατάω", "περπατάς", "περπατάει", "περπατάμε", "περπατάτε", "περπατάνε"),
        imperfect=("περπατούσα", "περπατούσες", "περπατούσε", "περπατούσαμε", "περπατούσατε", "περπατούσαν"),
        aorist=("περπάτησα", "περπάτησες", "περπάτησε", "περπατήσαμε", "περπατήσατε", "περπάτησαν"),
        perfective=("περπατήσω", "περπατήσεις", "περπατήσει", "περπατήσουμε", "περπατήσετε", "περπατήσουν"),
        participle="περπατήσει",
        imperative_continuous=("περπάτα", "περπατάτε"),
        imperative_simple=("περπάτησε", "περπατήστε"),
    ),
    Verb(
        "σκέφτομαι",
        present=("σκέφτομαι", "σκέφτεσαι", "σκέφτεται", "σκεφτόμαστε", "σκέφτεστε", "σκέφτονται"),
        imperfect=("σκεφτόμουν", "σκεφτόσουν", "σκεφτόταν", "σκεφτόμασταν", "σκεφτόσασταν", "σκέφτονταν"),
        aorist=("σκέφτηκα", "σκέφτηκες", "σκέφτηκε", "σκεφτήκαμε", "σκεφτήκατε", "σκέφτηκαν"),
        perfective=("σκεφτώ", "σκεφτείς", "σκεφτεί", "σκεφτούμε", "σκεφτείτε", "σκεφτούν"),
        participle="σκεφτεί",
        imperative_simple=("σκέψου", "σκεφτείτε"),
    ),
]


@dataclass(frozen=True)
class Question:
    verb: Verb
    category: str
    person_key: str
    pronoun: str
    person_label: str
    answers: tuple[str, ...]


def normalize_answer(value: str) -> str:
    value = " ".join(value.strip().lower().split())
    return unicodedata.normalize("NFC", value)


def category_match_answers(question: Question) -> set[str]:
    answers = {normalize_answer(answer) for answer in question.answers}
    for answer in question.answers:
        parts = normalize_answer(answer).split()
        for particle in ("να", "ας"):
            if parts[:1] == [particle]:
                answers.add(" ".join(parts[1:]))
            if len(parts) >= 3 and parts[1] == particle:
                answers.add(" ".join((parts[0], *parts[2:])))
    return answers


def build_answer_category_index(questions: list[Question]) -> dict[tuple[str, str, str], set[str]]:
    index: dict[tuple[str, str, str], set[str]] = {}
    for question in questions:
        for answer in category_match_answers(question):
            key = (question.verb.lemma, question.person_key, answer)
            index.setdefault(key, set()).add(question.category)
    return index


def matching_other_categories(
    question: Question,
    answer: str,
    answer_category_index: dict[tuple[str, str, str], set[str]],
) -> list[str]:
    key = (question.verb.lemma, question.person_key, normalize_answer(answer))
    categories = answer_category_index.get(key, set()) - {question.category}
    return sorted(categories, key=lambda category: CATEGORIES[category])


def finite_answers(form: str, pronoun: str) -> tuple[str, ...]:
    return (form, f"{pronoun} {form}")


def with_particle(particle: str, form: str, pronoun: str) -> tuple[str, ...]:
    phrase = f"{particle} {form}"
    return (phrase, f"{pronoun} {phrase}")


def finite_questions(verb: Verb, category: str, forms: tuple[str, ...]) -> list[Question]:
    questions = []
    for index, (person_key, pronoun, person_label) in enumerate(PERSONS):
        questions.append(
            Question(
                verb=verb,
                category=category,
                person_key=person_key,
                pronoun=pronoun,
                person_label=person_label,
                answers=finite_answers(forms[index], pronoun),
            )
        )
    return questions


def particle_questions(verb: Verb, category: str, particle: str, forms: tuple[str, ...]) -> list[Question]:
    questions = []
    for index, (person_key, pronoun, person_label) in enumerate(PERSONS):
        questions.append(
            Question(
                verb=verb,
                category=category,
                person_key=person_key,
                pronoun=pronoun,
                person_label=person_label,
                answers=with_particle(particle, forms[index], pronoun),
            )
        )
    return questions


def compound_questions(
    verb: Verb,
    category: str,
    auxiliary_forms: tuple[str, ...] | list[str],
    participle: str,
    prefix: str = "",
) -> list[Question]:
    questions = []
    for index, (person_key, pronoun, person_label) in enumerate(PERSONS):
        phrase = f"{prefix}{auxiliary_forms[index]} {participle}"
        questions.append(
            Question(
                verb=verb,
                category=category,
                person_key=person_key,
                pronoun=pronoun,
                person_label=person_label,
                answers=finite_answers(phrase, pronoun),
            )
        )
    return questions


def imperative_questions(verb: Verb, category: str, forms: tuple[str, str]) -> list[Question]:
    return [
        Question(
            verb=verb,
            category=category,
            person_key=person_key,
            pronoun=pronoun,
            person_label=person_label,
            answers=(forms[index],),
        )
        for index, (person_key, pronoun, person_label) in enumerate(COMMAND_PERSONS)
    ]


def build_questions() -> list[Question]:
    questions: list[Question] = []
    for verb in VERBS:
        if verb.present:
            questions.extend(finite_questions(verb, "present", verb.present))
            questions.extend(particle_questions(verb, "future_continuous", "θα", verb.present))
            questions.extend(particle_questions(verb, "present_subjunctive", "να", verb.present))
        if verb.imperfect:
            questions.extend(finite_questions(verb, "past_continuous", verb.imperfect))
            questions.extend(particle_questions(verb, "conditional_continuous", "θα", verb.imperfect))
        if verb.aorist:
            questions.extend(finite_questions(verb, "simple_past", verb.aorist))
        if verb.perfective:
            questions.extend(particle_questions(verb, "future_simple", "θα", verb.perfective))
            questions.extend(particle_questions(verb, "aorist_subjunctive", "να", verb.perfective))
        if verb.participle:
            questions.extend(compound_questions(verb, "present_perfect", HAVE_PRESENT, verb.participle))
            questions.extend(compound_questions(verb, "past_perfect", HAVE_IMPERFECT, verb.participle))
            questions.extend(compound_questions(verb, "future_perfect", HAVE_PRESENT, verb.participle, prefix="θα "))
        if verb.imperative_continuous:
            questions.extend(imperative_questions(verb, "imperative_continuous", verb.imperative_continuous))
        if verb.imperative_simple:
            questions.extend(imperative_questions(verb, "imperative_simple", verb.imperative_simple))
    return questions


def ensure_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempted_at TEXT NOT NULL,
            verb TEXT NOT NULL,
            category TEXT NOT NULL,
            person_key TEXT NOT NULL,
            expected TEXT NOT NULL,
            answer TEXT NOT NULL,
            correct INTEGER NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_attempts_category ON attempts(category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_attempts_verb ON attempts(verb)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_attempts_attempted_at ON attempts(attempted_at)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.commit()


def prepare_db_path(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)


def record_attempt(conn: sqlite3.Connection, question: Question, answer: str, correct: bool) -> None:
    conn.execute(
        """
        INSERT INTO attempts (
            attempted_at, verb, category, person_key, expected, answer, correct
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            question.verb.lemma,
            question.category,
            question.person_key,
            question.answers[0],
            answer,
            1 if correct else 0,
        ),
    )
    conn.commit()


def accuracy(correct: int, total: int) -> str:
    if total == 0:
        return "δ/υ"
    return f"{(correct / total) * 100:.1f}%"


def accuracy_style(correct: int, total: int) -> str:
    if total == 0:
        return Style.DIM
    percent = (correct / total) * 100
    if percent > 80:
        return Style.GREEN
    if percent >= 60:
        return Style.YELLOW
    return Style.RED


def colored_accuracy(correct: int, total: int) -> str:
    return color(accuracy(correct, total), Style.BOLD, accuracy_style(correct, total))


def print_stats(conn: sqlite3.Connection) -> None:
    total, correct = conn.execute("SELECT COUNT(*), COALESCE(SUM(correct), 0) FROM attempts").fetchone()
    section("Σύνολο")
    print(f"{color(correct, Style.GREEN)}/{total} ({colored_accuracy(correct, total)})")
    if total == 0:
        return

    print()
    section("Ανά κατηγορία")
    for category, count, category_correct in conn.execute(
        """
        SELECT category, COUNT(*), COALESCE(SUM(correct), 0)
        FROM attempts
        GROUP BY category
        ORDER BY CAST(SUM(correct) AS REAL) / COUNT(*), COUNT(*) DESC
        """
    ):
        category_label = CATEGORIES.get(category, category)
        print(
            f"  {color(category_label, Style.BLUE)}: "
            f"{color(category_correct, Style.GREEN)}/{count} "
            f"({colored_accuracy(category_correct, count)})"
        )

    print()
    section("Ανά ρήμα")
    for verb, count, verb_correct in conn.execute(
        """
        SELECT verb, COUNT(*), COALESCE(SUM(correct), 0)
        FROM attempts
        GROUP BY verb
        ORDER BY CAST(SUM(correct) AS REAL) / COUNT(*), COUNT(*) DESC, verb
        """
    ):
        print(
            f"  {color(verb, Style.MAGENTA)}: "
            f"{color(verb_correct, Style.GREEN)}/{count} ({colored_accuracy(verb_correct, count)})"
        )


def print_progress(
    conn: sqlite3.Connection,
    period: str,
    limit: int,
    categories: set[str] | None,
) -> None:
    period_expr = PROGRESS_PERIODS[period]
    limit = max(1, limit)
    category_filter = ""
    params: list[object] = []
    if categories:
        placeholders = ", ".join("?" for _ in categories)
        category_filter = f"WHERE category IN ({placeholders})"
        params.extend(sorted(categories))

    total = conn.execute(f"SELECT COUNT(*) FROM attempts {category_filter}", params).fetchone()[0]
    if total == 0:
        print(color("Δεν υπάρχουν προσπάθειες για τις επιλεγμένες κατηγορίες.", Style.YELLOW))
        return

    rows = conn.execute(
        f"""
        WITH recent_periods AS (
            SELECT {period_expr} AS period
            FROM attempts
            {category_filter}
            GROUP BY period
            ORDER BY period DESC
            LIMIT ?
        )
        SELECT {period_expr} AS period, category, COUNT(*) AS total, COALESCE(SUM(correct), 0) AS correct
        FROM attempts
        JOIN recent_periods ON recent_periods.period = {period_expr}
        {category_filter}
        GROUP BY period, category
        ORDER BY period DESC, category
        """,
        (*params, limit, *params),
    ).fetchall()

    period_label = PROGRESS_PERIOD_LABELS.get(period, period)
    section(f"Πρόοδος ανά {period_label}")
    print(label(f"Οι τελευταίες {limit} περίοδοι με προσπάθειες"))
    print(
        f"{cell('Περίοδος', 12, Style.BOLD)} "
        f"{cell('Κατηγορία', 42, Style.BOLD)} "
        f"{cell('Σκορ', 10, Style.BOLD, align='>')} "
        f"{cell('Ακρίβεια', 9, Style.BOLD, align='>')}"
    )
    print(color(f"{'-' * 12} {'-' * 42} {'-' * 10} {'-' * 9}", Style.DIM))
    for period_value, category, count, correct in rows:
        category_label = CATEGORIES.get(category, category)
        score = f"{correct}/{count}"
        print(
            f"{cell(period_value, 12, Style.CYAN)} "
            f"{cell(category_label, 42, Style.BLUE)} "
            f"{cell(score, 10, Style.GREEN, align='>')} "
            f"{cell(accuracy(correct, count), 9, Style.BOLD, accuracy_style(correct, count), align='>')}"
        )


def print_catalog(questions: list[Question]) -> None:
    section(f"{len(VERBS)} ρήματα, {len(questions)} διαθέσιμες ερωτήσεις")
    print()
    for verb in VERBS:
        categories = sorted({q.category for q in questions if q.verb == verb})
        labels = ", ".join(CATEGORIES[category] for category in categories)
        print(
            f"{cell(verb.lemma, 12, Style.MAGENTA)} "
            f"{color(labels, Style.BLUE)}"
        )


def conjugation_display(question: Question) -> str:
    person_keys = [person[0] for person in PERSONS]
    if question.category == "present_subjunctive":
        try:
            continue_form = CONTINUE_PRESENT[person_keys.index(question.person_key)]
        except ValueError:
            return f"{question.pronoun} {question.answers[0]}"
        return f"{question.pronoun} {continue_form} {question.answers[0]}"
    if question.category == "aorist_subjunctive":
        try:
            want_form = WANT_PRESENT[person_keys.index(question.person_key)]
        except ValueError:
            return f"{question.pronoun} {question.answers[0]}"
        return f"{question.pronoun} {want_form} {question.answers[0]}"
    return f"{question.pronoun} {question.answers[0]}"


def person_order(question: Question) -> int:
    ordered_keys = [person[0] for person in PERSONS] + [person[0] for person in COMMAND_PERSONS]
    try:
        return ordered_keys.index(question.person_key)
    except ValueError:
        return len(ordered_keys)


def print_conjugations(
    questions: list[Question],
    verbs: set[str] | None,
    categories: set[str] | None,
) -> None:
    selected = available_questions(questions, verbs, categories)
    if not selected:
        print(color("Δεν υπάρχουν κλίσεις για τα επιλεγμένα ρήματα/κατηγορίες.", Style.YELLOW))
        return

    section("Κλίσεις επιλεγμένων ρημάτων")
    print(f"{label('Κατηγορίες:')} {color(describe_filter(categories, CATEGORIES), Style.BLUE)}")
    print(f"{label('Ρήματα:')}     {color(describe_filter(verbs), Style.MAGENTA)}")

    for verb in VERBS:
        verb_questions = [question for question in selected if question.verb == verb]
        if not verb_questions:
            continue

        print()
        section(verb.lemma)
        for category in CATEGORIES:
            category_questions = [
                question
                for question in verb_questions
                if question.category == category
            ]
            if not category_questions:
                continue

            print(f"  {color(CATEGORIES[category], Style.BLUE, Style.BOLD)}")
            for question in sorted(category_questions, key=person_order):
                print(
                    f"    {cell(question.person_label, 40, Style.DIM)} "
                    f"{color(conjugation_display(question), Style.GREEN)}"
                )


def choose_questions(
    questions: list[Question],
    count: int,
    verbs: set[str] | None,
    categories: set[str] | None,
    rng: random.Random,
) -> list[Question]:
    filtered = available_questions(questions, verbs, categories)
    if not filtered:
        raise EmptyQuestionSelection("Δεν υπάρχουν ερωτήσεις για τα επιλεγμένα ρήματα/κατηγορίες.")
    if count <= len(filtered):
        return rng.sample(filtered, count)

    selected: list[Question] = []
    remaining = count
    while remaining >= len(filtered):
        selected.extend(rng.sample(filtered, len(filtered)))
        remaining -= len(filtered)
    if remaining:
        selected.extend(rng.sample(filtered, remaining))
    return selected


def parse_csv(values: str | None) -> set[str] | None:
    if not values:
        return None
    return {value.strip() for value in values.split(",") if value.strip()}


def saved_selection(values: object, allowed: set[str]) -> set[str] | None:
    if not isinstance(values, list):
        return None
    selected = {str(value) for value in values if str(value) in allowed}
    return selected or None


def validated_quiz_config(
    data: object,
    questions: list[Question],
    default_count: int,
) -> tuple[int, set[str] | None, set[str] | None]:
    if not isinstance(data, dict):
        return default_count, None, None

    question_count = data.get("question_count", default_count)
    if not isinstance(question_count, int) or question_count < 1:
        question_count = default_count

    allowed_verbs = {verb.lemma for verb in VERBS}
    allowed_categories = {question.category for question in questions}
    verbs = saved_selection(data.get("verbs"), allowed_verbs)
    categories = saved_selection(data.get("categories"), allowed_categories)
    return question_count, verbs, categories


def load_legacy_quiz_config(questions: list[Question], default_count: int) -> tuple[int, set[str] | None, set[str] | None] | None:
    try:
        data = json.loads(LEGACY_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return validated_quiz_config(data, questions, default_count)


def load_quiz_config(
    conn: sqlite3.Connection,
    questions: list[Question],
    default_count: int,
) -> tuple[int, set[str] | None, set[str] | None]:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (QUIZ_CONFIG_KEY,)).fetchone()
    if row:
        try:
            return validated_quiz_config(json.loads(row[0]), questions, default_count)
        except json.JSONDecodeError:
            return default_count, None, None

    legacy_config = load_legacy_quiz_config(questions, default_count)
    if legacy_config is None:
        return default_count, None, None

    question_count, verbs, categories = legacy_config
    save_quiz_config(conn, question_count, verbs, categories)
    try:
        LEGACY_CONFIG_PATH.unlink()
    except OSError:
        pass
    return legacy_config


def save_quiz_config(
    conn: sqlite3.Connection,
    question_count: int,
    verbs: set[str] | None,
    categories: set[str] | None,
) -> None:
    data = {
        "question_count": question_count,
        "verbs": sorted(verbs) if verbs else [],
        "categories": sorted(categories) if categories else [],
    }
    try:
        conn.execute(
            "REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            (QUIZ_CONFIG_KEY, json.dumps(data, ensure_ascii=False)),
        )
        conn.commit()
    except sqlite3.Error as error:
        print(color(f"Δεν ήταν δυνατή η αποθήκευση των επιλογών: {error}", Style.YELLOW))


def describe_filter(values: set[str] | None, labels: dict[str, str] | None = None) -> str:
    if not values:
        return "Όλα"
    if labels:
        return ", ".join(labels.get(value, value) for value in sorted(values))
    return ", ".join(sorted(values))


def wait_for_enter() -> None:
    input(label("\nΠάτησε Enter για επιστροφή στο μενού..."))


def prompt_menu_choice(prompt: str, choices: set[str]) -> str:
    while True:
        value = input(color(prompt, Style.BOLD)).strip().lower()
        if value in choices:
            return value
        print(color(f"Διάλεξε ένα από: {', '.join(sorted(choices))}", Style.YELLOW))


def prompt_int(prompt: str, default: int, minimum: int = 1) -> int:
    while True:
        value = input(color(f"{prompt} [{default}]: ", Style.BOLD)).strip()
        if not value:
            return default
        try:
            number = int(value)
        except ValueError:
            print(color("Πληκτρολόγησε ακέραιο αριθμό.", Style.YELLOW))
            continue
        if number >= minimum:
            return number
        print(color(f"Πληκτρολόγησε {minimum} ή μεγαλύτερο αριθμό.", Style.YELLOW))


def parse_number_selection(value: str, maximum: int) -> set[int] | None:
    indexes: set[int] = set()
    for part in value.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            if not start_text.isdigit() or not end_text.isdigit():
                return None
            start = int(start_text)
            end = int(end_text)
            if start > end:
                start, end = end, start
            indexes.update(range(start, end + 1))
        elif part.isdigit():
            indexes.add(int(part))
        else:
            return None
    if not indexes or any(index < 1 or index > maximum for index in indexes):
        return None
    return indexes


def prompt_selection(title: str, items: list[tuple[str, str]], show_keys: bool = True) -> set[str] | None:
    print()
    section(title)
    print(label("Πάτησε Enter για όλα ή γράψε αριθμούς όπως 1,3,5-8. Γράψε q για ακύρωση."))
    for index, (key, text) in enumerate(items, start=1):
        if show_keys and key != text:
            item_text = f"{color(key, Style.MAGENTA)} {label(text)}"
        else:
            item_text = color(key, Style.MAGENTA)
        if not show_keys:
            item_text = color(text, Style.MAGENTA)
        print(f"{cell(index, 3, Style.CYAN, align='>')} {item_text}")

    while True:
        value = input(color("Επιλογή: ", Style.BOLD)).strip().lower()
        if not value:
            return None
        if value == "q":
            raise KeyboardInterrupt
        indexes = parse_number_selection(value, len(items))
        if indexes is None:
            print(color("Χρησιμοποίησε αριθμούς από τη λίστα, χωρισμένους με κόμματα.", Style.YELLOW))
            continue
        return {items[index - 1][0] for index in indexes}


def available_questions(
    questions: list[Question],
    verbs: set[str] | None,
    categories: set[str] | None,
) -> list[Question]:
    return [
        question
        for question in questions
        if (verbs is None or question.verb.lemma in verbs)
        and (categories is None or question.category in categories)
    ]


def prompt_categories(questions: list[Question], selected_verbs: set[str] | None) -> set[str] | None:
    available = {question.category for question in available_questions(questions, selected_verbs, None)}
    items = [(category, CATEGORIES[category]) for category in CATEGORIES if category in available]
    return prompt_selection("Επιλογή κατηγοριών", items, show_keys=False)


def prompt_verbs(questions: list[Question], selected_categories: set[str] | None) -> set[str] | None:
    available = {question.verb.lemma for question in available_questions(questions, None, selected_categories)}
    items = [(verb.lemma, verb.lemma) for verb in VERBS if verb.lemma in available]
    return prompt_selection("Επιλογή ρημάτων", items)


def print_interactive_summary(question_count: int, verbs: set[str] | None, categories: set[str] | None) -> None:
    print()
    section("Τρέχουσες επιλογές")
    print(f"{label('Ερωτήσεις:')}  {color(question_count, Style.GREEN)}")
    print(f"{label('Κατηγορίες:')} {color(describe_filter(categories, CATEGORIES), Style.BLUE)}")
    print(f"{label('Ρήματα:')}     {color(describe_filter(verbs), Style.MAGENTA)}")


def interactive_menu(
    conn: sqlite3.Connection,
    questions: list[Question],
    default_count: int,
    rng: random.Random,
) -> int:
    question_count, selected_verbs, selected_categories = load_quiz_config(conn, questions, default_count)
    answer_index = build_answer_category_index(questions)

    while True:
        print_interactive_summary(question_count, selected_verbs, selected_categories)
        print()
        print(f"{color('1', Style.CYAN)}  Έναρξη κουίζ")
        print(f"{color('2', Style.CYAN)}  Επιλογή κατηγοριών")
        print(f"{color('3', Style.CYAN)}  Επιλογή ρημάτων")
        print(f"{color('4', Style.CYAN)}  Αριθμός ερωτήσεων")
        print(f"{color('5', Style.CYAN)}  Προβολή προόδου")
        print(f"{color('6', Style.CYAN)}  Προβολή στατιστικών")
        print(f"{color('7', Style.CYAN)}  Λίστα ρημάτων και κατηγοριών")
        print(f"{color('8', Style.CYAN)}  Προβολή κλίσεων επιλεγμένων ρημάτων")
        print(f"{color('9', Style.CYAN)}  Επαναφορά επιλογών")
        print(f"{color('q', Style.CYAN)}  Έξοδος")

        choice = prompt_menu_choice("\nΔιάλεξε επιλογή: ", {"1", "2", "3", "4", "5", "6", "7", "8", "9", "q"})
        try:
            if choice == "1":
                selected = choose_questions(questions, question_count, selected_verbs, selected_categories, rng)
                drill(conn, selected, answer_index)
                wait_for_enter()
            elif choice == "2":
                selected_categories = prompt_categories(questions, selected_verbs)
                save_quiz_config(conn, question_count, selected_verbs, selected_categories)
            elif choice == "3":
                selected_verbs = prompt_verbs(questions, selected_categories)
                save_quiz_config(conn, question_count, selected_verbs, selected_categories)
            elif choice == "4":
                question_count = prompt_int("Αριθμός ερωτήσεων", question_count)
                save_quiz_config(conn, question_count, selected_verbs, selected_categories)
            elif choice == "5":
                print()
                print_progress(conn, "day", 30, selected_categories)
                wait_for_enter()
            elif choice == "6":
                print()
                print_stats(conn)
                wait_for_enter()
            elif choice == "7":
                print()
                print_catalog(questions)
                wait_for_enter()
            elif choice == "8":
                print()
                print_conjugations(questions, selected_verbs, selected_categories)
                wait_for_enter()
            elif choice == "9":
                selected_verbs = None
                selected_categories = None
                question_count = default_count
                save_quiz_config(conn, question_count, selected_verbs, selected_categories)
                print(color("Οι επιλογές επανήλθαν.", Style.YELLOW, Style.BOLD))
            elif choice == "q":
                return 0
        except EmptyQuestionSelection as exc:
            print(color(str(exc), Style.YELLOW, Style.BOLD))
            wait_for_enter()
        except KeyboardInterrupt:
            print(color("\nΑκυρώθηκε.", Style.YELLOW))


def drill(
    conn: sqlite3.Connection,
    selected: list[Question],
    answer_category_index: dict[tuple[str, str, str], set[str]],
) -> None:
    correct_count = 0
    total = len(selected)

    for index, question in enumerate(selected, start=1):
        expected_display = " / ".join(question.answers)
        print()
        section(f"Ερώτηση {index}/{total}")
        print(
            f"{label('Ρήμα:')}       "
            f"{color(question.verb.lemma, Style.MAGENTA, Style.BOLD)}"
        )
        print(f"{label('Κατηγορία:')} {color(CATEGORIES[question.category], Style.BLUE)}")
        print(f"{label('Πρόσωπο:')}   {color(question.pronoun, Style.YELLOW)} {label(f'({question.person_label})')}")
        answer = input(color("Η απάντησή σου: ", Style.BOLD))

        accepted = {normalize_answer(value) for value in question.answers}
        correct = normalize_answer(answer) in accepted
        record_attempt(conn, question, answer, correct)

        if correct:
            correct_count += 1
            print(color("Σωστά.", Style.GREEN, Style.BOLD))
        else:
            print(
                f"{color('Όχι ακριβώς.', Style.RED, Style.BOLD)} "
                f"{label('Αναμενόμενο:')} "
                f"{color(expected_display, Style.GREEN)}"
            )
            other_categories = matching_other_categories(question, answer, answer_category_index)
            if other_categories:
                labels = ", ".join(CATEGORIES[category] for category in other_categories)
                print(f"{label('Η απάντησή σου ταιριάζει με:')} {color(labels, Style.BLUE)}.")

    print()
    section("Σκορ συνεδρίας")
    print(f"{color(correct_count, Style.GREEN)}/{total} ({colored_accuracy(correct_count, total)})")


def build_parser() -> argparse.ArgumentParser:
    parser = GreekArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("-h", "--help", action="help", help="εμφάνιση αυτού του μηνύματος και έξοδος")
    parser.add_argument("-n", "--questions", type=int, default=10, metavar="ΑΡΙΘΜΟΣ", help="αριθμός ερωτήσεων")
    parser.add_argument("--verbs", metavar="ΡΗΜΑΤΑ", help="λήμματα χωρισμένα με κόμματα, π.χ. γράφω,λέω")
    parser.add_argument("--categories", metavar="ΚΑΤΗΓΟΡΙΕΣ", help="αναγνωριστικά κατηγοριών χωρισμένα με κόμματα")
    parser.add_argument("--categories-list", action="store_true", help="εμφάνιση αναγνωριστικών κατηγοριών και έξοδος")
    parser.add_argument("--list", action="store_true", help="εμφάνιση διαθέσιμων ρημάτων/κατηγοριών και έξοδος")
    parser.add_argument("--stats", action="store_true", help="εμφάνιση αποθηκευμένων στατιστικών και έξοδος")
    parser.add_argument("--progress", action="store_true", help="εμφάνιση αποθηκευμένης προόδου ανά κατηγορία και έξοδος")
    parser.add_argument(
        "--progress-period",
        choices=sorted(PROGRESS_PERIODS),
        default="day",
        help="περίοδος ομαδοποίησης για --progress, προεπιλογή: day",
    )
    parser.add_argument(
        "--progress-limit",
        type=int,
        default=30,
        metavar="ΠΛΗΘΟΣ",
        help="πλήθος πρόσφατων περιόδων για --progress, προεπιλογή: 30",
    )
    parser.add_argument("--reset-stats", action="store_true", help="διαγραφή αποθηκευμένων προσπαθειών πριν από οτιδήποτε άλλο")
    parser.add_argument("--db", type=Path, default=DB_PATH, metavar="ΒΑΣΗ", help=f"διαδρομή βάσης SQLite, προεπιλογή: {DB_PATH}")
    parser.add_argument("--seed", type=int, metavar="ΣΠΟΡΟΣ", help="σπόρος τυχαιότητας για επαναλήψιμη εξάσκηση")
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="χρώμα στην κονσόλα: auto, always ή never, προεπιλογή: auto",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    global COLOR_ENABLED
    raw_argv = sys.argv[1:] if argv is None else argv
    launch_menu = len(raw_argv) == 0
    args = build_parser().parse_args(raw_argv)
    COLOR_ENABLED = supports_color(args.color)
    questions = build_questions()

    if args.categories_list:
        for category, category_label in CATEGORIES.items():
            print(f"{cell(category, 24, Style.MAGENTA)} {color(category_label, Style.BLUE)}")
        return 0

    if args.list:
        print_catalog(questions)
        return 0

    verbs = parse_csv(args.verbs)
    categories = parse_csv(args.categories)
    unknown_verbs = verbs - {verb.lemma for verb in VERBS} if verbs else set()
    unknown_categories = categories - set(CATEGORIES) if categories else set()
    if unknown_verbs:
        raise SystemExit(f"Άγνωστα ρήματα: {', '.join(sorted(unknown_verbs))}")
    if unknown_categories:
        raise SystemExit(f"Άγνωστα αναγνωριστικά κατηγοριών: {', '.join(sorted(unknown_categories))}")

    prepare_db_path(args.db)
    conn = sqlite3.connect(args.db)
    ensure_db(conn)

    rng = random.Random(args.seed)
    if launch_menu:
        return interactive_menu(conn, questions, args.questions, rng)

    if args.reset_stats:
        conn.execute("DELETE FROM attempts")
        conn.commit()
        print(color("Τα στατιστικά μηδενίστηκαν.", Style.YELLOW, Style.BOLD))

    if args.stats:
        print_stats(conn)
        return 0

    if args.progress:
        print_progress(conn, args.progress_period, args.progress_limit, categories)
        return 0

    try:
        selected = choose_questions(questions, args.questions, verbs, categories, rng)
    except EmptyQuestionSelection as exc:
        raise SystemExit(str(exc)) from exc
    drill(conn, selected, build_answer_category_index(questions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
