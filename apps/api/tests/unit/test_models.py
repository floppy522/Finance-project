from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from moneyflow.models import Transaction


def test_category_metadata_constraint_compiles_non_null_confidence_requirement() -> None:
    compiled = str(CreateTable(Transaction.__table__).compile(dialect=postgresql.dialect()))

    assert (
        "category_confidence IS NOT NULL AND category_confidence BETWEEN 0 AND 100"
        in compiled
    )
