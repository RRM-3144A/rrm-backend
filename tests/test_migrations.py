from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.database import Base


def _alembic_config(database_url: str, monkeypatch) -> Config:
    monkeypatch.setattr("app.config.settings.database_url", database_url)
    return Config("alembic.ini")


def test_upgrade_creates_every_model_table(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'migrations.db'}"
    config = _alembic_config(database_url, monkeypatch)

    command.upgrade(config, "head")

    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert set(Base.metadata.tables) <= tables


def test_downgrade_removes_every_table(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'migrations.db'}"
    config = _alembic_config(database_url, monkeypatch)

    command.upgrade(config, "head")
    command.downgrade(config, "base")

    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert tables <= {"alembic_version"}
