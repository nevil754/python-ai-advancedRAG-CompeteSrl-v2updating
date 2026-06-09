#!/usr/bin/env python
# =============================================================
# scripts/create_tenant.py
# CLI per creare un nuovo tenant da terminale.
#
# Uso:
#   python scripts/create_tenant.py \
#     --slug acme-corp \
#     --name "Acme Corporation" \
#     --plan pro \
#     --admin-email admin@acme.com \
#     --admin-password SecurePass123!
# =============================================================

import argparse
import asyncio
import sys
from pathlib import Path

# Aggiungi root al PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))


async def main():
    parser = argparse.ArgumentParser(description="Crea un nuovo tenant RAG")
    parser.add_argument("--slug", required=True, help="Slug univoco (es. acme-corp)")
    parser.add_argument("--name", required=True, help="Nome visualizzato")
    parser.add_argument("--plan", default="starter", choices=["starter", "pro", "enterprise"])
    parser.add_argument("--admin-email", help="Email admin (opzionale)")
    parser.add_argument("--admin-password", help="Password admin (opzionale)")
    args = parser.parse_args()

    from app.services.tenant_service import provision_tenant

    print(f"Provisioning tenant: {args.slug}...")
    result = await provision_tenant(
        slug=args.slug,
        display_name=args.name,
        plan=args.plan,
        admin_email=args.admin_email,
        admin_password=args.admin_password,
    )

    print(f"✓ Tenant creato: {result}")


if __name__ == "__main__":
    asyncio.run(main())
