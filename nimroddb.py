import aiosqlite
import uuid

async def add_warn(server_id: int, user_id: int, moderator_id: int, datestamp: str, reason: str):
    try:
        async with aiosqlite.connect('nimrod.db') as db:
            the_uuid = str(uuid.uuid4())
            await db.execute('INSERT INTO warnings (id, server_id, user_id, moderator_id, datestamp, reason) VALUES (?, ?, ?, ?, ?, ?)', (the_uuid, server_id, user_id, moderator_id, datestamp, reason))
            await db.commit()
            return the_uuid
    except Exception as e:
        print('Failed to add warn:')
        print(e, user_id, datestamp)
        return False

async def del_warn(warn_id: str):
    try:
        async with aiosqlite.connect('nimrod.db') as db:
            await db.execute('DELETE FROM warnings WHERE id = ?', (warn_id,))
            await db.commit()
        return True
    except Exception as e:
        print('Failed to delete warning:')
        print(e, warn_id)
        return False

async def list_warns(user_id: int):
    try:
        out = []
        async with aiosqlite.connect('nimrod.db') as db:
            db.row_factory = aiosqlite.Row
            async with db.execute('SELECT * FROM warnings LEFT JOIN warn_message ON warnings.id = warn_message.warn_id WHERE user_id = ?', (user_id,)) as cursor:
                async for row in cursor:
                    out.append(row)
        return out
    except Exception as e:
        print('Failed to list warns:')
        print(e, user_id)
        return False

async def add_warn_message_id(warn_id, channel_id, message_id):
    try:
        async with aiosqlite.connect('nimrod.db') as db:
            await db.execute('INSERT INTO warn_message (warn_id, channel_id, message_id) VALUES (?, ?, ?)', (warn_id, channel_id, message_id))
            await db.commit()
        return True
    except Exception as e:
        print('Failed to add warn message id:')
        print(e, warn_id, channel_id, message_id)
        return False
