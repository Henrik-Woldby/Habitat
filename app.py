from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3
from datetime import date, datetime, timedelta
import calendar
import locale
import secrets
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = "skift-denne-til-en-lang-tilfaeldig-noegle"

DAILY_GOAL = 20

# Dansk månedsnavn hvis muligt
try:
    locale.setlocale(locale.LC_TIME, "da_DK.UTF-8")
except locale.Error:
    try:
        locale.setlocale(locale.LC_TIME, "Danish_Denmark")
    except locale.Error:
        pass


def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn


def get_current_user_id():
    return session.get("user_id")


def get_current_user():
    user_id = get_current_user_id()
    if not user_id:
        return None

    db = get_db()
    user = db.execute("""
        SELECT id, name, username, email, password_hash, is_admin, is_active
        FROM users
        WHERE id = ?
    """, (user_id,)).fetchone()

    return user


def require_login():
    user = get_current_user()
    if user is None:
        return None, redirect("/login")

    if user["is_active"] != 1:
        session.pop("user_id", None)
        return None, redirect("/login")

    return user, None


def require_admin():
    user, redirect_response = require_login()
    if redirect_response:
        return None, redirect_response

    if user["is_admin"] != 1:
        return None, ("Ingen adgang", 403)

    return user, None


def calculate_streak_for_user(db, user_id, daily_goal):
    rows = db.execute("""
        SELECT dl.date, COALESCE(SUM(tc.points), 0) AS total
        FROM daily_logs dl
        LEFT JOIN completed_tasks ct ON ct.daily_log_id = dl.id
        LEFT JOIN task_catalog tc ON ct.task_id = tc.id
        WHERE dl.user_id = ?
        GROUP BY dl.date
        ORDER BY dl.date DESC
    """, (user_id,)).fetchall()

    streak = 0
    for row in rows:
        if row["total"] >= daily_goal:
            streak += 1
        else:
            break

    return streak


@app.context_processor
def inject_global_template_data():
    user = get_current_user()
    return {
        "current_user": user
    }

@app.route("/signup", methods=["GET", "POST"])
def signup():
    db = get_db()
    error_message = None

    if request.method == "POST":
        name = request.form["name"].strip()
        username = request.form["username"].strip().lower()
        email = request.form["email"].strip().lower()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not name:
            error_message = "Navn må ikke være tomt."
        elif not username:
            error_message = "Brugernavn må ikke være tomt."
        elif not email:
            error_message = "Email må ikke være tom."
        else:
            existing_username = db.execute("""
                SELECT id
                FROM users
                WHERE lower(username) = ?
            """, (username,)).fetchone()

            if existing_username is not None:
                error_message = "Brugernavn er allerede i brug."

            existing_email = db.execute("""
                SELECT id
                FROM users
                WHERE lower(email) = ?
            """, (email,)).fetchone()

            if error_message is None and existing_email is not None:
                error_message = "Email er allerede i brug."

            if error_message is None and (password or confirm_password):
                if password != confirm_password:
                    error_message = "De to passwords er ikke ens."
                elif not password:
                    error_message = "Password må ikke være tomt."

        if error_message is None:
            password_hash = generate_password_hash(password) if password else None

            cursor = db.execute("""
                INSERT INTO users (name, username, email, password_hash, is_admin, is_active)
                VALUES (?, ?, ?, ?, 0, 1)
            """, (name, username, email, password_hash))

            user_id = cursor.lastrowid
            db.commit()

            session["user_id"] = user_id
            return redirect("/welcome")

        form_data = {
            "name": name,
            "username": username,
            "email": email
        }
        return render_template("signup.html", error_message=error_message, form_data=form_data)

    return render_template("signup.html", error_message=None, form_data=None)

