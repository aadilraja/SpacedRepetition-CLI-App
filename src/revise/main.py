import enum
import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from sqlalchemy import Date, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


# ============================================================
# PATHS
# ============================================================

# Project structure:
#
# Tracker/
# ├── .env
# ├── data/
# │   ├── config.json
# │   └── revision.db
# └── src/
#     └── main.py
#
# BASE_DIR = Tracker/

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / os.getenv(
    "DATA_DIR",
    "data"
)

CONFIG_FILE = BASE_DIR / os.getenv(
    "CONFIG_FILE",
    "data/config.json"
)

DATABASE_FILE = BASE_DIR / os.getenv(
    "DATABASE_FILE",
    "data/revision.db"
)

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# DATABASE
# ============================================================

class Base(DeclarativeBase):
    pass


class Coverage(Base):
    """
    One occurrence of a topic being covered.

    The same topic can have multiple Coverage records:

        Binary Search - 12/05/2025
        Binary Search - 14/05/2025

    They are treated as separate revision cycles.
    """

    __tablename__ = "coverage"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False
    )

    covered_date: Mapped[date] = mapped_column(
        Date,
        nullable=False
    )

    next_review: Mapped[date] = mapped_column(
        Date,
        nullable=False
    )

    interval_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=2
    )

    stage: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="active"
    )

    # JSON encoded list.
    #
    # Example:
    #
    # [
    #   "dsa",
    #   "dsa/array",
    #   "dsa/array/hard"
    # ]
    #
    keywords: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]"
    )

    source_file: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    source_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.now
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.now,
        onupdate=datetime.now
    )


class ReviewHistory(Base):
    """
    Stores every review result.

    History is never deleted when a coverage item is removed.
    """

    __tablename__ = "review_history"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    coverage_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.now
    )

    result: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )

    previous_interval: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    new_interval: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )


DATABASE_URL = f"sqlite:///{DATABASE_FILE}"

engine = create_engine(
    DATABASE_URL,
    echo=False
)

Base.metadata.create_all(engine)


# ============================================================
# CONSTANTS
# ============================================================

# First-pass schedule:
#
# 2 → 3 → 5 → 7 → 14 → 28 → 56 → ...

FIRST_PASS_INTERVALS = [
    2,
    3,
    5,
    7,
]

# FIX #1:
# Allow an optional leading Markdown heading marker ("#", "##", ...)
# before the date, so lines like "# 12/06/2026" are recognized the
# same way as "12/06/2026" or "Date: 12/06/2026". Previously this
# pattern required the date (or "Date:") to be the very first thing
# on the line, so any tracker using Markdown headers for dates was
# silently ignored in full (current_date was never set, so every
# bullet under it was skipped).
DATE_PATTERN = re.compile(
    r"^\s*#*\s*(?:date\s*:\s*)?(\d{2}/\d{2}/\d{4})\s*$",
    re.IGNORECASE
)

BULLET_PATTERN = re.compile(
    r"^(\s*)[-*+]\s+(.*)$"
)

CHECKBOX_PATTERN = re.compile(
    r"^\[([ xX])\]\s*(.*)$"
)

BOLD_PATTERN = re.compile(
    r"\*\*([^*]+)\*\*"
)

MARKDOWN_LINK_PATTERN = re.compile(
    r"\[([^\]]+)\]\([^)]+\)"
)

ANGLE_LINK_PATTERN = re.compile(
    r"<https?://[^>]+>"
)


# ============================================================
# CONFIGURATION
# ============================================================

def is_first_run():
    return not CONFIG_FILE.exists()


def save_config(config):
    CONFIG_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with CONFIG_FILE.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            config,
            file,
            indent=4
        )


def load_config():
    try:
        with CONFIG_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:
            return json.load(file)

    except (
        json.JSONDecodeError,
        OSError
    ):
        print("Configuration file is missing or corrupted.")
        print("Delete config.json and run the program again.")
        raise SystemExit(1)


