"""Canonical temporal state for availability and booking.

The rule this module exists to enforce: **the LLM may interpret, deterministic
code decides.** A patient's message is the source of truth for *what date they
asked for*; the NLU is allowed to enrich and normalize, never to invent.

That distinction is not theoretical. Production logs for "book me with dr aris
16 nov friday" show the model emitting ``2023-11-17`` — it moved the patient's
day from the 16th to the 17th so the weekday would line up with a year the
patient never mentioned. For "16 oct friday" it emitted ``2023-10-16``, which
is a Monday. Any design that lets a value like that reach the availability
query can book someone on a date they did not request.

So candidates come from two sources with different trust levels:

* `scan_temporal_expressions()` reads the message directly. Whatever it finds
  is grounded by construction — the patient typed it.
* the NLU's `date` entities, which are checked component-by-component against
  the message before being believed.

They are then ranked by `TemporalPrecision` first, so an explicit calendar
date always outranks a weekday, a month, or a relative expression mentioned in
the same breath. The winner becomes one `TemporalQuery` that the SQL scan, the
response text, the UI chips, and the booking wizard all consume — none of them
re-derive a date of their own.
"""

from __future__ import annotations

import calendar
import difflib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum, IntEnum
from typing import Iterator, Sequence
from zoneinfo import ZoneInfo


class TemporalStatus(str, Enum):
    """Why the availability layer can (or cannot) run a search."""

    RESOLVED = "resolved"
    # No constraint given, or an explicitly flexible one ("asap") — the
    # patient is asking us to choose, so a forward scan is the right answer.
    UNSPECIFIED = "unspecified"
    # A constraint was given and could not be read. Ask; never substitute.
    UNRESOLVED = "unresolved"
    # Readable but not decidable ("tuesday 2" — no Tuesday the 2nd is near).
    AMBIGUOUS = "ambiguous"
    PAST = "past"
    BEYOND_HORIZON = "beyond_horizon"


class TemporalPrecision(IntEnum):
    """How specific a candidate is. Lower sorts first.

    This ordering *is* the "explicit date wins" invariant. Encoding it as a
    property of the candidate rather than a chain of special cases is what
    keeps "16 oct friday" meaning October 16 when new expression types get
    added later.
    """

    EXPLICIT_DATE = 0
    MONTH = 1
    WEEKDAY = 2
    RELATIVE = 3
    FLEXIBLE = 4


# How far ahead "tuesday 25" is allowed to look for a Tuesday that falls on a
# 25th. Deliberately not the booking horizon: what a phrase *means* must not
# change when a clinic edits its configuration.
_ORDINAL_SEARCH_DAYS = 62


@dataclass(frozen=True)
class TemporalQuery:
    """The one temporal fact a turn is allowed to act on.

    `start`/`end` are inclusive and already clamped to today and the clinic's
    booking horizon. `scope_label` describes what the patient asked for
    *before* clamping, which is what we say back to them.
    """

    status: TemporalStatus
    start: date | None = None
    end: date | None = None
    is_range: bool = False
    precision: TemporalPrecision | None = None
    requested_text: str = ""
    scope_label: str = ""
    horizon_end: date | None = None
    # Patient named a weekday that disagrees with the date they also named
    # ("16 nov friday" — November 16 2026 is a Monday). The date wins; this
    # records the disagreement so the reply can own it.
    conflict: bool = False
    conflict_weekday: str = ""

    @property
    def searchable(self) -> bool:
        return (
            self.status in (TemporalStatus.RESOLVED, TemporalStatus.UNSPECIFIED)
            and self.start is not None
            and self.end is not None
        )

    def iter_days(self) -> Iterator[date]:
        if self.start is None or self.end is None:
            return
        day = self.start
        while day <= self.end:
            yield day
            day += timedelta(days=1)

    def covers(self, day: date | str | None) -> bool:
        """True when `day` falls inside the resolved scope.

        Accepts an ISO string so row payloads can be checked without parsing.
        """
        if self.start is None or self.end is None or day is None:
            return False
        if isinstance(day, str):
            try:
                day = date.fromisoformat(day[:10])
            except ValueError:
                return False
        return self.start <= day <= self.end

    def as_meta(self) -> dict[str, str | bool]:
        """Scope carried on the SQL block so every downstream layer — text,
        chips, booking — answers to the same resolved state."""
        meta: dict[str, str | bool] = {
            "temporal_status": self.status.value,
            "temporal_is_range": self.is_range,
            "temporal_searchable": self.searchable,
        }
        if self.precision is not None:
            meta["temporal_precision"] = self.precision.name.lower()
        if self.start:
            meta["scope_start"] = self.start.isoformat()
        if self.end:
            meta["scope_end"] = self.end.isoformat()
        if self.scope_label:
            meta["scope_label"] = self.scope_label
        if self.requested_text:
            meta["requested_text"] = self.requested_text
        if self.horizon_end:
            meta["horizon_end"] = self.horizon_end.isoformat()
        if self.conflict:
            meta["temporal_conflict"] = True
            if self.conflict_weekday:
                meta["conflict_weekday"] = self.conflict_weekday
        return meta


