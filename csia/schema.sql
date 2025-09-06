DROP TABLE IF EXISTS user;
DROP TABLE IF EXISTS requester;
DROP TABLE IF EXISTS certifier;
DROP TABLE IF EXISTS tasks;

CREATE TABLE user (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT, 
    name TEXT UNIQUE NOT NULL, 
    password TEXT NOT NULL
);

CREATE TABLE requester (
    requester_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    region INTEGER NOT NULL,
    location INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES user(user_id)
);

CREATE TABLE certifier (
    certifier_id INTEGER PRIMARY KEY AUTOINCREMENT, 
    user_id INTEGER NOT NULL, 
    FOREIGN KEY (user_id) REFERENCES user(user_id)
);

CREATE TABLE tasks (
    task_id INTEGER PRIMARY KEY AUTOINCREMENT, 
    requester_id INTEGER NOT NULL, 
    certifier_id INTEGER NOT NULL, 
    time_submitted TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    time_completed TIMESTAMP DEFAULT NULL, 
    time_rejected TIMESTAMP DEFAULT NULL,
    task_name TEXT NOT NULL, 
    description TEXT, 
    project_number TEXT, 
    status TEXT DEFAULT "active", 
    FOREIGN KEY (requester_id) REFERENCES requester(requester_id),
    FOREIGN KEY (certifier_id) REFERENCES certifier(certifier_id)
);

CREATE TABLE slots (
    region INTEGER PRIMARY KEY,
    slots_left INTEGER NOT NULL,
    last_updated TIMESTAMP NOT NULL
);

INSERT INTO slots (region, slots_left, last_updated)
VALUES (1, 25, CURRENT_TIMESTAMP),
       (2, 15, CURRENT_TIMESTAMP);

