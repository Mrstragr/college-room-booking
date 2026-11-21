
import threading
import getpass
from datetime import datetime

import requests
import psycopg
from dotenv import load_dotenv
import os
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

BASE_URL = "http://127.0.0.1:5001"
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://localhost:5432/college_room_booking"
)

TOTAL_REQUESTS = 50

# Use a fresh future time slot for this test.
START = datetime.fromisoformat("2026-11-28T10:00:00")
END = datetime.fromisoformat("2026-11-28T11:00:00")

email = input("Student email: ").strip()
password = getpass.getpass("Student password: ")
room_name = input("Room name (e.g. computer lab 2): ").strip()

# Find the room in PostgreSQL.
with psycopg.connect(DATABASE_URL) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM rooms WHERE LOWER(room_name) = LOWER(%s)",
            (room_name,)
        )
        row = cur.fetchone()

        if not row:
            raise SystemExit("Room not found.")

        room_id = row[0]

        # Ensure the test slot is initially free.
        cur.execute("""
            SELECT COUNT(*)
            FROM bookings
            WHERE room_id = %s
              AND status = 'CONFIRMED'
              AND start_time < %s
              AND end_time > %s
        """, (room_id, END, START))

        if cur.fetchone()[0] > 0:
            raise SystemExit(
                "This test slot already has a confirmed booking. "
                "Choose another room or time."
            )

print("\nRoom ID:", room_id)
print("Preparing", TOTAL_REQUESTS, "requests...")

# Authenticate once and copy the session cookie.
auth = requests.Session()

response = auth.post(
    BASE_URL + "/login",
    data={"email": email, "password": password}
)

if response.status_code != 200 or "/student" not in response.url:
    raise SystemExit("Login failed. Check your credentials.")

sessions = []

for _ in range(TOTAL_REQUESTS):
    s = requests.Session()
    s.cookies.update(auth.cookies)
    sessions.append(s)

# All threads wait here until they are ready.
barrier = threading.Barrier(TOTAL_REQUESTS)

results = {
    "success": 0,
    "rejected": 0,
    "unexpected": 0
}

lock = threading.Lock()


def send_booking(index):
    try:
        barrier.wait(timeout=60)

        response = sessions[index].post(
            BASE_URL + "/book",
            data={
                "room_id": room_id,
                "start_time": START.isoformat(),
                "end_time": END.isoformat(),
                "purpose": f"Concurrency test request {index + 1}"
            },
            timeout=60
        )

        with lock:
            if "Room booked successfully!" in response.text:
                results["success"] += 1

            elif "Slot no longer available" in response.text:
                results["rejected"] += 1

            else:
                results["unexpected"] += 1
                print(
                    "Unexpected response:",
                    index + 1,
                    response.status_code,
                    response.url
                )

    except Exception as error:
        with lock:
            results["unexpected"] += 1
        print("Request error:", index + 1, error)


print("\nSending 50 simultaneous requests...\n")

with ThreadPoolExecutor(max_workers=TOTAL_REQUESTS) as executor:
    list(executor.map(send_booking, range(TOTAL_REQUESTS)))

print("\n========== TEST RESULTS ==========")
print("Total requests :", TOTAL_REQUESTS)
print("Successful     :", results["success"])
print("Rejected       :", results["rejected"])
print("Unexpected     :", results["unexpected"])

if results["success"] == 1 and results["rejected"] == 49:
    print("\nPASS: Exactly one booking was accepted!")
else:
    print("\nCHECK: Results did not match the expected outcome.")