@app.route("/welcome")
def welcome():
    user, redirect_response = require_login()
    if redirect_response:
        return redirect_response

    db = get_db()
    user_id = user["id"]

    # Hent de 5 tasks som flest brugere har valgt
    popular_tasks = db.execute("""
        SELECT
            tc.id,
            tc.title,
            tc.points,
            COUNT(ut.user_id) AS selected_count
        FROM task_catalog tc
        LEFT JOIN user_tasks ut
            ON tc.id = ut.task_id
           AND ut.is_active = 1
        WHERE tc.is_active = 1
        GROUP BY tc.id, tc.title, tc.points
        ORDER BY selected_count DESC, tc.title ASC
        LIMIT 5
    """).fetchall()

    # Hent hvilke af dem brugeren allerede har valgt
    selected_rows = db.execute("""
        SELECT task_id
        FROM user_tasks
        WHERE user_id = ?
          AND is_active = 1
    """, (user_id,)).fetchall()

    selected_task_ids = [row["task_id"] for row in selected_rows]

    return render_template(
        "welcome.html",
        popular_tasks=popular_tasks,
        selected_task_ids=selected_task_ids
    )

@app.route("/welcome/toggle_task/<int:task_id>")
def welcome_toggle_task(task_id):
    user, redirect_response = require_login()
    if redirect_response:
        return redirect_response

    db = get_db()
    user_id = user["id"]

    task = db.execute("""
        SELECT id
        FROM task_catalog
        WHERE id = ? AND is_active = 1
    """, (task_id,)).fetchone()

    if task is None:
        return "Task findes ikke", 404

    existing = db.execute("""
        SELECT id, is_active
        FROM user_tasks
        WHERE user_id = ? AND task_id = ?
    """, (user_id, task_id)).fetchone()

    if existing:
        new_value = 0 if existing["is_active"] == 1 else 1
        db.execute("""
            UPDATE user_tasks
            SET is_active = ?
            WHERE id = ?
        """, (new_value, existing["id"]))
    else:
        db.execute("""
            INSERT INTO user_tasks (user_id, task_id, is_active)
            VALUES (?, ?, 1)
        """, (user_id, task_id))

    db.commit()
    return redirect("/welcome")

@app.route("/request-password-reset", methods=["GET", "POST"])
def request_password_reset():
    if request.method == "POST":
        db = get_db()
        email = request.form["email"].strip().lower()

        user = db.execute("""
            SELECT id, name, email, is_active
            FROM users
            WHERE lower(email) = ?
        """, (email,)).fetchone()

        if user is None or user["is_active"] != 1:
            return "Bruger ikke fundet", 404

        token = secrets.token_urlsafe(32)
        created_at = datetime.now()
        expires_at = created_at + timedelta(hours=1)

        db.execute("""
            INSERT INTO password_reset_tokens (user_id, token, expires_at, used_at, created_at)
            VALUES (?, ?, ?, NULL, ?)
        """, (
            user["id"],
            token,
            expires_at.isoformat(timespec="seconds"),
            created_at.isoformat(timespec="seconds")
        ))
        db.commit()

        reset_link = url_for("reset_password", token=token, _external=True)

        return render_template(
            "password_reset_requested.html",
            email=user["email"],
            reset_link=reset_link
        )

    return render_template("request_password_reset.html")

