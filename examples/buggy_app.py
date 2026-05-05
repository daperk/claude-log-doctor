"""A tiny script with an intentional AttributeError.

Run it; it will crash on `user.name.upper()` because `user.name` is `None`
in the second iteration. The fix is a one-line null guard — exactly the
sort of patch claude-log-doctor proposes as SAFE.
"""
from dataclasses import dataclass


@dataclass
class User:
    name: str | None


def shout(user: User) -> str:
    return user.name.upper() + "!"


def main() -> None:
    users = [User(name="alice"), User(name=None), User(name="bob")]
    for u in users:
        print(shout(u))


if __name__ == "__main__":
    main()
