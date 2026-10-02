import itertools

from accounts.models import User
from clients.models import Client

_seq = itertools.count(1)
PASSWORD = "Str0ng-test-pass!"


def make_user(role=User.Role.MEMBER, **kwargs):
    n = next(_seq)
    kwargs.setdefault("email", f"user{n}@firm.test")
    kwargs.setdefault("first_name", f"User{n}")
    return User.objects.create_user(password=PASSWORD, role=role, **kwargs)


def make_admin(**kwargs):
    return make_user(role=User.Role.ADMIN, **kwargs)


def make_client(owner=None, **kwargs):
    n = next(_seq)
    kwargs.setdefault("name", f"Asiakas {n} Oy")
    kwargs.setdefault("email", f"client{n}@example.test")
    return Client.objects.create(owner=owner, **kwargs)
