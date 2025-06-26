import sqlite3
from datetime import datetime

import click
from flask import current_app, g 

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(
            current_app.config ['DATABASE'],
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row

    return g.db

def close_db(e=None):
    db = g.pop('db', None)

    if db is not None:
        db.close()

def init_db():
    db = get_db()

    with current_app.open_resource('schema.sql') as f:
        db.executescript(f.read().decode('utf8'))

@click.command('init-db') # defines command line command that calls function and shows success message
def init_db_command():
    # Clear existing data and create new tables
    init_db()
    click.echo('Initialized the database.')

sqlite3.register_converter( # Tell python how to interpret timestamp values in database
    "timestamp", lambda v: datetime.fromisoformat(v.decode())
)

def init_app(app):
    app.teardown_appcontext(close_db) # tells Flask to call function when cleaning up after returning response
    app.cli.add_command(init_db_command) # adds new ocmmand that can be called with flask command