def setup():
    print()
    print("Welcome to Revision Tracker")
    print("=" * 35)
    print()

    name = input("Enter your name: ").strip()

    while True:
        tracker_path = Path(
            input("Tracker Markdown file path: ").strip()
        ).expanduser()

        if not tracker_path.exists():
            print("That path does not exist.")
            continue

        if not tracker_path.is_file():
            print("That path is not a file.")
            continue

        if tracker_path.suffix.lower() != ".md":
            print("The tracker must be a Markdown (.md) file.")
            continue

        break

    config = {
        "name": name,
        "tracker_path": str(
            tracker_path.resolve()
        ),
        "last_scan": None
    }

    save_config(config)

    print()
    print("Setup complete.")
    print(f"Name: {name}")
    print(f"Tracker: {tracker_path}")

    print_template()


def update_config(values):
    config = load_config()

    if "name" in values:
        config["name"] = values["name"]

    if "path" in values:

        path = Path(
            values["path"]
        ).expanduser()

        if not path.exists():
            print(f"Path does not exist: {path}")
            return

        if not path.is_file():
            print(f"Path is not a file: {path}")
            return

        if path.suffix.lower() != ".md":
            print("Tracker must be a Markdown (.md) file.")
            return

        config["tracker_path"] = str(
            path.resolve()
        )

    save_config(config)

    print("Configuration updated.")

    print(
        f"Name: {config['name']}"
    )

    print(
        f"Tracker: {config['tracker_path']}"
    )


# ============================================================
# TEMPLATE
# ============================================================

def print_template():
    print()
    print("Basic tracker format")
    print("=" * 60)

    print(
        """
The tracker is intentionally flexible.

The main requirement is:

    DD/MM/YYYY

followed by bullet points containing what you covered.

Basic example:

15/08/2026

- Binary Search
- Binary Trees
- Process Scheduling
- Database Indexing


You can use bold keywords for filtering:

16/08/2026

- Binary Search **dsa**
- Process Scheduling **os**
- Database Indexing **dbms**


You can create hierarchical keywords by nesting bullets deeper:

17/08/2026

- Binary Search **dsa**
    - **array**
        - **hard**

This produces:

    dsa
    dsa/array
    dsa/array/hard

So you can filter with:

    revise list -filter "dsa"
    revise list -filter "dsa/array"
    revise list -filter "dsa/array/hard"


Note: keywords at the SAME indentation are independent tags, not a
chain. For example:

- Binary Search **dsa**
    - **array**
    - **hard**

produces "dsa/array" and "dsa/hard" as two separate branches (both
children of "dsa", but not children of each other) -- useful when a
topic has multiple unrelated facets rather than one strict taxonomy.


For a deep taxonomy path, you can also write the whole path in a
single bold tag using slashes, instead of indenting one level per
segment:

- Binary Search **dsa/array/hard**

This is shorthand for the same three-level nested example above and
produces exactly the same keywords:

    dsa
    dsa/array
    dsa/array/hard

Slash shorthand and indentation can be mixed freely, and a nested
bullet placed after a slash-shorthand tag continues nesting under
its deepest segment:

- Binary Search **dsa/array**
    - **hard**

also produces:

    dsa
    dsa/array
    dsa/array/hard


Markdown links are ignored when identifying the topic:

- Binary Search **dsa** [solution](./binary-search.md)

The topic is simply:

    Binary Search


You can also use:

    Date: 18/08/2026

instead of:

    18/08/2026


Markdown headings are also fine:

    # 18/08/2026
    ## Date: 18/08/2026


The program does not require Obsidian.
It works with ordinary Markdown files.
"""
    )

    print("=" * 60)


# ============================================================
# MARKDOWN HELPERS
# ============================================================

def parse_date(text):
    try:
        return datetime.strptime(
            text,
            "%d/%m/%Y"
        ).date()

    except ValueError:
        return None


