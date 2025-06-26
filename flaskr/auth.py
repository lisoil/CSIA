import functools
import sqlite3


from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for
)

from werkzeug.security import check_password_hash, generate_password_hash

from flaskr.db import get_db

bp = Blueprint('auth', __name__, url_prefix='/auth')

@bp.route('/register', methods=('GET', 'POST'))
def register():
    if request.method == 'POST':
        name = request.form['name']
        password = request.form['password']
        region = request.form['region']
        location = request.form['location']
        db = get_db()
        error = None

        if not name:
            error = 'Name is required.'
        elif not password:
            error = 'Password is required.'
        elif not region:
            error = 'Region is required.'
        elif not location:
            error = 'Location is required.'

        if error is None:
            try:
                # Insert into user table
                db.execute(
                    "INSERT INTO user (name, password) VALUES (?, ?)",
                    (name, generate_password_hash(password))
                )
                # Get the user_id of the newly inserted user
                user_id = db.execute(
                    "SELECT user_id FROM user WHERE name = ?", (name,)
                ).fetchone()['user_id']

                # Insert into requester table with the user_id
                db.execute(
                    "INSERT INTO requester (user_id, region, location) VALUES (?, ?, ?)",
                    (user_id, region, location)
                )
                db.commit() 
            except db.IntegrityError:
                error = f"User {name} is already registered."
            else:
                return redirect(url_for("auth.login"))
            
        flash(error)
    
    return render_template('auth/register.html')

@bp.route('login', methods=('GET', 'POST'))
def login():
    if request.method == 'POST':
        name = request.form['name']
        password = request.form['password']
        db =  get_db()
        error = None
        user = db.execute(
            'SELECT * FROM user WHERE name = ?', (name,)
        ).fetchone()

        if user is None:
            error = 'Name not found.'
        elif not check_password_hash(user['password'], password):
            error = 'Incorrect password.'

        if error is None:
            session.clear()
            session['user_id'] = user['user_id']
            return redirect(url_for('index'))
        
        flash(error)

    return render_template('auth/login.html')

@bp.before_app_request
def load_logged_in_user():
    user_id = session.get('user_id')

    if user_id is None:
        g.user = None
    else:
        g.user = get_db().execute(
            'SELECT * FROM user WHERE user_id = ?', (user_id,),
        ).fetchone()

@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# For when things require user to be logged in
def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for('auth.login'))
        
        return view(**kwargs)
    
    return wrapped_view

