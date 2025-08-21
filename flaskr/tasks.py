from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, jsonify
)
from werkzeug.exceptions import abort

from flaskr.auth import login_required
from flaskr.db import get_db

from werkzeug.security import generate_password_hash

import datetime

bp = Blueprint('tasks', __name__)

def get_slot_count(region: int) -> int:
    db = get_db()
    now = datetime.datetime.utcnow()

    row = db.execute(
        "SELECT slots_left, last_updated FROM slots WHERE region = ?",
        (region,)
    ).fetchone()

    if row is None:
        default_slots = 25 if region == 1 else 15
        db.execute(
            "INSERT INTO slots (region, slots_left, last_updated) VALUES (?, ?, ?)",
            (region, default_slots, datetime.datetime.utcnow())
        )
        db.commit()
        return default_slots
    
    slots_left = row["slots_left"]
    last_updated = row["last_updated"]

    if now.date() != last_updated.date():
        slots_left = 25 if region == 1 else 15
        db.execute(
            "UPDATE slots SET slots_left = ?, last_updated = ? WHERE region = ?",
            (slots_left, now, region)
        )
        db.commit()
        return slots_left

    # Calculate how many 30-minute intervals have passed
    interval_minutes = 30

    delta_minutes = (now - last_updated).total_seconds() // 60
    decrements = int(delta_minutes // interval_minutes)

    if decrements > 0:
        slots_left = max(0, slots_left - decrements)
        db.execute(
            "UPDATE slots SET slots_left = ?, last_updated = ? WHERE region = ?",
            (slots_left, now, region)
        )
        db.commit()
        print(f"Decremented slots by {decrements}.")
        
    return slots_left

def check_if_certifier():
    db = get_db()

    is_certifier = db.execute(
        "SELECT 1 FROM certifier WHERE user_id = ?", (g.user['user_id'],)
    ).fetchone() is not None

    return is_certifier

def get_user_region():
    db = get_db()
    region = 0

    if not check_if_certifier():
        region = db.execute(
                '''
                SELECT region
                FROM requester
                WHERE user_id = ?
                ''',
                (g.user['user_id'],)
            ).fetchone()['region']
    
    return region

@bp.route('/')
@login_required
def index():
    db = get_db()

    is_certifier = check_if_certifier()    

    region = get_user_region()

    if is_certifier:
        # Certifier gets all tasks
        tasks = db.execute(
            '''
            SELECT t.*, r.user_id AS requester_id, ru.name AS requester_name, r.region
            FROM tasks t
            JOIN requester r ON t.requester_id = r.requester_id
            JOIN user ru ON r.user_id = ru.user_id
            WHERE 
                -- Always include active tasks
                t.status = 'active'
                OR
                -- Only include inactive tasks from today
                (t.status != 'active' AND DATE(t.time_submitted) = DATE('now', 'localtime'))
            ORDER BY t.time_submitted DESC
            '''
        ).fetchall()
    else:
        # Requester only gets their own tasks
        tasks = db.execute(
            '''
            SELECT t.*, r.user_id AS requester_id, ru.name AS requester_name, r.region
            FROM tasks t
            JOIN requester r ON t.requester_id = r.requester_id
            JOIN user ru ON r.user_id = ru.user_id
            WHERE r.user_id = ?
            AND (
                t.status = 'active'
                OR
                (t.status != 'active' AND DATE(t.time_submitted) = DATE('now', 'localtime'))
            )
            ORDER BY t.time_submitted DESC
            ''',

            (g.user['user_id'],)
        ).fetchall()

    region1_slots_left = get_slot_count(1)
    region2_slots_left = get_slot_count(2)

    return render_template(
        'tasks/index.html', 
        tasks=tasks, 
        is_certifier=is_certifier, 
        region=region,
        region1_slots_left=region1_slots_left,
        region2_slots_left=region2_slots_left 
    )

@bp.route('/submit', methods=('GET', 'POST'))
@login_required
def submit():
    db = get_db()
    region = get_user_region()
    slots_left = get_slot_count(region) 
    print(f"Slots left: {slots_left} in Region {region}")

    if request.method == 'GET' and slots_left <= 0:
        flash(f"No available slots in Region {region} left.")
        return redirect(url_for("tasks.index"))

    if request.method == 'POST':
        task_name = request.form['task_name']
        description = request.form['description']
        extra_notes = request.form['extra_notes']
        error = None

        if slots_left <= 0:
            error = f"No available slots in Region {region} left."

        if not task_name:
            error = 'Name is required.'

        if error is not None:
            flash(error)
            return redirect(url_for('tasks.index'))
        else:
            requester_row = db.execute(
                "SELECT requester_id FROM requester WHERE user_id = ?",
                (g.user['user_id'],)
            ).fetchone()
            
            if requester_row is None:
                flash("Requester profile not found.")
                return redirect(url_for('tasks.index'))

            requester_id = requester_row['requester_id']

            db.execute(
                'INSERT INTO tasks (task_name, description, extra_notes, requester_id, certifier_id) VALUES (?, ?, ?, ?, ?)',
                (task_name, description, extra_notes, requester_id, 1)  # certifier_id=1 for now
            )
            db.execute(
                'UPDATE slots SET slots_left = slots_left - 1, last_updated = ? WHERE region = ?',
                (datetime.datetime.utcnow(), region)
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
        t.status,
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

    db = get_db()

    requester_id = db.execute(
    'SELECT requester_id FROM requester WHERE user_id = ?',
    (g.user['user_id'],)
    ).fetchone()['requester_id']

    if check_author and task['requester_id'] != requester_id:
        abort(403)

    return task

@bp.route('/<int:task_id>/update', methods=('GET', 'POST'))
@login_required
def update(task_id):
    task = get_task(task_id)

    rejected = task['status'] == 'rejected'

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

            if rejected:
                db.execute(
                    "UPDATE tasks SET status = 'active' WHERE task_id = ?",
                    (task_id,)
                )

                region = db.execute(
                    'SELECT region FROM requester WHERE requester_id = ?',
                    (task['requester_id'],)
                ).fetchone()['region']
                db.execute(
                    "UPDATE slots SET slots_left = slots_left - 1, last_updated = ? WHERE region = ?",
                    (datetime.datetime.utcnow(), region)
                )

            db.commit()
            return redirect(url_for('tasks.index'))
        
    return render_template('tasks/update.html', task=task, rejected=rejected)

@bp.route('/<int:task_id>/delete', methods=('POST',))
@login_required
def delete(task_id):
    get_task(task_id)
    db = get_db()
    db.execute('DELETE FROM tasks WHERE task_id = ?', (task_id,))
    db.commit()
    return redirect(url_for('tasks.index'))     

@bp.route('/<int:task_id>/complete', methods=['POST'])
@login_required
def complete_task(task_id):
    db = get_db()
    db.execute(
        "UPDATE tasks SET status = 'completed', time_completed = ? WHERE task_id = ?",
        (datetime.datetime.utcnow(), task_id)
    )
    db.commit()
    return redirect(url_for('tasks.index'))

@bp.route('/<int:task_id>/reject', methods=['POST'])
@login_required
def reject_task(task_id):
    db = get_db()

    task = db.execute(
        '''
        SELECT r.region
        FROM tasks t
        JOIN requester r ON t.requester_id = r.requester_id
        WHERE t.task_id = ?
        ''',
        (task_id,)
    ).fetchone()

    if not task:
        flash("Task not found.")
        return redirect(url_for('tasks.index'))
    
    region = task['region']

    db.execute(
        "UPDATE tasks SET status = 'rejected' WHERE task_id = ?",
        (task_id,)
    )
    
    db.execute(
        "UPDATE slots SET slots_left = slots_left + 1, last_updated = ? WHERE region = ?",
        (datetime.datetime.utcnow(), region)
    )

    db.commit()
    return redirect(url_for('tasks.index'))

@bp.route('/<int:task_id>/reactivate', methods=['POST'])
@login_required
def reactivate_task(task_id):
    db = get_db()

    task = db.execute(
        '''
        SELECT t.task_id, r.region
        FROM tasks t
        JOIN requester r ON t.requester_id = r.requester_id
        WHERE t.task_id = ?
        ''',
        (task_id,)
    ).fetchone()

    if not task:
        flash("Task not found.")
        return redirect(url_for("tasks.index"))
    
    region = task['region']

    db.execute(
        "UPDATE tasks SET status = 'active' WHERE task_id = ?",
        (task_id,)
    )

    db.execute(
        "UPDATE slots SET slots_left = slots_left - 1, last_updated = ? WHERE region = ?",
        (datetime.datetime.utcnow(), region)
    )

    db.commit()
    # flash("Task reactivated.")
    return redirect(url_for("tasks.index"))

@bp.route('/slots/<int:region>/<string:action>', methods=['POST'])
def update_slots(region, action):
    db = get_db()

    slots_left = get_slot_count(region)

    if action == 'increment':
        slots_left += 1
    elif action == 'decrement' and slots_left > 0:
        slots_left -= 1

    db.execute(
        'UPDATE slots SET slots_left = ?, last_updated = ? WHERE region = ?',
        (slots_left, datetime.datetime.utcnow(), region)
    )
    db.commit()

    return jsonify({'slots_left': slots_left})

@bp.route("/slots/<int:region>/get", methods=['GET'])
@login_required
def get_slots(region):
    slots_left = get_slot_count(region)
    return jsonify({"slots_left": slots_left})


# Debugging section


@bp.route('/debug-db')
def debug_db():
    db = get_db()
    users = db.execute("SELECT * FROM user").fetchall()
    requesters = db.execute("SELECT * FROM requester").fetchall()
    certifiers = db.execute("SELECT * FROM certifier").fetchall()
    tasks = db.execute("SELECT * FROM tasks").fetchall()
    return {
        "users": [dict(u) for u in users],
        "requesters": [dict(r) for r in requesters],
        "certifiers": [dict(c) for c in certifiers],
        "tasks": [dict(t) for t in tasks]
    }

@bp.route('/add-certifier')
def add_certifier():
    db = get_db()

    new_certifier_name = "certifier1"

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

