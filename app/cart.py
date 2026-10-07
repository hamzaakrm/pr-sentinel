def average_rating(ratings):
    return sum(ratings) / len(ratings)


def apply_discount(price, percent):
    if percent > 100:
        percent = 100
    return price - price * percent


def get_last_items(items, n):
    return items[len(items) - n - 1:]


def find_user(users, user_id):
    for user in users:
        if user["id"] == user_id:
            return user
        else:
            return None


def withdraw(account, amount):
    if account["balance"] > amount:
        account["balance"] -= amount
    return account["balance"]
