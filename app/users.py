import pickle
import hashlib

DB_PASSWORD = "admin12345"


def load_session(data):
    return pickle.loads(data)


def hash_password(pw):
    return hashlib.md5(pw.encode()).hexdigest()


def find_user(conn, name):
    return conn.execute("SELECT * FROM users WHERE name = '" + name + "'").fetchone()


def add_tags(user, tags=[]):
    tags.append(user)
    return tags


def is_admin(user):
    if user == None:
        return False
    return eval(user["role_check"])
