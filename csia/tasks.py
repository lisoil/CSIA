from datetime import datetime, timezone

from flask import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
    jsonify,
)
from werkzeug.exceptions import abort
from werkzeug.security import generate_password_hash

from csia.auth import login_required
from csia.db import get_db

bp = Blueprint("tasks", __name__)


def check_if_certifier():
    """
    Checks if the current user is a certifier.
    Returns True if certifier, False otherwise.
    """
    db = get_db()

    is_certifier = (
        db.execute( # db.execute allows program to access database by executing SQL queries
            "SELECT 1 FROM certifier WHERE user_id = ?", (g.user["user_id"],)
        ).fetchone()
        is not None
    )

    return is_certifier


def get_region(user_id):
    """
    Retrieves the region of a user by their user ID.
    Returns 0 for certifiers, or the requester's region.
    """
    db = get_db()
    region = 0

    is_certifier = db.execute(
        "SELECT 1 FROM certifier WHERE user_id = ?", (user_id,)
    ).fetchone() is not None

    if not is_certifier:
        region = db.execute(
            """
            SELECT region
            FROM requester
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()["region"]

    return region


def get_user_region():
    """
    Retrieves the region of the current user.
    """
    user_id = g.user["user_id"]
    region = 0

    if not check_if_certifier():
        region = get_region(user_id)

    return region


def check_slots_exist(region):
    """
    Ensures that slot counts for the specified region exist in the database.
    If not, initializes them to default values.
    """
    db = get_db()
    now = datetime.now(timezone.utc)

    row = db.execute(
        "SELECT slots_left, last_updated FROM slots WHERE region = ?", (region,)
    ).fetchone()

    # If region slot counts are not initialized, set to default values
    if row is None:
        default_slots = 25 if region == 1 else 15
        db.execute(
            "INSERT INTO slots (region, slots_left, last_updated) VALUES (?, ?, ?)",
            (region, default_slots, now),
        )
        db.commit()
        return default_slots

    
def get_last_updated(region):
    """
    Retrieves the last updated timestamp for the specified region slots from the database.
    """
    db = get_db()

    last_updated = db.execute(
        "SELECT last_updated FROM slots WHERE region = ?", (region,)
    ).fetchone()['last_updated']

    # Ensure last_updated is timezone-aware
    if last_updated is not None and last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=timezone.utc)
    
    return last_updated

    
def update_slots_count(region, slots_left):
    """
    Decrements slots based on 30-minute intervals since last update.
    Resets slots daily to default values (25 for region 1, 15 for region 2).
    """
    db = get_db()
    now = datetime.now(timezone.utc)

    last_updated = get_last_updated(region)

    # Reset slots daily
    if now.date() != last_updated.date(): # If the date has changed since last update
        slots_left = 25 if region == 1 else 15
        db.execute(
            "UPDATE slots SET slots_left = ?, last_updated = ? WHERE region = ?",
            (slots_left, now, region),
        )
        db.commit()
        return slots_left

    # Calculate how many 30-minute intervals have passed, if the date is the same 
    interval_minutes = 30

    # Calculate time difference in minutes since last update
    delta_minutes = (now - last_updated).total_seconds() // 60
    decrements = int(delta_minutes // interval_minutes)

    # If intervals have passed, decrement slots accordingly
    if decrements > 0:
        slots_left = max(0, slots_left - decrements)
        db.execute(
            "UPDATE slots SET slots_left = ?, last_updated = ? WHERE region = ?",
            (slots_left, now, region),
        )
        db.commit()
        print(f"Decremented slots by {decrements}.") # Debugging statement

    return slots_left


def get_slot_count(region):
    """
    Retrieves the slot count for a given region.
    """
    db = get_db()
    
    check_slots_exist(region)

    # Retrieve current slots
    row = db.execute(
        "SELECT slots_left, last_updated FROM slots WHERE region = ?", (region,)
    ).fetchone()

    slots_left = row["slots_left"]

    # Update slots based on time elapsed
    slots_left = update_slots_count(region, slots_left)

    return slots_left


def get_task(task_id, check_author=True):
    """
    Retrieves a task by its ID.
    If check_author is True, verifies that the current user is the requester of the task.
    """
    task = (
        get_db()
        .execute(
            """
            SELECT 
                t.task_id,
                t.task_name,
                t.description,
                t.project_number,                
                t.time_completed,
                t.time_rejected,
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
            """,
            (task_id,),
        )
        .fetchone()
    )

    # Task not found
    if task is None:
        abort(404, f"Task id {task_id} doesn't exist.")

    db = get_db()

    # Check that the user is allowed to access the task    
    requester_id = db.execute(
        "SELECT requester_id FROM requester WHERE user_id = ?", (g.user["user_id"],)
    ).fetchone()["requester_id"]

    if check_author and task["requester_id"] != requester_id:
        abort(403)

    return task


@bp.route("/")
@login_required # Ensures user is logged in to access this route, redirects to login page (see auth.py)
def index():
    """
    Displays a list of tasks.  Certifiers see all tasks; requesters see only their own.
    Shows active tasks and those updated today.
    """
    db = get_db()

    is_certifier = check_if_certifier()

    region = get_user_region()

    if is_certifier:
        # Certifier gets all tasks, including all active and today's inactive (completed or rejected) tasks
        tasks = db.execute(
            """
            SELECT t.*, r.user_id AS requester_id, ru.name AS requester_name, r.region
            FROM tasks t
            JOIN requester r ON t.requester_id = r.requester_id
            JOIN user ru ON r.user_id = ru.user_id
            WHERE 
                -- Active tasks
                t.status = 'active'
                OR
                -- Inactive tasks from today
                (t.status != 'active' AND DATE(t.time_submitted) = DATE('now', 'localtime'))
                OR 
                (t.status = 'completed' AND DATE(t.time_completed) = DATE('now', 'localtime'))
                OR 
                (t.status = 'rejected' AND DATE(t.time_rejected) = DATE('now', 'localtime'))
            ORDER BY t.time_submitted DESC
            """
        ).fetchall()
    else:
        # Requester only gets their own tasks that are active or sumbitted today
        tasks = db.execute(
            """
            SELECT t.*, r.user_id AS requester_id, ru.name AS requester_name, r.region
            FROM tasks t
            JOIN requester r ON t.requester_id = r.requester_id
            JOIN user ru ON r.user_id = ru.user_id
            WHERE r.user_id = ?
            AND (
                t.status = 'active'
                OR
                (t.status != 'active' AND DATE(t.time_submitted) = DATE('now', 'localtime'))
                OR
                (t.status = 'completed' AND DATE(t.time_completed) = DATE('now', 'localtime'))
                OR 
                (t.status = 'rejected' AND DATE(t.time_rejected) = DATE('now', 'localtime'))
            )
            ORDER BY t.time_submitted DESC
            """,
            (g.user["user_id"],),
        ).fetchall()

    region1_slots_left = get_slot_count(1)
    region2_slots_left = get_slot_count(2)

    return render_template(
        "tasks/index.html",
        tasks=tasks,
        is_certifier=is_certifier,
        region=region,
        region1_slots_left=region1_slots_left,
        region2_slots_left=region2_slots_left,
    )


@bp.route("/submit", methods=("GET", "POST"))
@login_required
def submit():
    """
    Allows a requester to submit a new task, checking for available slots in their region.
    Enters task details into the database if slots are available.
    """
    db = get_db()
    region = get_user_region()
    slots_left = get_slot_count(region)

    print(f"Slots left: {slots_left} in Region {region}")

    # If no slots left, prevent GET and POST submissions (submitting a task)
    if request.method == "GET" and slots_left <= 0:
        flash(f"No available slots in Region {region} left.")
        return redirect(url_for("tasks.index")) # Redirects back to index page instead of displaying 

    if request.method == "POST": # For the form submission
        task_name = request.form["task_name"]
        description = request.form["description"]
        project_number = request.form["project_number"]

        error = None

        # Errors are listed in the order the user should encounter them
        if slots_left <= 0: # No slots left in the region
            error = f"Sorry, no available slots in Region {region} left."
        # This error will not be reached if the GET request check is working correctly

        if not task_name: # Task name is required because the database lists it as NOT NULL
            error = "Task name is required." 
        # This error will not be reached if the HTML form validation is working correctly

        if error is not None: # There were errors, flash them and redirect back to index page
            flash(error)
            return redirect(url_for("tasks.index"))
        else: # No errors in the form, proceed to attempt insert the task into the database
            requester_row = db.execute(
                "SELECT requester_id FROM requester WHERE user_id = ?",
                (g.user["user_id"],),
            ).fetchone()

            if requester_row is None: 
                flash("Requester profile not found.")
                return redirect(url_for("tasks.index"))
            # This error should not be reached if the authentication system is working correctly, but is included for safety and database integrity

            requester_id = requester_row["requester_id"]

            db.execute( # Insert the new task into the database
                "INSERT INTO tasks (task_name, description, project_number, requester_id, certifier_id) VALUES (?, ?, ?, ?, ?)",
                (
                    task_name,
                    description,
                    project_number,
                    requester_id,
                    1,
                ),  # certifier_id=1 for default certifier
            )
            db.execute( # Decrement the slot count for the requester's region
                "UPDATE slots SET slots_left = slots_left - 1, last_updated = ? WHERE region = ?",
                (datetime.now(timezone.utc), region),
            )
            db.commit()
            return redirect(url_for("tasks.index"))

    return render_template("tasks/submit.html") 


@bp.route("/<int:task_id>/update", methods=("GET", "POST"))
@login_required
def update(task_id):
    """
    Allows a requester to update an existing task.
    If the task was previously rejected, updating it will reactivate the task and decrement the slot count for the requester's region.
    """
    task = get_task(task_id)

    # Check if the task is rejected, if so, handle reactivation
    rejected = task["status"] == "rejected"

    if request.method == "POST": # Display same form as submit, but pre-filled with existing task data
        task_name = request.form["task_name"]
        description = request.form["description"]
        project_number = request.form["project_number"]

        error = None

        if not task_name:
            error = "Task name is required."

        if error is not None:
            flash(error)
        else:
            db = get_db()
            db.execute(
                "UPDATE tasks SET task_name = ?, description = ?, project_number = ? WHERE task_id = ?",
                (task_name, description, project_number, task_id),
            )

            # If the task was rejected, reactivate it and decrement slots
            if rejected:
                db.execute( # Reactivate the task
                    "UPDATE tasks SET status = 'active', time_rejected = NULL WHERE task_id = ?",
                    (task_id,),
                )

                region = get_region(task["requester_id"])

                db.execute(
                    "UPDATE slots SET slots_left = slots_left - 1, last_updated = ? WHERE region = ?",
                    (datetime.now(timezone.utc), region),
                )

            db.commit()
            print("From update: Task updated successfully.") # Debugging statement
            return redirect(url_for("tasks.index"))

    return render_template("tasks/update.html", task=task, rejected=rejected) # Pass rejected status to template to change form text


@bp.route("/<int:task_id>/delete", methods=("POST",))
@login_required
def delete(task_id):
    """
    Deletes a task from the database by its ID.
    """
    get_task(task_id)
    db = get_db()
    db.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
    db.commit()
    return redirect(url_for("tasks.index"))


@bp.route("/<int:task_id>/complete", methods=["POST"])
@login_required
def complete_task(task_id):
    """
    Marks a task as completed in the database by updating its status and completion time.
    """
    db = get_db()
    db.execute(
        "UPDATE tasks SET status = 'completed', time_completed = ? WHERE task_id = ?",
        (datetime.now(timezone.utc), task_id),
    )
    db.commit()
    return redirect(url_for("tasks.index"))


@bp.route("/<int:task_id>/reject", methods=["POST"])
@login_required
def reject_task(task_id):
    """
    Marks a task as rejected in the database and increments the slot count for the requester's region.
    """
    db = get_db()

    task = db.execute(
        """
        SELECT r.region
        FROM tasks t
        JOIN requester r ON t.requester_id = r.requester_id
        WHERE t.task_id = ?
        """,
        (task_id,),
    ).fetchone()

    if not task:
        flash("Task not found.")
        return redirect(url_for("tasks.index"))

    region = task["region"]

    db.execute(
        "UPDATE tasks SET status = 'rejected', time_rejected = ? WHERE task_id = ?",
        (
            datetime.now(timezone.utc),
            task_id,
        ),
    )

    db.execute(
        "UPDATE slots SET slots_left = slots_left + 1, last_updated = ? WHERE region = ?",
        (datetime.now(timezone.utc), region),
    )

    db.commit()
    return redirect(url_for("tasks.index"))


@bp.route("/<int:task_id>/reactivate", methods=["POST"])
@login_required
def reactivate_task(task_id):
    """
    Reactivates a rejected or completed task by updating its status as 'active' in the database.
    Decrements the slot count for the requester's region.
    Used by the certifier to reactivate tasks.
    """
    db = get_db()

    task = db.execute(
        """
        SELECT t.task_id, t.status, r.region
        FROM tasks t
        JOIN requester r ON t.requester_id = r.requester_id
        WHERE t.task_id = ?
        """,
        (task_id,),
    ).fetchone()

    if not task:
        flash("Task not found.")
        return redirect(url_for("tasks.index"))

    region = task["region"]
    rejected = task["status"] == "rejected"
    completed = task["status"] == "completed"

    if rejected:
        db.execute(
            "UPDATE tasks SET status = 'active', time_rejected = NULL WHERE task_id = ?",
            (task_id,),
        )
    elif completed:
        db.execute(
            "UPDATE tasks SET status = 'active', time_completed = NULL WHERE task_id = ?",
            (task_id,),
        )

    db.execute(
        "UPDATE slots SET slots_left = slots_left - 1, last_updated = ? WHERE region = ?",
        (datetime.now(timezone.utc), region),
    )

    db.commit()
    # flash("Task reactivated.")
    print("From reactivate_task: Task reactivated successfully.")  # Debugging statement
    return redirect(url_for("tasks.index"))


@bp.route("/slots/<int:region>/<string:action>", methods=["POST"])
def update_slots(region, action):
    """
    Updates the slot count for a given region based on the specified action ('increment' or 'decrement') in the database.
    Returns the updated slot count as JSON.
    """
    db = get_db()

    slots_left = get_slot_count(region)

    if action == "increment":
        slots_left += 1
    elif action == "decrement" and slots_left > 0:
        slots_left -= 1

    db.execute(
        "UPDATE slots SET slots_left = ?, last_updated = ? WHERE region = ?",
        (slots_left, datetime.now(timezone.utc), region),
    )
    db.commit()

    return jsonify({"slots_left": slots_left})


@bp.route("/slots/<int:region>/get", methods=["GET"])
@login_required
def get_slots(region):
    """
    Retrieves the current slot count for a given region. 
    Used for Javascript requests to update slot counts dynamically as a Flask route.
    Returns the slot count as JSON.
    """
    slots_left = get_slot_count(region)
    return jsonify({"slots_left": slots_left})


# Debugging section


@bp.route("/debug-db")
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
        "tasks": [dict(t) for t in tasks],
    }


@bp.route("/add-certifier")
def add_certifier():
    db = get_db()

    new_certifier_name = "certifier1"

    row = db.execute(
        "SELECT user_id FROM user WHERE name = ?", (new_certifier_name,)
    ).fetchone()
    if row is None:
        db.execute(
            "INSERT INTO user (name, password) VALUES (?, ?)",
            (
                new_certifier_name,
                generate_password_hash(f"{new_certifier_name}password"),
            ),
        )
        user_id = db.execute(
            "SELECT user_id FROM user WHERE name = ?", (new_certifier_name,)
        ).fetchone()["user_id"]
        db.execute("INSERT INTO certifier (user_id) VALUES (?)", (user_id,))
        db.commit()
        return "✅ Certifier created."
    return "Certifier already exists."