@app.route("/edit-profile", methods=["GET", "POST"])
def edit_profile():
    user, redirect_response = require_login()
    if redirect_response:
        return redirect_response

    db = get_db()
    user_id = user["id"]
    error_message = None

    if request.method == "POST":
        name = request.form["name"].strip()
        username = request.form["username"].strip().lower()
        email = request.form["email"].strip().lower()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not name:
            error_message = "Navn må ikke være tomt."
        elif not username:
            error_message = "Brugernavn må ikke være tomt."
        elif not email:
            error_message = "Email må ikke være tom."
        else:
            existing_username = db.execute("""
                SELECT id
                FROM users
                WHERE lower(username) = ?
                  AND id != ?
            """, (username, user_id)).fetchone()

            if existing_username is not None:
                error_message = "Brugernavn er allerede i brug."

            existing_email = db.execute("""
                SELECT id
                FROM users
                WHERE lower(email) = ?
                  AND id != ?
            """, (email, user_id)).fetchone()

            if error_message is None and existing_email is not None:
                error_message = "Email er allerede i brug."

            if error_message is None and (password or confirm_password):
                if password != confirm_password:
                    error_message = "De to passwords er ikke ens."
                elif not password:
                    error_message = "Password må ikke være tomt."

        if error_message is None:
            if password:
                password_hash = generate_password_hash(password)

                db.execute("""
                    UPDATE users
                    SET name = ?, username = ?, email = ?, password_hash = ?
                    WHERE id = ?
                """, (name, username, email, password_hash, user_id))
            else:
                db.execute("""
                    UPDATE users
                    SET name = ?, username = ?, email = ?
                    WHERE id = ?
                """, (name, username, email, user_id))

            db.commit()
            return redirect("/profile")

        # vis det brugeren skrev, selvom der er fejl
        user = {
            "name": name,
            "username": username,
            "email": email
        }

    return render_template("edit_profile.html", user=user, error_message=error_message)

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    db = get_db()

    token_row = db.execute("""
        SELECT prt.id, prt.user_id, prt.token, prt.expires_at, prt.used_at, u.email
        FROM password_reset_tokens prt
        JOIN users u ON u.id = prt.user_id
        WHERE prt.token = ?
    """, (token,)).fetchone()

    if token_row is None:
        return "Reset-link findes ikke", 404

    if token_row["used_at"] is not None:
        return "Dette reset-link er allerede brugt", 400

    expires_at = datetime.fromisoformat(token_row["expires_at"])
    if datetime.now() > expires_at:
        return "Dette reset-link er udløbet", 400

    if request.method == "POST":
        password = request.form["password"].strip()
        confirm_password = request.form["confirm_password"].strip()

        if not password:
            return "Password må ikke være tomt", 400

        if password != confirm_password:
            return "De to passwords er ikke ens", 400

        password_hash = generate_password_hash(password)

        db.execute("""
            UPDATE users
            SET password_hash = ?
            WHERE id = ?
        """, (password_hash, token_row["user_id"]))

        db.execute("""
            UPDATE password_reset_tokens
            SET used_at = ?
            WHERE id = ?
        """, (
            datetime.now().isoformat(timespec="seconds"),
            token_row["id"]
        ))

        db.commit()
        return redirect("/login")

    return render_template(
        "reset_password.html",
        token=token,
        email=token_row["email"]
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        db = get_db()
        email = request.form["email"].strip().lower()
        password = request.form.get("password", "").strip()

        user = db.execute("""
            SELECT id, name, username, email, password_hash, is_admin, is_active
            FROM users
            WHERE lower(email) = ?
        """, (email,)).fetchone()

        if user is None:
            return "Bruger ikke fundet", 404

        if user["is_active"] != 1:
            return "Brugeren er deaktiveret", 403

        stored_hash = user["password_hash"]

        # Hvis der findes password-hash, skal password valideres
        if stored_hash:
            if not password:
                return "Password mangler", 400

            if not check_password_hash(stored_hash, password):
                return "Forkert password", 403

        # Hvis der ikke findes hash, tillades login kun via email
        session["user_id"] = user["id"]
        return redirect("/")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect("/login")


@app.route("/profile")
def profile():
    user, redirect_response = require_login()
    if redirect_response:
        return redirect_response

    return render_template("profile.html", user=user)


@app.route("/")
def index():
    user, redirect_response = require_login()
    if redirect_response:
        return redirect_response

    db = get_db()
    user_id = user["id"]
    today = str(date.today())

    selected_count_row = db.execute("""
        SELECT COUNT(*) AS task_count
        FROM user_tasks
        WHERE user_id = ?
          AND is_active = 1
    """, (user_id,)).fetchone()
    
    if selected_count_row["task_count"] == 0:
        return redirect("/welcome")

    db.execute("""
        INSERT OR IGNORE INTO daily_logs (user_id, date)
        VALUES (?, ?)
    """, (user_id, today))
    db.commit()

    tasks = db.execute("""
        SELECT tc.id, tc.title, tc.points
        FROM user_tasks ut
        JOIN task_catalog tc ON ut.task_id = tc.id
        WHERE ut.user_id = ?
          AND ut.is_active = 1
          AND tc.is_active = 1
        ORDER BY tc.title
    """, (user_id,)).fetchall()

    completed = db.execute("""
        SELECT ct.task_id
        FROM completed_tasks ct
        JOIN daily_logs dl ON ct.daily_log_id = dl.id
        WHERE dl.user_id = ? AND dl.date = ?
    """, (user_id, today)).fetchall()

    completed_ids = [row["task_id"] for row in completed]

    points_row = db.execute("""
        SELECT COALESCE(SUM(tc.points), 0) AS total_points
        FROM completed_tasks ct
        JOIN daily_logs dl ON ct.daily_log_id = dl.id
        JOIN task_catalog tc ON ct.task_id = tc.id
        WHERE dl.user_id = ? AND dl.date = ?
    """, (user_id, today)).fetchone()

    points = points_row["total_points"]

    progress = int((points / DAILY_GOAL) * 100) if DAILY_GOAL > 0 else 0
    if progress > 100:
        progress = 100

    streak = calculate_streak_for_user(db, user_id, DAILY_GOAL)

    return render_template(
        "index.html",
        tasks=tasks,
        completed=completed_ids,
        points=points,
        progress=progress,
        streak=streak,
        daily_goal=DAILY_GOAL
    )


@app.route("/toggle/<int:task_id>")
def toggle(task_id):
    user, redirect_response = require_login()
    if redirect_response:
        return redirect_response

    db = get_db()
    user_id = user["id"]
    today = str(date.today())

    # Sørg for at tasken faktisk er valgt af brugeren og aktiv
    allowed_task = db.execute("""
        SELECT tc.id
        FROM user_tasks ut
        JOIN task_catalog tc ON tc.id = ut.task_id
        WHERE ut.user_id = ?
          AND ut.task_id = ?
          AND ut.is_active = 1
          AND tc.is_active = 1
    """, (user_id, task_id)).fetchone()

    if allowed_task is None:
        return "Task er ikke tilgængelig for denne bruger", 403

    db.execute("""
        INSERT OR IGNORE INTO daily_logs (user_id, date)
        VALUES (?, ?)
    """, (user_id, today))
    db.commit()

    log_row = db.execute("""
        SELECT id
        FROM daily_logs
        WHERE user_id = ? AND date = ?
    """, (user_id, today)).fetchone()

    log_id = log_row["id"]

    exists = db.execute("""
        SELECT id
        FROM completed_tasks
        WHERE daily_log_id = ? AND task_id = ?
    """, (log_id, task_id)).fetchone()

    if exists:
        db.execute("""
            DELETE FROM completed_tasks
            WHERE id = ?
        """, (exists["id"],))
    else:
        db.execute("""
            INSERT INTO completed_tasks (daily_log_id, task_id)
            VALUES (?, ?)
        """, (log_id, task_id))

    db.commit()
    return redirect("/")


@app.route("/manage_tasks")
def manage_tasks():
    user, redirect_response = require_login()
    if redirect_response:
        return redirect_response

    db = get_db()
    user_id = user["id"]

    all_tasks = db.execute("""
        SELECT
            tc.id,
            tc.title,
            tc.points,
            tc.created_by_user_id,
            CASE
                WHEN ut.user_id IS NOT NULL AND ut.is_active = 1 THEN 1
                ELSE 0
            END AS selected
        FROM task_catalog tc
        LEFT JOIN user_tasks ut
            ON tc.id = ut.task_id
           AND ut.user_id = ?
        WHERE tc.is_active = 1
        ORDER BY tc.title
    """, (user_id,)).fetchall()

    return render_template(
        "manage_tasks.html",
        all_tasks=all_tasks,
        current_user_id=user_id
    )


@app.route("/toggle_user_task/<int:task_id>")
def toggle_user_task(task_id):
    user, redirect_response = require_login()
    if redirect_response:
        return redirect_response

    db = get_db()
    user_id = user["id"]

    task = db.execute("""
        SELECT id
        FROM task_catalog
        WHERE id = ? AND is_active = 1
    """, (task_id,)).fetchone()

    if task is None:
        return "Task findes ikke", 404

    existing = db.execute("""
        SELECT id, is_active
        FROM user_tasks
        WHERE user_id = ? AND task_id = ?
    """, (user_id, task_id)).fetchone()

    if existing:
        new_value = 0 if existing["is_active"] == 1 else 1
        db.execute("""
            UPDATE user_tasks
            SET is_active = ?
            WHERE id = ?
        """, (new_value, existing["id"]))
    else:
        db.execute("""
            INSERT INTO user_tasks (user_id, task_id, is_active)
            VALUES (?, ?, 1)
        """, (user_id, task_id))

    db.commit()
    return redirect("/manage_tasks")


@app.route("/create_task", methods=["POST"])
def create_task():
    user, redirect_response = require_login()
    if redirect_response:
        return redirect_response

    db = get_db()
    user_id = user["id"]

    title = request.form["title"].strip()
    points = int(request.form["points"])

    cursor = db.execute("""
        INSERT INTO task_catalog (title, points, created_by_user_id, is_active)
        VALUES (?, ?, ?, 1)
    """, (title, points, user_id))

    new_task_id = cursor.lastrowid

    db.execute("""
        INSERT INTO user_tasks (user_id, task_id, is_active)
        VALUES (?, ?, 1)
    """, (user_id, new_task_id))

    db.commit()
    return redirect("/manage_tasks")


@app.route("/edit_task/<int:task_id>", methods=["GET", "POST"])
def edit_task(task_id):
    user, redirect_response = require_login()
    if redirect_response:
        return redirect_response

    db = get_db()
    user_id = user["id"]

    task = db.execute("""
        SELECT id, title, points, created_by_user_id
        FROM task_catalog
        WHERE id = ? AND is_active = 1
    """, (task_id,)).fetchone()

    if task is None:
        return "Task findes ikke", 404

    if task["created_by_user_id"] != user_id:
        return "Du har ikke adgang til at redigere denne task", 403

    if request.method == "POST":
        title = request.form["title"].strip()
        points = int(request.form["points"])

        db.execute("""
            UPDATE task_catalog
            SET title = ?, points = ?
            WHERE id = ?
        """, (title, points, task_id))
        db.commit()

        return redirect("/manage_tasks")

    return render_template("edit_task.html", task=task)


@app.route("/day/<selected_date>")
def day_detail(selected_date):
    user, redirect_response = require_login()
    if redirect_response:
        return redirect_response

    db = get_db()
    user_id = user["id"]

    tasks = db.execute("""
        SELECT tc.title, tc.points
        FROM completed_tasks ct
        JOIN task_catalog tc ON ct.task_id = tc.id
        JOIN daily_logs dl ON ct.daily_log_id = dl.id
        WHERE dl.user_id = ? AND dl.date = ?
    """, (user_id, selected_date)).fetchall()

    total = sum(task["points"] for task in tasks)

    return render_template(
        "day.html",
        tasks=tasks,
        total=total,
        date=selected_date
    )


@app.route("/calendar")
def calendar_view():
    user, redirect_response = require_login()
    if redirect_response:
        return redirect_response

    db = get_db()
    user_id = user["id"]

    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)

    if not year or not month:
        today = datetime.today()
        year = today.year
        month = today.month

    if month < 1:
        month = 1
    if month > 12:
        month = 12

    current_date = datetime(year, month, 1)
    month_name = current_date.strftime("%B").capitalize()

    rows = db.execute("""
        SELECT dl.date, COALESCE(SUM(tc.points), 0) AS total
        FROM daily_logs dl
        LEFT JOIN completed_tasks ct ON ct.daily_log_id = dl.id
        LEFT JOIN task_catalog tc ON ct.task_id = tc.id
        WHERE dl.user_id = ?
        GROUP BY dl.date
    """, (user_id,)).fetchall()

    data = {row["date"]: row["total"] for row in rows}
    cal = calendar.monthcalendar(year, month)

    if month == 1:
        prev_month = 12
        prev_year = year - 1
    else:
        prev_month = month - 1
        prev_year = year

    if month == 12:
        next_month = 1
        next_year = year + 1
    else:
        next_month = month + 1
        next_year = year

    today_str = str(date.today())

    return render_template(
        "calendar.html",
        calendar=cal,
        year=year,
        month=month,
        month_name=month_name,
        data=data,
        daily_goal=DAILY_GOAL,
        prev_month=prev_month,
        prev_year=prev_year,
        next_month=next_month,
        next_year=next_year,
        today=today_str
    )