def day_label(day: date, *, today: date | None = None) -> str:
    """"Saturday, December 12" — weekday always computed, never quoted.

    The year is appended when it isn't the current one, so "December 12, 2023"
    and "December 12, 2025" don't both render as bare "December 12".
    """
    label = f"{day.strftime('%A')}, {day.strftime('%B')} {day.day}"
    if today is not None and day.year != today.year:
        label += f", {day.year}"
    return label


def _month_label(day: date) -> str:
    return f"{day.strftime('%B')} {day.year}"


_MONTHS: dict[str, int] = {}
for _i in range(1, 13):
    _MONTHS[calendar.month_name[_i].lower()] = _i
    _MONTHS[calendar.month_abbr[_i].lower()] = _i
_MONTHS["sept"] = 9

_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_MONTH_FULL_NAMES = [calendar.month_name[i].lower() for i in range(1, 13)]

_WEEKDAYS: dict[str, int] = {}
for _i in range(7):
    _WEEKDAYS[calendar.day_name[_i].lower()] = _i
_WEEKDAYS.update(
    {
        "mon": 0, "tue": 1, "tues": 1, "wed": 2, "weds": 2,
        "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6,
    }
)
_WEEKDAY_ALT = "|".join(sorted(_WEEKDAYS, key=len, reverse=True))

# Free-text weekday spotting drops the abbreviations that collide with real
# words — "sun damage", "she sat down", "we got wed". Same tiering as
# entity_extract.py; a false Sunday here would invent a weekday conflict.
_WEEKDAY_SAFE = {
    name: num
    for name, num in _WEEKDAYS.items()
    if name not in {"sun", "sat", "wed"}
}
_WEEKDAY_SAFE_ALT = "|".join(sorted(_WEEKDAY_SAFE, key=len, reverse=True))

_SEP = r"[-/.\s]+"
# A trailing "-202" is a mistyped year, not a date we may quietly complete.
_NO_TRAILING_NUMBER = r"(?![-/.]\s*\d)"

_ISO_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_D_MON_Y_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?{_SEP}({_MONTH_ALT}){_SEP}(\d{{4}})\b"
)
_MON_D_Y_RE = re.compile(
    rf"\b({_MONTH_ALT}){_SEP}(\d{{1,2}})(?:st|nd|rd|th)?[,\s]+(\d{{4}})\b"
)
_D_MON_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?{_SEP}({_MONTH_ALT})\b{_NO_TRAILING_NUMBER}"
)
# "13-January-202" — a half-typed year. Matched only so its span can be
# consumed: without that the bare-month sweep would read the leftover
# "January" as a whole-month request the patient never made.
_MALFORMED_YEAR_RE = re.compile(
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?{_SEP}(?:{_MONTH_ALT}){_SEP}\d{{1,3}}\b"
)
_MON_D_RE = re.compile(
    rf"\b({_MONTH_ALT}){_SEP}(\d{{1,2}})(?:st|nd|rd|th)?\b{_NO_TRAILING_NUMBER}"
)
# "May" is a month and an ordinary verb. Bare month scanning therefore skips
# it unless a qualifier makes the calendar reading unambiguous, so "may I book
# something" never becomes a May date range.
_MONTH_ALT_UNQUALIFIED = "|".join(
    sorted((m for m in _MONTHS if m != "may"), key=len, reverse=True)
)
_MONTH_QUALIFIER = r"(?:in|for|during|coming|next|this|of|about|around)"
_QUALIFIED_MONTH_RE = re.compile(rf"\b{_MONTH_QUALIFIER}\s+({_MONTH_ALT})\b")
_BARE_MONTH_IN_TEXT_RE = re.compile(rf"\b({_MONTH_ALT_UNQUALIFIED})\b")