def remove_markdown_links(text):
    """
    Convert:

        [solution](./solution.md)

    into nothing.

    Also removes:

        <https://example.com>
    """

    text = MARKDOWN_LINK_PATTERN.sub(
        "",
        text
    )

    text = ANGLE_LINK_PATTERN.sub(
        "",
        text
    )

    return text


def extract_bold_keywords(text):
    """
    Extract:

        **dsa** **array** **hard**

    Each returned value may itself contain slashes, e.g.

        **dsa/array/hard**

    Slash-splitting into a full path is handled separately by
    expand_keyword_path(); this function only pulls out and
    normalizes the raw bold values.
    """

    return [
        value.strip().lower()
        for value in BOLD_PATTERN.findall(text)
        if value.strip()
    ]


def expand_keyword_path(raw_keyword, parent_path):
    """
    Expand a single bold keyword into the list of full hierarchical
    paths it represents, anchored under parent_path.

    A bold keyword may itself be a slash-separated path, used as
    shorthand for nesting multiple levels on one line:

        parent_path = ""
        raw_keyword = "dsa/array/hard"
        -> ["dsa", "dsa/array", "dsa/array/hard"]

        parent_path = "dsa"
        raw_keyword = "array/hard"
        -> ["dsa/array", "dsa/array/hard"]

    A plain keyword with no slash behaves exactly as before:

        parent_path = "dsa"
        raw_keyword = "array"
        -> ["dsa/array"]

    Empty segments (e.g. from "dsa//array" or stray slashes) are
    dropped. If every segment is empty, returns an empty list.
    """

    segments = [
        segment.strip()
        for segment in raw_keyword.split("/")
        if segment.strip()
    ]

    paths = []
    current = parent_path

    for segment in segments:
        current = f"{current}/{segment}" if current else segment
        paths.append(current)

    return paths