@app.route("/friends")
def friends():
    user, redirect_response = require_login()
    if redirect_response:
        return redirect_response

    db = get_db()
    user_id = user["id"]
    today = str(date.today())

    friends_rows = db.execute("""
        SELECT u.id, u.name, u.username, u.email
        FROM friendships f
        JOIN users u
            ON (
                (f.requester_user_id = ? AND u.id = f.addressee_user_id)
                OR
                (f.addressee_user_id = ? AND u.id = f.requester_user_id)
            )
        WHERE f.status = 'accepted'
          AND (f.requester_user_id = ? OR f.addressee_user_id = ?)
          AND u.is_active = 1
    """, (user_id, user_id, user_id, user_id)).fetchall()

    friends_with_status = []

    for friend in friends_rows:
        points_row = db.execute("""
            SELECT COALESCE(SUM(tc.points), 0) AS total_points
            FROM daily_logs dl
            LEFT JOIN completed_tasks ct ON ct.daily_log_id = dl.id
            LEFT JOIN task_catalog tc ON ct.task_id = tc.id
            WHERE dl.user_id = ? AND dl.date = ?
        """, (friend["id"], today)).fetchone()

        points_today = points_row["total_points"] if points_row else 0
        streak = calculate_streak_for_user(db, friend["id"], DAILY_GOAL)

        friends_with_status.append({
            "id": friend["id"],
            "name": friend["name"],
            "username": friend["username"],
            "email": friend["email"],
            "points_today": points_today,
            "goal_reached": points_today >= DAILY_GOAL,
            "streak": streak
        })

    incoming_requests = db.execute("""
        SELECT f.id, u.name, u.username, u.email, f.created_at
        FROM friendships f
        JOIN users u ON u.id = f.requester_user_id
        WHERE f.addressee_user_id = ?
          AND f.status = 'pending'
          AND u.is_active = 1
        ORDER BY f.created_at DESC
    """, (user_id,)).fetchall()

    pending_requests = db.execute("""
        SELECT f.id, u.name, u.username, u.email, f.created_at
        FROM friendships f
        JOIN users u ON u.id = f.addressee_user_id
        WHERE f.requester_user_id = ?
          AND f.status = 'pending'
          AND u.is_active = 1
        ORDER BY f.created_at DESC
    """, (user_id,)).fetchall()

    return render_template(
        "friends.html",
        friends=friends_with_status,
        incoming_requests=incoming_requests,
        pending_requests=pending_requests,
        daily_goal=DAILY_GOAL
    )


