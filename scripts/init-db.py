#!/usr/bin/env python3
"""GraphMentor — Database Initialization Script.

Run: uv run scripts/init-db.py

Calls sudo internally only for commands that need it (service start,
postgres user operations). Idempotent — safe to re-run.
"""

import shutil
import subprocess
import sys
import time


def run(
    cmd: str, *, check: bool = True, timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            check=check, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"  Command timed out: {cmd}")
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="timeout")


def sudo(cmd: str, *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run a command with sudo, inheriting stdin for password prompt."""
    try:
        return subprocess.run(
            f"sudo {cmd}", shell=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"  Command timed out: sudo {cmd}")
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="timeout")


def psql_admin(sql: str) -> subprocess.CompletedProcess[str]:
    """Execute SQL as the postgres superuser via sudo."""
    escaped = sql.replace('"', '\\"')
    return sudo(f'-u postgres psql -tc "{escaped}"')


def main() -> None:
    print("=== GraphMentor DB Init ===\n")

    # 1. Install PostgreSQL if not present
    if not shutil.which("psql"):
        print("Installing PostgreSQL...")
        result = sudo("apt-get update -qq")
        if result.returncode != 0:
            sys.exit(f"apt-get update failed: {result.stderr.strip()}")
        result = sudo("apt-get install -y -qq postgresql postgresql-contrib")
        if result.returncode != 0:
            sys.exit(f"apt-get install failed: {result.stderr.strip()}")
    else:
        print("PostgreSQL already installed.")

    # 2. Start PostgreSQL if not running
    ready = run("pg_isready", check=False, timeout=5)
    if ready.returncode == 0:
        print("PostgreSQL already running.")
    else:
        # Find cluster info
        result = run("pg_lsclusters --no-header", check=False)
        if result.returncode != 0 or not result.stdout.strip():
            sys.exit("No PostgreSQL cluster found. Try: sudo pg_createcluster <ver> main --start")

        parts = result.stdout.strip().split()
        version, cluster = parts[0], parts[1]
        print(f"Starting PostgreSQL {version}/{cluster}...")
        result = sudo(f"pg_ctlcluster {version} {cluster} start")
        if result.returncode != 0:
            print(f"  pg_ctlcluster failed: {result.stderr.strip()}")
            print("  Trying 'service postgresql start'...")
            result = sudo("service postgresql start", timeout=10)
            if result.returncode != 0:
                sys.exit(f"Failed to start PostgreSQL: {result.stderr.strip()}")

    # 3. Wait for readiness
    for i in range(1, 11):
        result = run("pg_isready", check=False, timeout=5)
        if result.returncode == 0:
            print("PostgreSQL is ready.")
            break
        print(f"  Waiting for PostgreSQL... ({i}/10)")
        time.sleep(1)
    else:
        sys.exit("PostgreSQL failed to become ready after 10 attempts.")

    # 4. Create user (idempotent)
    exists = psql_admin("SELECT 1 FROM pg_roles WHERE rolname='graphmentor'")
    if "1" not in exists.stdout:
        print("Creating user 'graphmentor'...")
        psql_admin("CREATE USER graphmentor WITH PASSWORD 'graphmentor' CREATEDB")
    else:
        print("User 'graphmentor' already exists.")

    # 5. Create databases (idempotent)
    for db in ("graphmentor", "graphmentor_test"):
        exists = psql_admin(
            f"SELECT 1 FROM pg_catalog.pg_database WHERE datname='{db}'"
        )
        if "1" not in exists.stdout:
            print(f"Creating database '{db}'...")
            psql_admin(f"CREATE DATABASE {db} OWNER graphmentor")
        else:
            print(f"Database '{db}' already exists.")

    # 6. Verify connectivity
    print("\nVerifying connectivity...")
    all_ok = True
    for db in ("graphmentor", "graphmentor_test"):
        result = run(
            f"PGPASSWORD=graphmentor psql -U graphmentor -h localhost -d {db} -c 'SELECT 1'",
            check=False,
        )
        if result.returncode == 0:
            print(f"  {db}: ready")
        else:
            print(f"  {db}: FAILED — {result.stderr.strip()}")
            all_ok = False

    print(f"\n=== {'Done' if all_ok else 'Completed with errors'} ===")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