# "tuesday 25" / "25 tuesday" — a weekday pinned to a day-of-month. Excluded
# when the number reads as a clock time ("tuesday at 2", "tuesday 2pm").
_WD_ORDINAL_RE = re.compile(
    rf"\b({_WEEKDAY_ALT})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!\s*(?::|\d|am|pm|a\.m|p\.m|o'?clock))"
)
_ORDINAL_WD_RE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_WEEKDAY_ALT})\b")

_RELATIVE_WORDS = (
    "today", "tonight", "tomorrow", "tmrw", "yesterday", "week", "weekend",
    "asap", "soonest", "earliest", "next available", "same day", "month",
)

# Entity strings that mean "you pick" rather than naming a time.
_FLEXIBLE = {
    "asap", "as soon as possible", "soonest", "earliest",
    "next available", "next available slot", "next opening",
    "anytime", "any time", "any day", "whenever", "flexible",
    "instantly", "immediately", "right away",
}
# Phrases that mean "you pick", not "I named a date we failed to read".
# looks_temporal must ignore them: otherwise "when is dr maya available
# earliest" is flagged as a constraint, no candidate is produced (NLU sent
# date=null; the scanner does not emit FLEXIBLE), and the resolver asks
# which January 2027 they meant.
_FLEXIBLE_RE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(p) for p in sorted(_FLEXIBLE, key=len, reverse=True))
    + r")\b"
)
_YESTERDAY_RE = re.compile(r"\byesterday\b")
_TODAY_WORDS = {"same day", "sameday", "today", "now", "right now"}

_BARE_MONTH_RE = re.compile(
    rf"^(?:in\s+|during\s+|for\s+|coming\s+|next\s+|this\s+)?({_MONTH_ALT})\s*(\d{{4}})?$"
)


