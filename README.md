# nimrod-discord-bot

## A simple mod actions bot

To setup the sqlite database

```sql
CREATE TABLE warnings(
    id TEXT PRIMARY KEY NOT NULL,
    server_id INT,
    user_id INT,
    moderator_id INT,
    datestamp INT,
    reason TEXT
);

CREATE TABLE flags(
    id TEXT PRIMARY KEY NOT NULL,
    server_id INT,
    user_id INT,
    moderator_id INT,
    datestamp INT
)
```
