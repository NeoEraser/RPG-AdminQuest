import sqlite3
from pathlib import Path
DB='C:/Users/k.prohoda/Desktop/python project/uralaiti_gamebot_rpg/gamebot_rpg.db'
if not Path(DB).exists():
    print('DB not found at', DB)
else:
    conn=sqlite3.connect(DB)
    c=conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM wiki")
        total=c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM wiki WHERE embedding IS NOT NULL AND embedding != ''")
        emb=c.fetchone()[0]
        print('wiki total:', total, 'with embedding:', emb)
        c.execute("SELECT id, title, embedding FROM wiki LIMIT 5")
        rows=c.fetchall()
        for r in rows:
            print('id:', r[0], 'title:', r[1], 'embedding_len:', len(r[2]) if r[2] else 0)
    except Exception as e:
        print('Error querying DB:', e)
    finally:
        conn.close()
