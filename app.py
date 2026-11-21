import os
import sys
from getpass import getpass
from datetime import datetime

import psycopg
from flask import Flask, render_template, request, redirect, url_for, session, flash
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from psycopg.errors import UniqueViolation, ExclusionViolation, ForeignKeyViolation

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-development-secret")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://localhost:5432/college_room_booking"
)


def db():
    return psycopg.connect(DATABASE_URL)


def current_user():
    return session.get("user")


def login_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        if current_user().get("role") != "ADMIN":
            flash("Administrator access is required.", "danger")
            return redirect(url_for("student"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/")
def index():
    if not current_user():
        return redirect(url_for("login"))
    return redirect(url_for("admin" if current_user()["role"] == "ADMIN" else "student"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 8:
            flash("Enter your name, a valid email and a password of at least 8 characters.", "danger")
            return render_template("register.html")
        try:
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO users (name, email, password_hash, role)
                           VALUES (%s, %s, %s, 'STUDENT')""",
                        (name, email, generate_password_hash(password, method="pbkdf2:sha256"))
                    )
            flash("Registration successful. Please log in.", "success")
            return redirect(url_for("login"))
        except UniqueViolation:
            flash("That email is already registered.", "danger")
        except Exception:
            app.logger.exception("Registration error")
            flash("Could not create account. Please try again.", "danger")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name, email, password_hash, role FROM users WHERE email = %s",
                    (email,)
                )
                row = cur.fetchone()
        if row and check_password_hash(row[3], password):
            session.clear()
            session["user"] = {"id": row[0], "name": row[1], "email": row[2], "role": row[4]}
            return redirect(url_for("index"))
        flash("Incorrect email or password.", "danger")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/student")
@login_required
def student():
    if current_user()["role"] == "ADMIN":
        return redirect(url_for("admin"))
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, room_name, room_type, capacity, location, description
                FROM rooms
                WHERE is_active = TRUE
                ORDER BY room_name
            """)
            rooms = cur.fetchall()
            cur.execute("""
                SELECT b.id, r.room_name, b.start_time, b.end_time, b.purpose, b.status
                FROM bookings b JOIN rooms r ON r.id = b.room_id
                WHERE b.user_id = %s
                ORDER BY b.start_time DESC
            """, (current_user()["id"],))
            bookings = cur.fetchall()
    return render_template("student.html", rooms=rooms, bookings=bookings)


@app.route("/book", methods=["POST"])
@login_required
def book():
    if current_user()["role"] != "STUDENT":
        flash("Only student accounts can create bookings.", "danger")
        return redirect(url_for("index"))
    try:
        room_id = int(request.form["room_id"])
        start = datetime.fromisoformat(request.form["start_time"])
        end = datetime.fromisoformat(request.form["end_time"])
        purpose = request.form.get("purpose", "").strip()
        if end <= start or not purpose:
            raise ValueError()
        with db() as conn:
            with conn.cursor() as cur:
                # Check room status and maintenance window inside the same transaction.
                cur.execute("SELECT is_active FROM rooms WHERE id = %s FOR UPDATE", (room_id,))
                room = cur.fetchone()
                if not room or not room[0]:
                    flash("This room is not currently available.", "danger")
                    return redirect(url_for("student"))
                cur.execute("""
                    SELECT 1 FROM maintenance
                    WHERE room_id = %s AND status = 'SCHEDULED'
                      AND tstzrange(start_time, end_time, '[)') &&
                          tstzrange(%s, %s, '[)')
                    LIMIT 1
                """, (room_id, start, end))
                if cur.fetchone():
                    flash("This room is scheduled for maintenance during that time.", "danger")
                    return redirect(url_for("student"))
                cur.execute("""
                    INSERT INTO bookings (room_id, user_id, start_time, end_time, purpose)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (room_id, current_user()["id"], start, end, purpose))
                booking_id = cur.fetchone()[0]
                cur.execute("""
                    INSERT INTO booking_history (booking_id, action, performed_by, details)
                    VALUES (%s, 'CREATED', %s, %s)
                """, (booking_id, current_user()["id"], "Booking created"))
        flash("Room booked successfully!", "success")
    except ExclusionViolation:
        flash("Slot no longer available. Another booking overlaps this time.", "danger")
    except (ValueError, KeyError):
        flash("Please enter a valid room, date, time and purpose. End time must be after start time.", "danger")
    except Exception:
        app.logger.exception("Booking failed")
        flash("Booking could not be completed.", "danger")
    return redirect(url_for("student"))


@app.route("/cancel/<int:booking_id>", methods=["POST"])
@login_required
def cancel_booking(booking_id):
    try:
        with db() as conn:
            with conn.cursor() as cur:
                if current_user()["role"] == "ADMIN":
                    cur.execute("""
                        UPDATE bookings SET status = 'CANCELLED'
                        WHERE id = %s AND status = 'CONFIRMED'
                        RETURNING user_id
                    """, (booking_id,))
                else:
                    cur.execute("""
                        UPDATE bookings SET status = 'CANCELLED'
                        WHERE id = %s AND user_id = %s AND status = 'CONFIRMED'
                        RETURNING user_id
                    """, (booking_id, current_user()["id"]))
                row = cur.fetchone()
                if not row:
                    flash("Booking not found or already cancelled.", "warning")
                else:
                    cur.execute("""
                        INSERT INTO booking_history (booking_id, action, performed_by, details)
                        VALUES (%s, 'CANCELLED', %s, %s)
                    """, (booking_id, current_user()["id"], "Booking cancelled"))
                    flash("Booking cancelled.", "success")
    except Exception:
        app.logger.exception("Cancellation failed")
        flash("Could not cancel booking.", "danger")
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def admin():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, room_name, room_type, capacity, location, is_active FROM rooms ORDER BY id DESC")
            rooms = cur.fetchall()
            cur.execute("""
                SELECT b.id, r.room_name, u.name, u.email, b.start_time, b.end_time, b.purpose, b.status
                FROM bookings b
                JOIN rooms r ON r.id = b.room_id
                JOIN users u ON u.id = b.user_id
                ORDER BY b.start_time DESC
            """)
            bookings = cur.fetchall()
            cur.execute("""
                SELECT m.id, r.room_name, m.start_time, m.end_time, m.reason, m.status
                FROM maintenance m JOIN rooms r ON r.id = m.room_id
                ORDER BY m.start_time DESC
            """)
            maintenance = cur.fetchall()
    return render_template("admin.html", rooms=rooms, bookings=bookings, maintenance=maintenance)


@app.route("/admin/rooms", methods=["POST"])
@admin_required
def add_room():
    name = request.form.get("room_name", "").strip()
    room_type = request.form.get("room_type", "LAB")
    location = request.form.get("location", "").strip()
    description = request.form.get("description", "").strip()
    try:
        capacity = int(request.form.get("capacity", "0"))
        if not name or capacity < 1 or room_type not in ("LAB", "CLASSROOM"):
            raise ValueError()
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO rooms (room_name, room_type, capacity, location, description)
                    VALUES (%s, %s, %s, %s, %s)
                """, (name, room_type, capacity, location, description))
        flash("Room added successfully.", "success")
    except UniqueViolation:
        flash("A room with that name already exists.", "danger")
    except ValueError:
        flash("Enter a room name and a valid capacity.", "danger")
    except Exception:
        app.logger.exception("Add room failed")
        flash("Could not add room.", "danger")
    return redirect(url_for("admin"))


@app.route("/admin/rooms/<int:room_id>/toggle", methods=["POST"])
@admin_required
def toggle_room(room_id):
    try:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE rooms SET is_active = NOT is_active WHERE id = %s", (room_id,))
        flash("Room availability updated.", "success")
    except Exception:
        app.logger.exception("Room update failed")
        flash("Could not update room.", "danger")
    return redirect(url_for("admin"))


@app.route("/admin/maintenance", methods=["POST"])
@admin_required
def add_maintenance():
    try:
        room_id = int(request.form["room_id"])
        start = datetime.fromisoformat(request.form["start_time"])
        end = datetime.fromisoformat(request.form["end_time"])
        reason = request.form.get("reason", "").strip()
        if end <= start:
            raise ValueError()
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 1 FROM bookings
                    WHERE room_id = %s AND status = 'CONFIRMED'
                      AND tstzrange(start_time, end_time, '[)') &&
                          tstzrange(%s, %s, '[)')
                    LIMIT 1
                """, (room_id, start, end))
                if cur.fetchone():
                    flash("Cannot schedule maintenance: a confirmed booking overlaps this period.", "danger")
                    return redirect(url_for("admin"))
                cur.execute("""
                    INSERT INTO maintenance (room_id, start_time, end_time, reason)
                    VALUES (%s, %s, %s, %s)
                """, (room_id, start, end, reason))
        flash("Maintenance period added.", "success")
    except (ValueError, KeyError):
        flash("Enter valid maintenance dates and times.", "danger")
    except Exception:
        app.logger.exception("Maintenance creation failed")
        flash("Could not schedule maintenance.", "danger")
    return redirect(url_for("admin"))


@app.route("/admin/maintenance/<int:maintenance_id>/cancel", methods=["POST"])
@admin_required
def cancel_maintenance(maintenance_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE maintenance SET status = 'CANCELLED' WHERE id = %s", (maintenance_id,))
    flash("Maintenance cancelled.", "success")
    return redirect(url_for("admin"))


@app.cli.command("create-admin")
def create_admin():
    name = input("Admin name: ").strip()
    email = input("Admin email: ").strip().lower()
    password = getpass("Admin password (minimum 8 characters): ")
    if not name or not email or len(password) < 8:
        print("Name/email required and password must be at least 8 characters.")
        return
    try:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO users (name, email, password_hash, role)
                    VALUES (%s, %s, %s, 'ADMIN')
                """, (name, email, generate_password_hash(password, method="pbkdf2:sha256")))
        print("Admin account created.")
    except UniqueViolation:
        print("That email already exists.")


if __name__ == "__main__":
    app.run(debug=True, port=5001)