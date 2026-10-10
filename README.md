# LabStock

Inventory for small diagnostic laboratories — know what you have, what expires soon, and what to reorder.

This repository is a **working first-slice demo**: multi-tenant stock ledger, lots and opened containers, receive/issue/adjust/count workflows, expiry and reorder alerts, basic roles, and seeded dummy data for a small lab.

## Stack

- Django 5 + responsive server-rendered UI
- **PostgreSQL** when configured; **SQLite** by default for local demo

## Quick start (SQLite)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver 0.0.0.0:8731
```

Open [http://127.0.0.1:8731](http://127.0.0.1:8731).

### Demo logins

Password for all: `labstockdemo`

| Username | Role |
| --- | --- |
| `storekeeper` | Storekeeper (daily receive / issue / counts) |
| `tech` | Technician |
| `admin` | Admin (also member of a second tenant) |
| `viewer` | Read-only |

## PostgreSQL

Copy `.env.example` to `.env` and set either:

```bash
DATABASE_URL=postgres://labstock:labstock@localhost:5432/labstock
```

or:

```bash
POSTGRES_DB=labstock
POSTGRES_USER=labstock
POSTGRES_PASSWORD=labstock
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

Then migrate and seed as above. If those variables are unset, LabStock uses `db.sqlite3`.

## What’s in this slice

- **Stock movement ledger** — every balance change has quantity, reason, user, timestamp; corrections via recorded adjustments
- **Opened containers** — tracked individually with expiry rule days + source
- **Multi-tenant** — organizations isolated; admin can switch between demo labs
- **Screens** — Dashboard, Items/locations, Lots/opened, Receive/issue/open, Counts/adjustments, Reports/settings
- **Seed data** — Ridgeway Diagnostics (chemistry + serology consumables)

## Out of scope (for now)

Patient/clinical workflows, barcode scanning, supplier integrations, forecasting, spreadsheet import, messaging.

## Project layout

```
config/          Django project settings & URLs
inventory/       Domain models, ledger services, views, seed command
templates/       Responsive HTML
static/css/      App styles
```
