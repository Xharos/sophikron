"""Establish migration tracking without introducing business tables."""

revision: str = "0001_database_baseline"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Record the baseline; deployment provisioning already owns roles and schema."""
    pass


def downgrade() -> None:
    """Remove baseline tracking without changing provisioned roles or schema."""
    pass
