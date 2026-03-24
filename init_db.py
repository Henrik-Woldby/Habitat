import sqlite3

conn = sqlite3.connect("database.db")

conn.executescript("""
DROP TABLE IF EXISTS password_reset_tokens;
DROP TABLE IF EXISTS friendships;
DROP TABLE IF EXISTS completed_tasks;
DROP TABLE IF EXISTS daily_logs;
DROP TABLE IF EXISTS user_tasks;
DROP TABLE IF EXISTS task_catalog;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    is_admin BOOLEAN NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT 1
);

CREATE TABLE task_catalog (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    points INTEGER NOT NULL,
    created_by_user_id INTEGER NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id)
);

CREATE TABLE user_tasks (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    task_id INTEGER NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    UNIQUE(user_id, task_id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (task_id) REFERENCES task_catalog(id)
);

CREATE TABLE daily_logs (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    UNIQUE(user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE completed_tasks (
    id INTEGER PRIMARY KEY,
    daily_log_id INTEGER NOT NULL,
    task_id INTEGER NOT NULL,
    FOREIGN KEY (daily_log_id) REFERENCES daily_logs(id),
    FOREIGN KEY (task_id) REFERENCES task_catalog(id)
);

CREATE TABLE friendships (
    id INTEGER PRIMARY KEY,
    requester_user_id INTEGER NOT NULL,
    addressee_user_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'accepted')),
    created_at TEXT NOT NULL,
    UNIQUE(requester_user_id, addressee_user_id),
    FOREIGN KEY (requester_user_id) REFERENCES users(id),
    FOREIGN KEY (addressee_user_id) REFERENCES users(id)
);

CREATE TABLE password_reset_tokens (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    token TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

INSERT INTO users (id, name, username, email, password_hash, is_admin, is_active)
VALUES (1, 'Henrik', 'henrik', 'henrik@mail.dk', NULL, 1, 1);

INSERT INTO users (id, name, username, email, password_hash, is_admin, is_active)
VALUES (2, 'Anna', 'anna', 'anna@mail.dk', NULL, 0, 1);

INSERT INTO users (id, name, username, email, password_hash, is_admin, is_active)
VALUES (3, 'Mikkel', 'mikkel', 'mikkel@mail.dk', NULL, 0, 1);
""")

conn.commit()
conn.close()

print("Database oprettet!")