@dataclass(frozen=True)
class _Candidate:
    raw: str
    start: date
    end: date
    is_range: bool
    precision: TemporalPrecision
    label: str
    grounded: bool = False
    weekday_hint: int | None = None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _end_of_month(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _roll_forward(day: date, today: date) -> date:
    """A month/day with no year always means the next one to occur."""
    if day >= today:
        return day
    try:
        return day.replace(year=day.year + 1)
    except ValueError:  # Feb 29
        return day.replace(year=day.year + 1, day=28)


def looks_temporal(message: str) -> bool:
    """Does this message contain something the patient meant as a date?

    Used only to decide between "they told us nothing" (UNSPECIFIED, forward
    scan) and "they told us something we couldn't read" (UNRESOLVED, ask).
    Deliberately fuzzy on spelling — "coming januray" is a temporal constraint
    even though no parser will ever resolve it — and deliberately blind to
    bare numbers, which are far more often quantities than dates.
    """
    msg = _norm(message)
    if not msg:
        return False
    # Flexible words are temporal, but they are not a constraint we failed
    # to parse — they are a request to scan forward. Strip them before the
    # "did they name a date?" check so they cannot collapse into UNRESOLVED.
    msg = _norm(_FLEXIBLE_RE.sub(" ", msg))
    if not msg:
        return False
    if _ISO_RE.search(msg) or _D_MON_RE.search(msg) or _MON_D_RE.search(msg):
        return True
    if any(word in msg for word in _RELATIVE_WORDS):
        return True
    tokens = [t for t in re.split(r"[^a-z]+", msg) if len(t) >= 3]
    for token in tokens:
        # "may" excluded for the same reason the bare-month sweep skips it.
        if token == "may":
            continue
        if token in _MONTHS or token in _WEEKDAY_SAFE:
            return True
    # Misspellings: "januray", "feburary", "wendsday".
    long_tokens = [t for t in tokens if len(t) >= 5]
    vocabulary = _MONTH_FULL_NAMES + list(calendar.day_name)
    vocabulary = [v.lower() for v in vocabulary]
    for token in long_tokens:
        if difflib.get_close_matches(token, vocabulary, n=1, cutoff=0.8):
            return True
    return False


def _iso_grounded(year: int, month: int, dom: int, message: str) -> bool:
    """Is an ISO date faithful to the message, component by component?

    Literal token matching fails here: "13-January-2024" normalizes to
    "2024-01-13", and the zero-padded "01" appears nowhere in the text even
    though the patient plainly said January. Each component is therefore
    checked in every form it could have been written.
    """
    msg = _norm(message)
    if str(year) not in msg:
        return False
    if not re.search(rf"\b0?{dom}\b", msg):
        return False
    month_forms = [
        calendar.month_name[month].lower(),
        calendar.month_abbr[month].lower(),
        f"0{month}" if month < 10 else str(month),
        str(month),
    ]
    return any(
        re.search(rf"\b{re.escape(form)}", msg) for form in month_forms
    )


def _is_grounded(raw: str, message: str) -> bool:
    """Did the patient actually write this expression?

    ISO dates go through component checking; everything else must appear
    token-for-token. With no message to check against we assume grounded
    rather than discard every candidate.
    """
    msg = _norm(message)
    if not msg:
        return True
    raw_n = _norm(raw)
    iso = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw_n)
    if iso:
        return _iso_grounded(
            int(iso.group(1)), int(iso.group(2)), int(iso.group(3)), message
        )
    if raw_n and raw_n in msg:
        return True
    tokens = [t for t in re.split(r"[^a-z0-9]+", raw_n) if t]
    if not tokens:
        return False
    return all(re.search(rf"\b{re.escape(tok)}", msg) for tok in tokens)


def _explicit_day(
    raw: str, day: date, today: date, *, grounded: bool
) -> _Candidate:
    return _Candidate(
        raw=raw,
        start=day,
        end=day,
        is_range=False,
        precision=TemporalPrecision.EXPLICIT_DATE,
        label=day_label(day, today=today),
        grounded=grounded,
    )


