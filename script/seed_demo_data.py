"""Configure and create local demo data; use --dry-run to inspect without writing."""

import argparse
import os
import sys
from copy import deepcopy
from getpass import getpass

from demo_data.client import Client
from demo_data.configuration import SeedError, Settings
from demo_data.runner import describe, seed

# Edit these values to build a different scenario. Namespace changes isolate repeated experiments.
CONFIG = Settings(
    namespace="demo",  # Use another name to keep multiple independent scenarios.
    school_year=2026,
    class_count=2,
    pupils_per_class=45,
    german_pupils=10,
    random_seed=2026,
    kholle_group_size=3,
    rooms=("B208", "C105", "C106", "D202", "E301"),
    include_summer_holidays=True,  # Keep the July 30 bound, but stop lessons on July 2.
    filled_calendar_indexes=(0, 1),  # The PT calendar is created but intentionally left empty.
    teacher_counts={
        "si": 2,
        "maths": 2,
        "physics": 2,
        "english": 1,
        "french": 1,
        "german": 1,
    },
    kholleur_counts={"si": 1, "maths": 1, "physics": 1, "english": 1},
    weekly_hours={
        "maths": {"course": 7, "td": 3},
        "si": {"course": 2, "td": 4, "tp": 4},
        "physics": {"course": 4, "td": 2, "tp": 2},
        "english": {"course": 2},
        "computer_science": {"course": 1, "tp": 1},
        "french": {"course": 2},
    },
    german_option_hours=1,  # Set 1 to add a weekly hour for the ten German-option pupils.
    broadcast=False,  # Calendars are initially visible to administrators only.
)
BASE_URL = "http://127.0.0.1:8000"
ORIGIN = "http://192.168.1.41:3000"


def main(argv: list[str] | None = None) -> int:
    """Read scenario overrides and revoke the memory-only administrator session on exit."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--classes", type=int)
    parser.add_argument("--students", type=int)
    parser.add_argument("--namespace")
    parser.add_argument("--email", default=os.getenv("SOPHIKRON_SEED_EMAIL", ""))
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--origin", default=ORIGIN)
    arguments = parser.parse_args(argv)
    settings = deepcopy(CONFIG)
    if arguments.classes is not None:
        settings.class_count = arguments.classes
    if arguments.students is not None:
        settings.pupils_per_class = arguments.students
    if arguments.namespace is not None:
        settings.namespace = arguments.namespace
    client = None
    authenticated = False
    try:
        describe(settings)
        if arguments.dry_run:
            return 0
        client = Client(arguments.base_url, arguments.origin)
        email = (arguments.email or input("Administrator email: ")).strip()
        password = os.getenv("SOPHIKRON_SEED_PASSWORD") or getpass("Administrator password: ")
        if not email or not password:
            raise SeedError("Administrator email and password are required.")
        profile = client.request("POST", "/auth/login", {"identifier": email, "password": password})
        authenticated = True
        required = {
            "users.read",
            "users.manage",
            "promotions.read",
            "promotions.manage",
            "profiles.manage",
        }
        if (
            profile.get("is_bootstrap")
            or "admin" not in profile.get("roles", [])
            or not required <= set(profile.get("permissions", []))
        ):
            raise SeedError(
                "Utilisez un compte administrateur permanent avec les droits de gestion."
            )
        seed(client, settings)
        return 0
    except SeedError as error:
        print(f"Erreur : {error}", file=sys.stderr)
        print(
            "Les créations déjà validées sont conservées ; une relance reprend le scénario.",
            file=sys.stderr,
        )
        return 1
    except (KeyboardInterrupt, EOFError):
        return 130
    finally:
        if authenticated and client is not None:
            try:
                client.request("POST", "/auth/logout")
            except SeedError:
                print(
                    "Déconnexion non confirmée ; la session expirera normalement.",
                    file=sys.stderr,
                )


if __name__ == "__main__":
    raise SystemExit(main())
