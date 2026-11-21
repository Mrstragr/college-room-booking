
# College Lab / Room Booking System

A web-based application for managing college laboratories and classroom reservations.

## Features

### Student
- Student registration and login
- Browse available rooms
- Book rooms for specific time slots
- View personal bookings
- Cancel confirmed bookings

### Administrator
- Admin login
- Add and manage rooms
- View all reservations
- Cancel bookings
- Schedule and cancel maintenance

### Database Integrity
- PostgreSQL database
- Foreign-key relationships
- Prevention of overlapping confirmed bookings
- Append-only booking history
- Database-level concurrency protection

## Technology Stack

| Component | Technology |
|---|---|
| Frontend | HTML, CSS, Bootstrap |
| Backend | Python Flask |
| Database | PostgreSQL |
| Database Driver | Psycopg |
| Authentication | Flask sessions |
| Password Security | Werkzeug password hashing |
| Testing | Python, Requests |

## Database Tables

1. users
2. rooms
3. bookings
4. booking_history
5. maintenance

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Mrstragr/college-room-booking.git
cd college-room-booking
```

### 2. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create PostgreSQL database

```bash
createdb college_room_booking
```

### 5. Configure environment

Create a `.env` file:

```env
SECRET_KEY=your-random-secret-key
DATABASE_URL=postgresql://localhost:5432/college_room_booking
```

### 6. Create database schema

```bash
psql -d college_room_booking -f database/final_schema.sql
```

### 7. Create administrator

```bash
flask --app app create-admin
```

### 8. Run application

```bash
python app.py
```

Open:

http://127.0.0.1:5001

## Concurrency Testing

Run:

```bash
python tests/test_concurrency.py
```

Expected result for 50 simultaneous overlapping booking requests:

- Total requests: 50
- Successful bookings: 1
- Rejected bookings: 49
- Unexpected errors: 0

## Project Objective

To provide a simple and reliable room reservation system that prevents double bookings through database-level integrity constraints.