def scan_temporal_expressions(
    message: str, *, today: date, tz: ZoneInfo | None = None
) -> tuple[list[_Candidate], bool]:
    """Read dates straight out of the patient's message.

    Returns (candidates, ambiguous). Everything produced here is grounded by
    definition, which is what lets it outrank a model normalization without
    having to trust the model at all.
    """
    msg = _norm(message)
    if not msg:
        return [], False

    candidates: list[_Candidate] = []
    consumed: list[tuple[int, int]] = []

    def overlaps(span: tuple[int, int]) -> bool:
        return any(span[0] < e and span[1] > s for s, e in consumed)

    for match in _MALFORMED_YEAR_RE.finditer(msg):
        consumed.append(match.span())

    for match in _ISO_RE.finditer(msg):
        if overlaps(match.span()):
            continue
        try:
            day = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            continue
        consumed.append(match.span())
        candidates.append(_explicit_day(match.group(0), day, today, grounded=True))

    for pattern, order in ((_D_MON_Y_RE, "dmy"), (_MON_D_Y_RE, "mdy")):
        for match in pattern.finditer(msg):
            if overlaps(match.span()):
                continue
            if order == "dmy":
                dom, month, year = (
                    int(match.group(1)),
                    _MONTHS[match.group(2)],
                    int(match.group(3)),
                )
            else:
                month, dom, year = (
                    _MONTHS[match.group(1)],
                    int(match.group(2)),
                    int(match.group(3)),
                )
            try:
                day = date(year, month, dom)
            except ValueError:
                continue
            consumed.append(match.span())
            candidates.append(
                _explicit_day(match.group(0), day, today, grounded=True)
            )

    # Year-less month/day. The year is filled in by rolling forward from
    # today — never taken from a model normalization, which has been observed
    # shifting the day to make its own wrong year self-consistent.
    for pattern, order in ((_D_MON_RE, "dm"), (_MON_D_RE, "md")):
        for match in pattern.finditer(msg):
            if overlaps(match.span()):
                continue
            if order == "dm":
                dom, month = int(match.group(1)), _MONTHS[match.group(2)]
            else:
                month, dom = _MONTHS[match.group(1)], int(match.group(2))
            try:
                day = date(today.year, month, dom)
            except ValueError:
                continue
            consumed.append(match.span())
            candidates.append(
                _explicit_day(
                    match.group(0), _roll_forward(day, today), today, grounded=True
                )
            )

    ambiguous = False
    for pattern, order in ((_WD_ORDINAL_RE, "wd"), (_ORDINAL_WD_RE, "dw")):
        for match in pattern.finditer(msg):
            if overlaps(match.span()):
                continue
            if order == "wd":
                weekday, dom = _WEEKDAYS[match.group(1)], int(match.group(2))
            else:
                dom, weekday = int(match.group(1)), _WEEKDAYS[match.group(2)]
            if not 1 <= dom <= 31:
                continue
            found = None
            for offset in range(0, _ORDINAL_SEARCH_DAYS + 1):
                probe = today + timedelta(days=offset)
                if probe.day == dom and probe.weekday() == weekday:
                    found = probe
                    break
            consumed.append(match.span())
            if found is None:
                # "tuesday 2" — no Tuesday the 2nd is anywhere near. Guessing
                # "next Tuesday" would answer a question nobody asked.
                ambiguous = True
            else:
                candidates.append(
                    _explicit_day(match.group(0), found, today, grounded=True)
                )

    for pattern in (_QUALIFIED_MONTH_RE, _BARE_MONTH_IN_TEXT_RE):
        for match in pattern.finditer(msg):
            if overlaps(match.span()):
                continue
            month = _MONTHS[match.group(1)]
            start = date(today.year, month, 1)
            end = _end_of_month(today.year, month)
            # "November" asked in December means next November.
            if end < today:
                start = date(today.year + 1, month, 1)
                end = _end_of_month(today.year + 1, month)
            consumed.append(match.span())
            candidates.append(
                _Candidate(
                    raw=match.group(1),
                    start=start,
                    end=end,
                    is_range=True,
                    precision=TemporalPrecision.MONTH,
                    label=_month_label(start),
                    grounded=True,
                )
            )

    # "yesterday" is a concrete relative day, not an unreadable constraint.
    # parse_natural_date used to return None for it, so a well-extracted NLU
    # entity still died as UNRESOLVED. Scan it here so the message itself
    # is enough even when the NLU sends date=null.
    for match in _YESTERDAY_RE.finditer(msg):
        if overlaps(match.span()):
            continue
        day = today - timedelta(days=1)
        consumed.append(match.span())
        candidates.append(
            _Candidate(
                raw=match.group(0),
                start=day,
                end=day,
                is_range=False,
                precision=TemporalPrecision.RELATIVE,
                label=day_label(day, today=today),
                grounded=True,
            )
        )

    return candidates, ambiguous


def _local_date_entities(message: str) -> list[str]:
    """Weekdays and relative expressions, via the deterministic extractor.

    Reused rather than re-implemented: entity_extract.py already carries the
    collision tiering that keeps "sun damage" from reading as Sunday, and a
    second copy of those rules would drift from it.
    """
    from apps.chatbot.nlu.entity_extract import extract_entities

    try:
        found = extract_entities(message).get("date")
    except Exception:
        return []
    if not found:
        return []
    if isinstance(found, list):
        return [str(f) for f in found if str(f).strip()]
    return [str(found)] if str(found).strip() else []


