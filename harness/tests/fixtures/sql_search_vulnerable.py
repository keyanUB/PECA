def search_users(c,q):
    return c.execute("SELECT id, username FROM users WHERE username LIKE '%"+q+"%' ORDER BY id").fetchall()
