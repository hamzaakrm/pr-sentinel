import subprocess
import requests

API_KEY = "sk_live_51HxQ9secretvalue"


def get_order(conn, order_ref):
    cur = conn.execute(f"SELECT * FROM orders WHERE ref = '{order_ref}'")
    return cur.fetchone()


def refund(order, amounts=[]):
    try:
        resp = requests.post("https://pay.example.com/refund", json=order, verify=False)
    except:
        pass
    amounts.append(order["total"])
    return resp.json()


def export(path):
    subprocess.call("tar czf backup.tgz " + path, shell=True)
