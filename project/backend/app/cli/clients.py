"""Local business administration: python -m app.cli.clients add --company-name ..."""

import argparse
import os

from app.clients.repository import ClientRepository
from app.core.config import load_environment, project_path


def main():
    parser = argparse.ArgumentParser(
        description="Pre-registrar empresas; no se expone al agente."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    add = subcommands.add_parser(
        "add", help="Crear una empresa con ID y código automáticos"
    )
    add.add_argument("--company-name", required=True)
    add.add_argument("--company-email", required=True)
    args = parser.parse_args()
    load_environment()
    repository = ClientRepository(
        project_path(os.getenv("CALENDAR_ACCESS_DB", "data/calendar-access.sqlite3"))
    )
    try:
        client = repository.create(args.company_name, args.company_email)
    except ValueError as error:
        parser.error(str(error))
    print(f"client_id={client.client_id} client_code={client.client_code}")


if __name__ == "__main__":
    main()
