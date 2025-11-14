import sqlite3
from datetime import datetime

import click
from flask import current_app, g

from werkzeug.security import generate_password_hash


def get_db():
    """
    Opens a new database connection if there is none yet.
    Used in many functions in the program to access the database. 
    """
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"], detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row

    return g.db


def close_db(e=None):
    """
    Closes the database connection.
    """
    db = g.pop("db", None)

    if db is not None:
        db.close()


def init_db():
    """
    Initializes the database by creating tables and inserting a default certifier.
    """
    db = get_db()

    # Runs schema to create tables
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf8"))

    # Certifier user creation
    db.execute(
        "INSERT INTO user (name, password) VALUES (?, ?)",
        ("certifier1", generate_password_hash("certifier1password")),
    )
    user_id = db.execute(
        "SELECT user_id FROM user WHERE name = ?", ("certifier1",)
    ).fetchone()["user_id"]
    db.execute("INSERT INTO certifier (user_id) VALUES (?)", (user_id,))

    db.commit()


@click.command(
    "init-db"
)  # defines command line command that calls function and shows success message
def init_db_command():
    # Clear existing data and create new tables
    init_db()
    click.echo("Initialized the database.")


sqlite3.register_converter(  # Tell python how to interpret timestamp values in database
    "timestamp", lambda v: datetime.fromisoformat(v.decode())
)


def init_app(app):
    app.teardown_appcontext(
        close_db
    )  # tells Flask to call function when cleaning up after returning response
    app.cli.add_command(
        init_db_command
    )  # adds new ocmmand that can be called with flask command
