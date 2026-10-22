"""Local installation and identity-key maintenance; never expose these operations over HTTP."""

import argparse
import asyncio
import base64
import json
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, delete, exists, inspect, or_, select, text

from app.core.auth_config import AuthSettings
from app.core.config import DatabaseSettings
from app.core.database import Base, Database
from app.core.security import IdentityCipher, PasswordSecurity, write_private_file
from app.models import AuthRateLimit, LoginAttempt, User
from app.services.auth import LIFECYCLE_LOCK, AuthService
from app.services.mail import DisabledMailer


def generate_keys(path: Path) -> None:
    """Create independent encryption and lookup keys once in a new private file."""
    keyring = {
        "active_key": "v1",
        "encryption_keys": {"v1": base64.b64encode(secrets.token_bytes(32)).decode()},
        "lookup_key": base64.b64encode(secrets.token_bytes(32)).decode(),
    }
    write_private_file(path, json.dumps(keyring, indent=2) + "\n")


def adopt_empty_baseline(connection: Connection) -> None:
    """Apply the consolidated initial migration only to the exact old empty baseline state.

    Parameters
    ----------
    connection
        A migration-role connection inside an explicit transaction. Unrelated tables survive.
    """
    context = MigrationContext.configure(connection, opts={"version_table_schema": "sophikron"})
    if context.get_current_revision() != "0001_database_baseline":
        raise ValueError("Expected the old stamped baseline")
    tables = set(inspect(connection).get_table_names(schema="sophikron"))
    authentication_tables = {table.name for table in Base.metadata.sorted_tables}
    if tables.intersection(authentication_tables):
        raise ValueError("Authentication tables already exist; refusing baseline adoption")
    configuration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(configuration).get_revision("0001_database_baseline")
    with Operations.context(context):
        revision.module.upgrade()
    connection.execute(text("REVOKE ALL ON sophikron.alembic_version FROM sophikron_app"))


async def execute(arguments: argparse.Namespace) -> None:
    """Run one explicitly selected local operation and release every database resource."""
    if arguments.command == "generate-keys":
        generate_keys(arguments.output)
        return
    database = Database(DatabaseSettings())
    try:
        if arguments.command == "adopt-empty-baseline":
            async with database.engine.begin() as connection:
                await connection.run_sync(adopt_empty_baseline)
            return
        if arguments.command == "prune-rate-limits":
            async with database.sessions.begin() as session:
                now = datetime.now(UTC)
                await session.execute(delete(LoginAttempt).where(LoginAttempt.expires_at <= now))
                await session.execute(
                    delete(AuthRateLimit).where(
                        AuthRateLimit.expires_at <= now,
                        ~exists().where(or_(
                            LoginAttempt.ip_key == AuthRateLimit.key,
                            LoginAttempt.identity_key == AuthRateLimit.key,
                        )),
                    )
                )
            return
        settings = AuthSettings()
        cipher = IdentityCipher.from_file(settings.keys_file)
        if arguments.command == "bootstrap":
            passwords = PasswordSecurity(settings)
            async with database.sessions() as session:
                service = AuthService(session, settings, cipher, passwords, DisabledMailer())
                await service.initialize_installation(renew=arguments.renew)
        elif arguments.command == "rotate-identities":
            async with database.sessions() as session:
                async with session.begin():
                    await session.execute(
                        text("SELECT pg_advisory_xact_lock(:key)"), {"key": LIFECYCLE_LOCK}
                    )
                    previous = IdentityCipher.from_file(arguments.previous_keys_file)
                    users = await session.scalars(select(User).order_by(User.id).with_for_update())
                    for user in users:
                        username = previous.decrypt(user.id, "username", user.username_encrypted)
                        email = (
                            previous.decrypt(user.id, "email", user.email_encrypted)
                            if user.email_encrypted is not None
                            else None
                        )
                        if previous.lookup("username", username) != user.username_lookup or (
                            email is not None
                            and previous.lookup("email", email) != user.email_lookup
                        ):
                            raise ValueError(
                                "Previous lookup key does not match the stored identities"
                            )
                        user.username_encrypted = cipher.encrypt(user.id, "username", username)
                        user.email_encrypted = (
                            cipher.encrypt(user.id, "email", email) if email is not None else None
                        )
                        user.username_lookup = cipher.lookup("username", username)
                        user.email_lookup = (
                            cipher.lookup("email", email) if email is not None else None
                        )
    finally:
        await database.close()


def main() -> None:
    """Parse local commands and report only sanitized results, never secret contents."""
    parser = argparse.ArgumentParser(description="Sophikron backend administration")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prune-rate-limits", help="Remove expired ephemeral rate-limit counters")
    keys = commands.add_parser("generate-keys", help="Create a new protected identity keyring")
    keys.add_argument("--output", type=Path, required=True)
    bootstrap = commands.add_parser("bootstrap", help="Initialize the temporary administrator")
    bootstrap.add_argument("--renew", action="store_true")
    commands.add_parser(
        "adopt-empty-baseline", help="Upgrade the previously empty stamped revision"
    )
    rotate = commands.add_parser(
        "rotate-identities", help="Rotate identity keys during maintenance"
    )
    rotate.add_argument("--previous-keys-file", type=Path, required=True)
    rotate.add_argument("--maintenance", action="store_true", required=True)
    arguments = parser.parse_args()
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    try:
        with asyncio.Runner(loop_factory=loop_factory) as runner:
            runner.run(execute(arguments))
    except Exception:
        parser.exit(
            1, "Operation failed. Check configuration, database state and file permissions.\n"
        )
    print("Operation completed. Existing installations are preserved; secrets are never printed.")


if __name__ == "__main__":
    main()
