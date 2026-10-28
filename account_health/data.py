"""The data the agents look up: a small built-in company, so nothing outside this repo is needed.

A source answers two questions about one account: its tickets and its opportunities.
"""

from typing import Any

_STATUSES = ["open", "solved", "pending", "solved", "new", "closed", "hold", "solved"]


def _tickets(count: int) -> list[dict[str, Any]]:
    return [{"id": i, "status": _STATUSES[i % len(_STATUSES)], "subject": f"Ticket {i}"} for i in range(count)]


# acct-1 has 40 tickets (20 open), so a reader that stops after the first 20 sees only 10 of them.
FIXTURES = {
    "acct-1": {
        "tickets": _tickets(40),
        "opportunities": [
            {"Id": "o1", "Name": "Renewal", "Amount": 40000.0, "StageName": "Negotiation", "IsClosed": False},
            {"Id": "o2", "Name": "Upsell", "Amount": 25000.0, "StageName": "Proposal", "IsClosed": False},
            {"Id": "o3", "Name": "Add-on", "Amount": 12000.5, "StageName": "Qualification", "IsClosed": False},
            {"Id": "o4", "Name": "Last year", "Amount": 9000.0, "StageName": "Closed Won", "IsClosed": True},
        ],
    },
    "acct-2": {  # small: the planted bug cannot change its numbers
        "tickets": _tickets(5),
        "opportunities": [{"Id": "o5", "Name": "Renewal", "Amount": 8000.0, "StageName": "Proposal", "IsClosed": False}],
    },
}


class FixtureSource:
    def __init__(self) -> None:
        self.accounts = FIXTURES

    def _account(self, account_id: str) -> dict[str, Any]:
        if account_id not in self.accounts:
            raise LookupError(f"unknown account {account_id!r}; try one of {', '.join(self.accounts)}")
        return self.accounts[account_id]

    async def tickets(self, account_id: str) -> list[dict[str, Any]]:
        return list(self._account(account_id)["tickets"])

    async def opportunities(self, account_id: str) -> list[dict[str, Any]]:
        return list(self._account(account_id)["opportunities"])