def _parse_entity(
    raw: str, *, today: date, tz: ZoneInfo | None
) -> _Candidate | None:
    """One NLU date entity -> one candidate, or None if unreadable."""
    # Imported lazily: sql_tool's package __init__ pulls in the handlers, one
    # of which imports this module. A module-level import here deadlocks
    # whenever anything imports apps.chatbot.temporal first.
    from apps.chatbot.sql_tool.utils import parse_natural_date

    text = _norm(raw)
    if not text:
        return None

    if text in _FLEXIBLE:
        return _Candidate(
            raw=raw,
            start=today,
            end=today,
            is_range=True,
            precision=TemporalPrecision.FLEXIBLE,
            label="",
        )
    if text in _TODAY_WORDS:
        return _Candidate(
            raw=raw,
            start=today,
            end=today,
            is_range=False,
            precision=TemporalPrecision.RELATIVE,
            label=day_label(today, today=today),
        )
    if text == "yesterday":
        # Use the resolver's `today`, not parse_natural_date's wall clock —
        # tests freeze today, and a production call already computed clinic-local
        # today before it got here.
        day = today - timedelta(days=1)
        return _Candidate(
            raw=raw,
            start=day,
            end=day,
            is_range=False,
            precision=TemporalPrecision.RELATIVE,
            label=day_label(day, today=today),
        )
    if text in {"tomorrow", "tmrw"}:
        day = today + timedelta(days=1)
        return _Candidate(
            raw=raw,
            start=day,
            end=day,
            is_range=False,
            precision=TemporalPrecision.RELATIVE,
            label=day_label(day, today=today),
        )

    scanned, _ = scan_temporal_expressions(text, today=today, tz=tz)
    explicit = [c for c in scanned if c.precision <= TemporalPrecision.MONTH]
    if explicit:
        best = min(explicit, key=lambda c: (c.precision, c.start))
        return _Candidate(
            raw=raw,
            start=best.start,
            end=best.end,
            is_range=best.is_range,
            precision=best.precision,
            label=best.label,
        )

    bare = _BARE_MONTH_RE.match(text)
    if bare:
        month = _MONTHS[bare.group(1)]
        year = int(bare.group(2)) if bare.group(2) else today.year
        start, end = date(year, month, 1), _end_of_month(year, month)
        if not bare.group(2) and end < today:
            start, end = date(year + 1, month, 1), _end_of_month(year + 1, month)
        return _Candidate(
            raw=raw,
            start=start,
            end=end,
            is_range=True,
            precision=TemporalPrecision.MONTH,
            label=_month_label(start),
        )

    parsed = parse_natural_date(raw, tz=tz)
    if parsed is None:
        return None
    weekday_hint = _WEEKDAYS.get(text)
    return _Candidate(
        raw=raw,
        start=parsed,
        end=parsed,
        is_range=False,
        precision=(
            TemporalPrecision.WEEKDAY
            if weekday_hint is not None
            else TemporalPrecision.RELATIVE
        ),
        label=day_label(parsed, today=today),
        weekday_hint=weekday_hint,
    )


def _stated_weekdays(message: str, candidates: Sequence[_Candidate]) -> set[int]:
    stated = {c.weekday_hint for c in candidates if c.weekday_hint is not None}
    for match in re.finditer(rf"\b({_WEEKDAY_SAFE_ALT})\b", _norm(message)):
        stated.add(_WEEKDAY_SAFE[match.group(1)])
    return {w for w in stated if w is not None}