def clean_topic_title(text):
    """
    Remove Markdown links and bold syntax.

    Example:

        Binary Search **dsa** [solution](x)

    becomes:

        Binary Search
    """

    text = remove_markdown_links(
        text
    )

    text = BOLD_PATTERN.sub(
        "",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip(
        " -*_:#"
    ).strip()


# ============================================================
# MARKDOWN SCANNER
# ============================================================

def parse_tracker(file_path):
    """
    Parse the Markdown tracker.

    Top-level bullets become topics.

    Checkbox state:
        - [x] Topic -> checked=True
        - [X] Topic -> checked=True
        - [ ] Topic -> checked=False
        - Topic     -> checked=None

    The caller decides how checkbox state affects importing.
    """

    file_path = Path(file_path)

    if not file_path.is_file():
        raise FileNotFoundError(
            f"Tracker file not found: {file_path}"
        )

    results = []
    current_date = None
    keyword_stack = []

    with file_path.open(
        "r",
        encoding="utf-8"
    ) as file:

        for line_number, raw_line in enumerate(
            file,
            start=1
        ):

            line = raw_line.rstrip("\n")

            # ------------------------------------------------
            # Date
            # ------------------------------------------------

            date_match = DATE_PATTERN.match(line)

            if date_match:
                current_date = parse_date(
                    date_match.group(1)
                )

                keyword_stack = []

                continue

            # ------------------------------------------------
            # Bullet
            # ------------------------------------------------

            bullet_match = BULLET_PATTERN.match(line)

            if not bullet_match:
                continue

            indentation = len(
                bullet_match.group(1).replace(
                    "\t",
                    "    "
                )
            )

            content = bullet_match.group(2).strip()

            if current_date is None:
                continue

            # ------------------------------------------------
            # Checkbox
            # ------------------------------------------------

            checked = None

            checkbox_match = CHECKBOX_PATTERN.match(
                content
            )

            if checkbox_match:

                checked = (
                    checkbox_match.group(1).lower() == "x"
                )

                content = checkbox_match.group(2).strip()

            # ------------------------------------------------
            # Top-level bullet = topic
            # ------------------------------------------------

            if indentation == 0:

                title = clean_topic_title(
                    content
                )

                if not title:
                    continue

                root_keywords = extract_bold_keywords(
                    content
                )

                keyword_paths = []
                stack_anchor = None

                for keyword in root_keywords:

                    expanded_paths = expand_keyword_path(
                        keyword,
                        ""
                    )

                    keyword_paths.extend(
                        expanded_paths
                    )

                    if expanded_paths:
                        stack_anchor = expanded_paths[-1]

                keyword_stack = []

                if stack_anchor:
                    keyword_stack.append(
                        (
                            indentation,
                            stack_anchor
                        )
                    )

                results.append(
                    {
                        "title": title,
                        "covered_date": current_date,
                        "keywords": keyword_paths,
                        "source_file": str(
                            file_path.resolve()
                        ),
                        "source_line": line_number,
                        "checked": checked
                    }
                )

                continue

            # ------------------------------------------------
            # Nested bullet
            # ------------------------------------------------

            nested_keywords = extract_bold_keywords(
                content
            )

            if not nested_keywords:
                continue

            if not results:
                continue

            while (
                keyword_stack
                and keyword_stack[-1][0] >= indentation
            ):
                keyword_stack.pop()

            parent_path = ""

            if keyword_stack:
                parent_path = keyword_stack[-1][1]

            for keyword in nested_keywords:

                expanded_paths = expand_keyword_path(
                    keyword,
                    parent_path
                )

                if not expanded_paths:
                    continue

                results[-1]["keywords"].extend(
                    expanded_paths
                )

                keyword_stack.append(
                    (
                        indentation,
                        expanded_paths[-1]
                    )
                )

    return results


# ============================================================
# SOURCE ID
# ============================================================

def make_source_key(item):
    """
    Generate a stable ID for one Markdown coverage occurrence.

    Same:

        file + date + title + source line

    will not be imported twice.

    A topic on another date becomes a different record.
    """

    raw = (
        f"{item['source_file']}|"
        f"{item['covered_date'].isoformat()}|"
        f"{item['title'].strip().lower()}"
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


# ============================================================
# DATABASE IMPORT
# ============================================================

def import_topics(parsed_topics, config):
    """
    Import checked topics from the top-of-file Markdown date section.

    Only [x] topics should reach this function. Existing records are
    skipped so scanning is safe to repeat.
    """

    added = 0
    skipped = 0

    with Session(engine) as session:

        for item in parsed_topics:

            source_key = make_source_key(
                item
            )

            existing = (
                session.query(Coverage)
                .filter(
                    Coverage.source_key == source_key
                )
                .first()
            )

            if existing:

                # If an existing record was previously removed, checking
                # the topic again makes it active again.
                if existing.status == "removed":
                    existing.status = "active"
                    existing.next_review = (
                        item["covered_date"]
                        + timedelta(
                            days=existing.interval_days
                        )
                    )

                skipped += 1
                continue

            keywords = sorted(
                set(
                    item["keywords"]
                )
            )

            coverage = Coverage(
                title=item["title"],
                covered_date=item["covered_date"],
                next_review=(
                    item["covered_date"]
                    + timedelta(days=2)
                ),
                interval_days=2,
                stage=0,
                status="active",
                keywords=json.dumps(
                    keywords
                ),
                source_file=item["source_file"],
                source_key=source_key
            )

            session.add(
                coverage
            )

            added += 1

        session.commit()

    return added, skipped


def scan_tracker(config):
    """
    Scan ONLY the top date section of the Markdown file (i.e. the
    first date the parser encounters, in file order).

    Rules:

        top date section:
            [x] Topic -> add
            [ ] Topic -> ignore
            Topic     -> ignore

        every other date section:
            everything -> ignore

    This function is called only by the `scan` command.
    """

    tracker_path = config["tracker_path"]

    try:
        parsed_topics = parse_tracker(
            tracker_path
        )

    except FileNotFoundError as error:

        print(error)
        return 0

    if not parsed_topics:

        print("No topics found.")
        return 0

    # FIX #2:
    # "Top date" means the date section that appears first in the
    # file (file order), NOT the chronologically greatest date.
    # Using max() here previously picked whichever date section had
    # the latest calendar date, even if it appeared further down the
    # file than an earlier-dated section at the top -- which is the
    # opposite of what "scan only the top section" is supposed to do.
    top_date = parsed_topics[0]["covered_date"]

    # Only checked topics from the top date section are imported.
    checked_topics = [
        item
        for item in parsed_topics
        if (
            item["covered_date"] == top_date
            and item.get("checked") is True
        )
    ]

    ignored = len(parsed_topics) - len(
        checked_topics
    )

    added, skipped = import_topics(
        checked_topics,
        config
    )

    config["last_scan"] = datetime.now().isoformat()

    save_config(
        config
    )

    print()
    print("Scan complete.")
    print(
        f"Top date: "
        f"{top_date.strftime('%d/%m/%Y')}"
    )
    print(
        f"Topics in top date section: "
        f"{len([item for item in parsed_topics if item['covered_date'] == top_date])}"
    )
    print(
        f"Checked and scanned: "
        f"{len(checked_topics)}"
    )
    print(
        f"New: {added}"
    )
    print(
        f"Already imported: {skipped}"
    )
    print(
        f"Ignored: {ignored}"
    )

    return added


# ============================================================
# KEYWORD FILTER
# ============================================================

def get_keywords(topic):
    try:
        return json.loads(
            topic.keywords
        )

    except (
        json.JSONDecodeError,
        TypeError
    ):
        return []


def topic_matches_filter(
    topic,
    filter_value
):
    """
    Match hierarchical filters.

    Example:

        topic keywords:
            [
                "dsa",
                "dsa/array",
                "dsa/array/hard"
            ]

        filter:
            dsa/array

    matches.

    Filter also matches topic title.
    """

    if not filter_value:
        return True

    filter_value = filter_value.strip().lower()

    if filter_value in topic.title.lower():
        return True

    keywords = get_keywords(
        topic
    )

    # Exact hierarchical path.
    if filter_value in keywords:
        return True

    # Also allow an individual keyword.
    for keyword in keywords:

        parts = keyword.split("/")

        if filter_value in parts:
            return True

    return False


# ============================================================
# DATE FILTER
# ============================================================

def parse_date_filter(value):
    """
    Supported:

        12/05/2025

        13/05/2025::24/07/2026

        13/05/2025::

        ::24/07/2026
    """

    value = value.strip()

    if "::" not in value:

        parsed = parse_date(
            value
        )

        if parsed is None:
            raise ValueError(
                "Date must be DD/MM/YYYY."
            )

        return parsed, parsed

    start_text, end_text = value.split(
        "::",
        1
    )

    start_text = start_text.strip()
    end_text = end_text.strip()

    start_date = None
    end_date = None

    if start_text:

        start_date = parse_date(
            start_text
        )

        if start_date is None:
            raise ValueError(
                "Start date must be DD/MM/YYYY."
            )

    if end_text:

        end_date = parse_date(
            end_text
        )

        if end_date is None:
            raise ValueError(
                "End date must be DD/MM/YYYY."
            )

    if (
        start_date
        and end_date
        and start_date > end_date
    ):
        raise ValueError(
            "Start date cannot be after end date."
        )

    return start_date, end_date


def topic_matches_date(
    topic,
    date_filter
):
    if not date_filter:
        return True

    start_date, end_date = parse_date_filter(
        date_filter
    )

    covered_date = topic.covered_date

    if start_date and covered_date < start_date:
        return False

    if end_date and covered_date > end_date:
        return False

    return True


# ============================================================
# LIST
# ============================================================

def list_topics(
    keyword=None,
    date_filter=None
):

    with Session(engine) as session:

        topics = (
            session.query(Coverage)
            .order_by(
                Coverage.covered_date
            )
            .all()
        )

    filtered = []

    for topic in topics:

        if not topic_matches_filter(
            topic,
            keyword
        ):
            continue

        if not topic_matches_date(
            topic,
            date_filter
        ):
            continue

        filtered.append(
            topic
        )

    if not filtered:

        print("No matching topics found.")
        return

    print()

    print(
        f"{'ID':<5}"
        f"{'Date':<13}"
        f"{'Topic':<35}"
        f"{'Next Review':<13}"
        f"{'Interval':<10}"
        f"{'Status':<10}"
    )

    print("-" * 90)

    for topic in filtered:

        print(
            f"{topic.id:<5}"
            f"{topic.covered_date.strftime('%d/%m/%Y'):<13}"
            f"{topic.title[:33]:<35}"
            f"{topic.next_review.strftime('%d/%m/%Y'):<13}"
            f"{topic.interval_days:<10}"
            f"{topic.status:<10}"
        )


# ============================================================
# DUE
# ============================================================

def get_due_topics(
    keyword=None
):

    today = date.today()

    with Session(engine) as session:

        topics = (
            session.query(Coverage)
            .filter(
                Coverage.status == "active",
                Coverage.next_review <= today
            )
            .order_by(
                Coverage.next_review
            )
            .all()
        )

    if keyword:

        topics = [
            topic
            for topic in topics
            if topic_matches_filter(
                topic,
                keyword
            )
        ]

    return topics


def show_due(
    keyword=None
):

    topics = get_due_topics(
        keyword
    )

    if not topics:

        print("Nothing is due.")
        return

    print()
    print("Due for review")
    print("=" * 60)

    for topic in topics:

        overdue = (
            date.today()
            - topic.next_review
        ).days

        print(
            f"[{topic.id}] {topic.title}"
        )

        print(
            f"    Covered: "
            f"{topic.covered_date.strftime('%d/%m/%Y')}"
        )

        print(
            f"    Due: "
            f"{topic.next_review.strftime('%d/%m/%Y')}"
        )

        print(
            f"    Interval: "
            f"{topic.interval_days} days"
        )

        if topic.keywords:

            print(
                f"    Keywords: "
                f"{', '.join(get_keywords(topic))}"
            )

        if overdue > 0:

            print(
                f"    Overdue: "
                f"{overdue} day(s)"
            )

        print()


# ============================================================
# REVIEW
# ============================================================

def calculate_next_interval(
    current_interval,
    result
):

    if result == "failed":
        return 2

    if result != "confident":
        raise ValueError(
            "Result must be confident or failed."
        )

    # First pass:
    #
    # 2 → 3 → 5 → 7

    if current_interval in FIRST_PASS_INTERVALS:

        index = FIRST_PASS_INTERVALS.index(
            current_interval
        )

        if index + 1 < len(FIRST_PASS_INTERVALS):

            return FIRST_PASS_INTERVALS[
                index + 1
            ]

        # 7 → 14
        return current_interval * 2

    # After 7:
    #
    # 14 → 28 → 56 → ...

    return current_interval * 2


def review_topics(
    result,
    keyword=None
):

    if result not in {
        "confident",
        "failed"
    }:

        print(
            "Result must be 'confident' or 'failed'."
        )

        return

    topics = get_due_topics(
        keyword
    )

    if not topics:

        print(
            "No matching topics are due."
        )

        return

    today = date.today()

    with Session(engine) as session:

        reviewed = 0

        for due_topic in topics:

            topic = session.get(
                Coverage,
                due_topic.id
            )

            if topic is None:
                continue

            previous_interval = (
                topic.interval_days
            )

            new_interval = calculate_next_interval(
                previous_interval,
                result
            )

            topic.interval_days = new_interval

            if result == "failed":

                topic.stage = 0

            else:

                topic.stage += 1

            topic.next_review = (
                today
                + timedelta(
                    days=new_interval
                )
            )

            history = ReviewHistory(
                coverage_id=topic.id,
                reviewed_at=datetime.now(),
                result=result,
                previous_interval=previous_interval,
                new_interval=new_interval
            )

            session.add(
                history
            )

            reviewed += 1

        session.commit()

    print()
    print(
        f"Reviewed {reviewed} topic(s): {result}"
    )


# ============================================================
# REMOVE
# ============================================================

def remove_topics(
    title=None,
    date_filter=None,
    keyword=None
):

    with Session(engine) as session:

        topics = (
            session.query(Coverage)
            .filter(
                Coverage.status == "active"
            )
            .all()
        )

        matches = []

        for topic in topics:

            if title:
                if title.lower() not in topic.title.lower():
                    continue

            if date_filter:
                if not topic_matches_date(
                    topic,
                    date_filter
                ):
                    continue

            if keyword:
                if not topic_matches_filter(
                    topic,
                    keyword
                ):
                    continue

            matches.append(
                topic
            )

        if not matches:

            print(
                "No matching topics found."
            )

            return

        print()
        print("Topics to remove:")
        print("-" * 50)

        for topic in matches:

            print(
                f"[{topic.id}] "
                f"{topic.covered_date.strftime('%d/%m/%Y')} "
                f"{topic.title}"
            )

        print()

        confirmation = input(
            f"Remove {len(matches)} topic occurrence(s)? [y/N]: "
        ).strip().lower()

        if confirmation != "y":

            print("Cancelled.")
            return

        for topic in matches:

            topic.status = "removed"

        session.commit()

        print(
            f"Removed {len(matches)} topic occurrence(s)."
        )


# ============================================================
# EXCEL EXPORT
# ============================================================

def export_excel():

    try:

        from openpyxl import Workbook

    except ImportError:

        print(
            "Excel export requires openpyxl."
        )

        print(
            "Install it with:"
        )

        print(
            "pip install openpyxl"
        )

        return

    output_file = DATA_DIR / "revision_export.xlsx"

    with Session(engine) as session:

        topics = (
            session.query(Coverage)
            .order_by(
                Coverage.covered_date
            )
            .all()
        )

    workbook = Workbook()

    sheet = workbook.active
    sheet.title = "All Topics"

    sheet.append(
        [
            "ID",
            "Date",
            "Topic",
            "Keywords",
            "Next Review",
            "Interval",
            "Stage",
            "Status",
            "Source File"
        ]
    )

    for topic in topics:

        sheet.append(
            [
                topic.id,
                topic.covered_date.strftime(
                    "%d/%m/%Y"
                ),
                topic.title,
                " | ".join(
                    get_keywords(topic)
                ),
                topic.next_review.strftime(
                    "%d/%m/%Y"
                ),
                topic.interval_days,
                topic.stage,
                topic.status,
                topic.source_file
            ]
        )

    workbook.save(
        output_file
    )

    print()
    print(
        f"Excel exported to:"
    )

    print(
        output_file
    )


# ============================================================
# ARGUMENT PARSER
# ============================================================

app = typer.Typer(
    name="revise",
    help="Personal spaced-revision tracker",
    add_completion=False
)

config_app = typer.Typer(
    help='Manage configuration (name, tracker path)'
)

app.add_typer(
    config_app,
    name="config"
)


class ReviewResult(str, enum.Enum):
    """
    Typer/Click validates this automatically -- an invalid value
    (e.g. "revise review nonsense") is rejected before review_topics()
    is ever called, with a proper usage error and the list of valid
    choices shown to the user.
    """

    confident = "confident"
    failed = "failed"


# ============================================================
# ROOT CALLBACK
# ============================================================
#
# Runs once before any subcommand. Handles first-run setup and loads
# config into ctx.obj so subcommands that need it don't each have to
# call load_config() themselves.
#
# Note: Click resolves "--help" before invoking this callback, so
# `revise --help` no longer triggers the interactive setup wizard the
# way the old argparse version did (which ran setup() unconditionally
# before parsing any arguments, including --help).

@app.callback(invoke_without_command=True)
def cli_entrypoint(ctx: typer.Context):

    if is_first_run():
        setup()

    ctx.obj = load_config()

    if ctx.invoked_subcommand is None:
        typer.echo(
            ctx.get_help()
        )

        raise typer.Exit()


# ============================================================
# SCAN
# ============================================================

@app.command(
    help="Scan only checked topics from the top Markdown date section"
)
def scan(ctx: typer.Context):

    scan_tracker(
        ctx.obj
    )


# ============================================================
# DUE
# ============================================================

@app.command(
    help="Show due topics without scanning Markdown"
)
def due(
    filter: Optional[str] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter by keyword, keyword path, or title substring"
    )
):

    show_due(
        filter
    )


# ============================================================
# LIST
# ============================================================

@app.command(
    name="list",
    help="List covered topics"
)
def list_command(
    ctx: typer.Context,
    filter: Optional[str] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter by keyword, keyword path, or title substring"
    ),
    date_filter: Optional[str] = typer.Option(
        None,
        "--date",
        "-d",
        help='Single date "DD/MM/YYYY" or range "DD/MM/YYYY::DD/MM/YYYY"'
    ),
    export: bool = typer.Option(
        False,
        "--export",
        help="Export to Excel instead of printing to the console"
    )
):

    scan_tracker(
        ctx.obj
    )

    if export:

        export_excel()

    else:

        try:

            list_topics(
                keyword=filter,
                date_filter=date_filter
            )

        except ValueError as error:

            typer.echo(
                f"Invalid date filter: {error}"
            )


