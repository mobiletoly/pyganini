"""Small immutable data store for navigation label resolution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Office:
    identifier: str
    name: str


@dataclass(frozen=True, slots=True)
class Team:
    identifier: str
    name: str
    office_identifier: str | None = None


@dataclass(frozen=True, slots=True)
class Customer:
    identifier: str
    name: str
    team_identifier: str
    risk: str


@dataclass(frozen=True, slots=True)
class Store:
    offices: tuple[Office, ...]
    teams: tuple[Team, ...]
    customers: tuple[Customer, ...]

    def office(self, identifier: str) -> Office | None:
        return next(
            (office for office in self.offices if office.identifier == identifier),
            None,
        )

    def team(self, identifier: str) -> Team | None:
        return next(
            (team for team in self.teams if team.identifier == identifier),
            None,
        )

    def customer(self, identifier: str) -> Customer | None:
        return next(
            (
                customer
                for customer in self.customers
                if customer.identifier == identifier
            ),
            None,
        )

    def team_customers(self, team_identifier: str) -> tuple[Customer, ...]:
        return tuple(
            customer
            for customer in self.customers
            if customer.team_identifier == team_identifier
        )


STORE = Store(
    offices=(Office("sea", "Seattle"),),
    teams=(
        Team("hq-team", "HQ Team"),
        Team("regional-team", "Regional Team", office_identifier="sea"),
    ),
    customers=(
        Customer("contoso", "Contoso Retail", "hq-team", "high"),
        Customer("northwind", "Northwind Supply", "regional-team", "medium"),
    ),
)