@app.route("/send_friend_request", methods=["POST"])
def send_friend_request():
    user, redirect_response = require_login()
    if redirect_response:
        return redirect_response

    db = get_db()
    user_id = user["id"]
    email = request.form["email"].strip().lower()

    if not email:
        return redirect("/friends")

    target_user = db.execute("""
        SELECT id, username, email, is_active
        FROM users
        WHERE lower(email) = ?
    """, (email,)).fetchone()

    if target_user is None:
        return "Bruger ikke fundet", 404

    if target_user["is_active"] != 1:
        return "Bruger er ikke aktiv", 403

    if target_user["id"] == user_id:
        return redirect("/friends")

    existing = db.execute("""
        SELECT id
        FROM friendships
        WHERE
            (requester_user_id = ? AND addressee_user_id = ?)
            OR
            (requester_user_id = ? AND addressee_user_id = ?)
    """, (
        user_id, target_user["id"],
        target_user["id"], user_id
    )).fetchone()

    if existing:
        return redirect("/friends")

    db.execute("""
        INSERT INTO friendships (requester_user_id, addressee_user_id, status, created_at)
        VALUES (?, ?, 'pending', ?)
    """, (
        user_id,
        target_user["id"],
        datetime.now().isoformat(timespec="seconds")
    ))

    db.commit()
    return redirect("/friends")