# ============================================================
# REVIEW
# ============================================================

@app.command(
    help="Record a review result for all due topics (optionally filtered)"
)
def review(
    result: ReviewResult = typer.Argument(
        ...,
        help="Review outcome"
    ),
    filter: Optional[str] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Only review topics matching this keyword, keyword path, or title"
    )
):

    review_topics(
        result=result.value,
        keyword=filter
    )


# ============================================================
# REMOVE
# ============================================================

@app.command(
    help="Remove coverage records (marks them as removed; history is kept)"
)
def remove(
    title: Optional[str] = typer.Argument(
        None,
        help="Title substring to match"
    ),
    date_filter: Optional[str] = typer.Option(
        None,
        "--date",
        "-d",
        help='Single date "DD/MM/YYYY" or range "DD/MM/YYYY::DD/MM/YYYY"'
    ),
    filter: Optional[str] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter by keyword or keyword path"
    )
):

    try:

        remove_topics(
            title=title,
            date_filter=date_filter,
            keyword=filter
        )

    except ValueError as error:

        typer.echo(
            f"Invalid date filter: {error}"
        )


# ============================================================
# EXPORT
# ============================================================

@app.command(
    help="Export all data to Excel"
)
def export():

    export_excel()


# ============================================================
# TEMPLATE
# ============================================================

@app.command(
    help="Show the Markdown tracker template and formatting guide"
)
def template():

    print_template()


# ============================================================
# CONFIG
# ============================================================

@config_app.callback(invoke_without_command=True)
def config_root(ctx: typer.Context):

    if ctx.invoked_subcommand is None:

        typer.echo(
            'Use: revise config update --name "..." --path "..."'
        )


@config_app.command(
    name="update",
    help="Update your name and/or tracker file path"
)
def config_update(
    name: Optional[str] = typer.Option(
        None,
        "--name",
        help="Your display name"
    ),
    path: Optional[Path] = typer.Option(
        None,
        "--path",
        help="Path to your Markdown tracker file"
    )
):

    values = {}

    if name is not None:
        values["name"] = name

    if path is not None:
        values["path"] = str(path)

    if not values:

        typer.echo(
            'Example: revise config update --name "John" --path "C:\\tracker.md"'
        )

        return

    update_config(
        values
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    app()