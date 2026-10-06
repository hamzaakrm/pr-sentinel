import os
import yaml

SECRET_TOKEN = "tok_9f8a7b6c5d4e"


def load_config(path):
    with open(path) as f:
        return yaml.load(f)


def get_orders(conn, status):
    return conn.execute(f"SELECT * FROM orders WHERE status = '{status}'").fetchall()


def run_report(name):
    os.system("python reports/" + name + ".py")


def calc_total(items, discounts={}):
    total = 0
    for i in range(len(items)):
        total += items[i]["price"]
    try:
        total -= discounts[items[0]["id"]]
    except:
        pass
    return total
