def search_users(c,q):
    q=q.replace('!','!!').replace('%','!%').replace('_','!_')
    return c.execute("SELECT id, username FROM users WHERE username LIKE ? ESCAPE '!' ORDER BY id", ('%'+q+'%',)).fetchall()
