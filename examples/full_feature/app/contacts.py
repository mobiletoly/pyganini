"""In-memory contacts owned by the example application."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Contact:
    """One contact-directory entry."""

    identifier: str
    name: str
    status: str
    avatar_filename: str = ""


_SEED_CONTACTS: tuple[Contact, ...] = (
    Contact("42", "Ada Lovelace", "Active"),
    Contact("7", "Grace Hopper", "Active"),
    Contact("11", "Katherine Johnson", "Inactive"),
)


class ContactRepository:
    """A deterministic, application-local contact repository."""

    def __init__(self, seed: Iterable[Contact] | None = None) -> None:
        self._contacts = list(_SEED_CONTACTS if seed is None else seed)

    def list_contacts(self, status: str | None = None) -> tuple[Contact, ...]:
        """Return contacts in their stable insertion order."""
        if status is None:
            return tuple(self._contacts)
        return tuple(contact for contact in self._contacts if contact.status == status)

    def contact_by_id(self, identifier: str) -> Contact | None:
        """Return one contact by its stable string identifier."""
        return next(
            (contact for contact in self._contacts if contact.identifier == identifier),
            None,
        )

    def add_contact(self, name: str, status: str, avatar_filename: str) -> Contact:
        """Append and return a contact after application validation."""
        numeric_ids = [
            int(contact.identifier)
            for contact in self._contacts
            if contact.identifier.isdecimal()
        ]
        next_identifier = str(max(numeric_ids, default=0) + 1)
        contact = Contact(next_identifier, name, status, avatar_filename)
        self._contacts.append(contact)
        return contact
