import sqlite3
import uuid

def open_db():
    return sqlite3.connect('nimrod.db')

def add_warn(server_id: int, user_id: int, moderator_id: int, datestamp: str, reason: str):
    try:
        conn = open_db()
        cur = conn.cursor()
        cur.execute('INSERT INTO warnings (id, server_id, user_id, moderator_id, datestamp, reason) VALUES (?, ?, ?, ?, ?, ?)', (str(uuid.uuid4()), server_id, user_id, moderator_id, datestamp, reason))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print('Failed to add warn:')
        print(e)
        return False

def del_warn(warn_id: str):
    try:
        conn = open_db()
        cur = conn.cursor()
        cur.execute('DELETE FROM warnings WHERE id = ?', (warn_id,))
        count = cur.rowcount
        conn.commit()
        conn.close()
        if count > 0:
            return True
        return False
    except Exception as e:
        print('Failed to delete warn:')
        print(e)
        return False

def add_flag(server_id: int, user_id: int, moderator_id: int, datestamp: str):
    try:
        conn = open_db()
        cur = conn.cursor()
        cur.execute('INSERT INTO flags (id, server_id, user_id, moderator_id, datestamp) VALUES (?, ?, ?, ?, ?)', (str(uuid.uuid4()), server_id, user_id, moderator_id, datestamp))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print('Failed to add flag:')
        print(e)
        return False

def get_flag(user_id: int):
    conn = open_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM flags WHERE user_id = ?', (user_id,))
    row = cur.fetchone()
    conn.close()

    try:
        return {
            "id":           row[0],
            "server_id":    row[1],
            "user_id":      row[2],
            "moderator_id": row[3],
            "datestamp":    row[4]
        }
    except:
        return None

def list_warns(user_id: int):
    conn = open_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM warnings WHERE user_id = ?', (user_id,))
    results = cur.fetchall()
    conn.close()

    out = []
    if results:
        for result in results:
            out.append({
                "id":           result[0],
                "server_id":    result[1],
                "user_id":      result[2],
                "moderator_id": result[3],
                "datestamp":    result[4],
                "reason":       result[5]
            })

    return out