def resolve_temporal_query(
    *,
    date_entities: Sequence[str],
    today: date,
    horizon_days: int,
    message: str = "",
    tz: ZoneInfo | None = None,
) -> TemporalQuery:
    """Collapse everything the turn knows about time into one validated scope.

    Entity ordering is deliberately ignored. Candidates are ranked by
    precision first, then by whether the patient actually said them.
    """
    horizon_end = today + timedelta(days=max(int(horizon_days), 0))

    raw_entities = [str(e).strip() for e in (date_entities or []) if str(e).strip()]
    candidates: list[_Candidate] = []

    # Source 1 — the message itself. Grounded by construction.
    scanned, scanner_ambiguous = scan_temporal_expressions(
        message, today=today, tz=tz
    )
    candidates.extend(scanned)

    # Source 2 — deterministic local extraction of weekdays and relative
    # expressions. Also grounded: it only ever reports what it read.
    for raw in _local_date_entities(message):
        cand = _parse_entity(raw, today=today, tz=tz)
        if cand is not None:
            candidates.append(
                _Candidate(
                    raw=cand.raw,
                    start=cand.start,
                    end=cand.end,
                    is_range=cand.is_range,
                    precision=cand.precision,
                    label=cand.label,
                    grounded=True,
                    weekday_hint=cand.weekday_hint,
                )
            )

    # Source 3 — the NLU. Lowest trust: believed only where the patient's own
    # words back it up, component by component.
    for raw in raw_entities:
        cand = _parse_entity(raw, today=today, tz=tz)
        if cand is None:
            continue
        candidates.append(
            _Candidate(
                raw=cand.raw,
                start=cand.start,
                end=cand.end,
                is_range=cand.is_range,
                precision=cand.precision,
                label=cand.label,
                grounded=_is_grounded(cand.raw, message),
                weekday_hint=cand.weekday_hint,
            )
        )

    flexible_only = bool(candidates) and all(
        c.precision is TemporalPrecision.FLEXIBLE for c in candidates
    )
    constraint_detected = (
        bool(raw_entities) or scanner_ambiguous or looks_temporal(message)
    )

    if not candidates and not constraint_detected:
        return _unspecified(today, horizon_end)
    if flexible_only and not scanner_ambiguous:
        return _unspecified(today, horizon_end)

    # A model-invented past date never outranks anything and never stands
    # alone — it is discarded rather than merely deprioritized.
    usable = [c for c in candidates if c.grounded or c.end >= today]
    usable = [c for c in usable if c.precision is not TemporalPrecision.FLEXIBLE]

    if not usable:
        if scanner_ambiguous:
            return _unreadable(
                TemporalStatus.AMBIGUOUS, message, raw_entities, horizon_end
            )
        if constraint_detected:
            return _unreadable(
                TemporalStatus.UNRESOLVED, message, raw_entities, horizon_end
            )
        return _unspecified(today, horizon_end)

    best = min(
        usable,
        key=lambda c: (
            c.precision,
            0 if c.grounded else 1,
            0 if c.end >= today else 1,
            c.start,
        ),
    )

    # An unresolvable weekday+ordinal alongside nothing more specific is still
    # ambiguous — "tuesday 2" must not fall back to the plain weekday.
    if scanner_ambiguous and best.precision >= TemporalPrecision.WEEKDAY:
        return _unreadable(
            TemporalStatus.AMBIGUOUS, message, raw_entities, horizon_end
        )

    conflict = False
    conflict_weekday = ""
    if best.precision is TemporalPrecision.EXPLICIT_DATE:
        stated = _stated_weekdays(message, candidates)
        if stated and best.start.weekday() not in stated:
            conflict = True
            conflict_weekday = calendar.day_name[sorted(stated)[0]]

    common = {
        "is_range": best.is_range,
        "precision": best.precision,
        "requested_text": best.raw,
        "scope_label": best.label,
        "horizon_end": horizon_end,
        "conflict": conflict,
        "conflict_weekday": conflict_weekday,
    }
    if best.end < today:
        return TemporalQuery(
            status=TemporalStatus.PAST, start=best.start, end=best.end, **common
        )
    if best.start > horizon_end:
        return TemporalQuery(
            status=TemporalStatus.BEYOND_HORIZON,
            start=best.start,
            end=best.end,
            **common,
        )
    return TemporalQuery(
        status=TemporalStatus.RESOLVED,
        start=max(best.start, today),
        end=min(best.end, horizon_end),
        **common,
    )


def _unreadable(
    status: TemporalStatus,
    message: str,
    raw_entities: Sequence[str],
    horizon_end: date,
) -> TemporalQuery:
    asked = raw_entities[0] if raw_entities else _norm(message)
    return TemporalQuery(
        status=status,
        requested_text=asked,
        scope_label=asked,
        horizon_end=horizon_end,
    )


def _unspecified(today: date, horizon_end: date) -> TemporalQuery:
    start = min(today + timedelta(days=1), horizon_end)
    return TemporalQuery(
        status=TemporalStatus.UNSPECIFIED,
        start=start,
        end=horizon_end,
        is_range=True,
        precision=TemporalPrecision.FLEXIBLE,
        horizon_end=horizon_end,
    )