@app.route("/accept_friend_request/<int:friendship_id>", methods=["POST"])
def accept_friend_request(friendship_id):
    user, redirect_response = require_login()
    if redirect_response:
        return redirect_response

    db = get_db()
    user_id = user["id"]

    friendship = db.execute("""
        SELECT id
        FROM friendships
        WHERE id = ?
          AND addressee_user_id = ?
          AND status = 'pending'
    """, (friendship_id, user_id)).fetchone()

    if friendship is None:
        return "Venneanmodning findes ikke", 404

    db.execute("""
        UPDATE friendships
        SET status = 'accepted'
        WHERE id = ?
    """, (friendship_id,))

    db.commit()
    return redirect("/friends")


@app.route("/admin")
def admin():
    user, admin_response = require_admin()
    if admin_response:
        return admin_response

    db = get_db()

    users = db.execute("""
        SELECT id, name, username, email, is_admin, is_active
        FROM users
        ORDER BY name
    """).fetchall()

    tasks = db.execute("""
        SELECT tc.id, tc.title, tc.points, tc.is_active, u.name AS creator_name
        FROM task_catalog tc
        LEFT JOIN users u ON u.id = tc.created_by_user_id
        ORDER BY tc.title
    """).fetchall()

    return render_template("admin.html", users=users, tasks=tasks)


