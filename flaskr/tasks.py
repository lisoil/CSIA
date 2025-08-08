from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for
)
from werkzeug.exceptions import abort

from flaskr.auth import login_required
from flaskr.db import get_db

from werkzeug.security import generate_password_hash

bp = Blueprint('tasks', __name__)

# @bp.route('/')
# def index():
#     db = get_db()
#     tasks = db.execute(
#     '''
#     SELECT 
#         t.task_id,
#         t.task_name,
#         t.description,
#         t.time_submitted,
#         t.time_completed,
#         t.status_active,
#         ru.name AS requester_name,
#         cu.name AS certifier_name
#     FROM tasks t
#     JOIN requester r ON t.requester_id = r.requester_id
#     JOIN user ru ON r.user_id = ru.user_id
#     JOIN certifier c ON t.certifier_id = c.certifier_id
#     JOIN user cu ON c.user_id = cu.user_id
#     ORDER BY t.time_submitted DESC
#     '''
#     ).fetchall()
#     return render_template('tasks/index.html', tasks=tasks)

@bp.route('/')
@login_required
def index():
    db = get_db()

    # Check if the current user is a certifier
    is_certifier = db.execute(
        "SELECT 1 FROM certifier WHERE user_id = ?", (g.user['user_id'],)
    ).fetchone() is not None

    if is_certifier:
        # Certifier gets all tasks
        tasks = db.execute(
            '''
            SELECT t.*, r.user_id AS requester_id, ru.name AS requester_name
            FROM tasks t
            JOIN requester r ON t.requester_id = r.requester_id
            JOIN user ru ON r.user_id = ru.user_id
            ORDER BY t.time_submitted DESC
            '''
        ).fetchall()

    else:
        # Requester only gets their own tasks
        tasks = db.execute(
            '''
            SELECT t.*, r.user_id AS requester_id, ru.name AS requester_name
            FROM tasks t
            JOIN requester r ON t.requester_id = r.requester_id
            JOIN user ru ON r.user_id = ru.user_id
            WHERE r.user_id = ?
            ORDER BY t.time_submitted DESC
            ''',
            (g.user['user_id'],)
        ).fetchall()

    return render_template('tasks/index.html', tasks=tasks, is_certifier=is_certifier)


@bp.route('/submit', methods=('GET', 'POST'))
@login_required
def submit():
    if request.method == 'POST':
        task_name = request.form['task_name']
        description = request.form['description']
        extra_notes = request.form['extra_notes']
        error = None

        if not task_name:
            error = 'Name is required.'

        if error is not None:
            flash(error)
        else:
            db = get_db()
            db.execute(
                'INSERT INTO tasks (task_name, description, extra_notes, requester_id, certifier_id) VALUES (?, ?, ?, ?, ?)',
                (task_name, description, extra_notes, g.user['user_id'], 1)
            )
            db.commit()
            return redirect(url_for('tasks.index'))

    return render_template('tasks/submit.html')

def get_task(task_id, check_author=True):
    task = get_db().execute(
    '''
    SELECT 
        t.task_id,
        t.task_name,
        t.description,
        t.extra_notes,                
        t.time_completed,
        t.status_active,
        ru.name AS requester_name,
        cu.name AS certifier_name,
        t.requester_id
    FROM tasks t
    JOIN requester r ON t.requester_id = r.requester_id
    JOIN user ru ON r.user_id = ru.user_id
    LEFT JOIN certifier c ON t.certifier_id = c.certifier_id
    LEFT JOIN user cu ON c.user_id = cu.user_id
    WHERE t.task_id = ?
    ''',
    (task_id,)
    ).fetchone()

    if task is None:
        abort(404, f"Task id {task_id} doesn't exist.")

    if check_author and task['requester_id'] != g.user['user_id']:
        abort(403)

    return task

@bp.route('/<int:task_id>/update', methods=('GET', 'POST'))
@login_required
def update(task_id):
    task = get_task(task_id)

    if request.method == 'POST':
        task_name = request.form['task_name']
        description = request.form['description']
        extra_notes = request.form['extra_notes']
        error = None

        if not task_name:
            error = "Task is required."
        
        if error is not None:
            flash(error)
        else:
            db = get_db()
            db.execute(
                'UPDATE tasks SET task_name = ?, description = ?, extra_notes = ? WHERE task_id = ?',
                (task_name, description, extra_notes, task_id)
            )
            db.commit()
            return redirect(url_for('tasks.index'))
        
    return render_template('tasks/update.html', task=task)

@bp.route('/<int:task_id>/delete', methods=('POST',))
@login_required
def delete(task_id):
    get_task(task_id)
    db = get_db()
    db.execute('DELETE FROM tasks WHERE task_id = ?', (task_id,))
    db.commit()
    return redirect(url_for('tasks.index'))

@bp.route('/debug-db')
def debug_db():
    db = get_db()
    users = db.execute("SELECT * FROM user").fetchall()
    requesters = db.execute("SELECT * FROM requester").fetchall()
    certifiers = db.execute("SELECT * FROM certifier").fetchall()
    return {
        "users": [dict(u) for u in users],
        "requesters": [dict(r) for r in requesters],
        "certifiers": [dict(c) for c in certifiers]
    }

@bp.route('/add-certifier')
def add_certifier():
    db = get_db()

    new_certifier_name = "certifier2"

    row = db.execute("SELECT user_id FROM user WHERE name = ?", (new_certifier_name,)).fetchone()
    if row is None:
        db.execute(
            "INSERT INTO user (name, password) VALUES (?, ?)",
            (new_certifier_name, generate_password_hash(f'{new_certifier_name}password'))
        )
        user_id = db.execute(
            "SELECT user_id FROM user WHERE name = ?", (new_certifier_name,)
        ).fetchone()["user_id"]
        db.execute("INSERT INTO certifier (user_id) VALUES (?)", (user_id,))
        db.commit()
        return "✅ Certifier created."
    return "Certifier already exists."

