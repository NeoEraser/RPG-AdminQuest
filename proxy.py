import sqlite3

# Ваш список прокси
proxy_list = [
"http://120.28.76.192:8082"

]

conn = sqlite3.connect('C:\\Users\\k.prohoda\\Desktop\\python project\\uralaiti_gamebot_rpg\\gamebot_rpg.db')
cursor = conn.cursor()

# Массовая вставка - одной командой
cursor.executemany(
    "INSERT OR IGNORE INTO proxies (proxy_url, is_working, created_at, updated_at) VALUES (?, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
    [(proxy,) for proxy in proxy_list]  # Превращаем каждый URL в кортеж
)

conn.commit()
conn.close()

print(f"Вставлено {len(proxy_list)} прокси")