@app.route("/admin/toggle_user/<int:target_user_id>", methods=["POST"])
def admin_toggle_user(target_user_id):
    user, admin_response = require_admin()
    if admin_response:
        return admin_response

    db = get_db()

    target_user = db.execute("""
        SELECT id, is_admin, is_active
        FROM users
        WHERE id = ?
    """, (target_user_id,)).fetchone()

    if target_user is None:
        return "Bruger findes ikke", 404

    if target_user["id"] == user["id"]:
        return "Du kan ikke deaktivere dig selv", 403

    new_value = 0 if target_user["is_active"] == 1 else 1

    db.execute("""
        UPDATE users
        SET is_active = ?
        WHERE id = ?
    """, (new_value, target_user_id))

    db.commit()
    return redirect("/admin")


@app.route("/admin/toggle_task/<int:task_id>", methods=["POST"])
def admin_toggle_task(task_id):
    user, admin_response = require_admin()
    if admin_response:
        return admin_response

    db = get_db()

    task = db.execute("""
        SELECT id, is_active
        FROM task_catalog
        WHERE id = ?
    """, (task_id,)).fetchone()

    if task is None:
        return "Task findes ikke", 404

    new_value = 0 if task["is_active"] == 1 else 1

    db.execute("""
        UPDATE task_catalog
        SET is_active = ?
        WHERE id = ?
    """, (new_value, task_id))

    db.commit()
    return redirect("/admin")


import os

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )