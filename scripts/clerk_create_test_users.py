"""Create one Clerk test user per role (dev instance) with the role stored in publicMetadata.

Run yourself (needs `npx clerk@latest auth login` done once):
    python scripts/clerk_create_test_users.py            # prints a dry-run plan
    python scripts/clerk_create_test_users.py --create   # creates users, writes passwords to test-users.local.txt (gitignored)

To change the role of an EXISTING user instead, use the Clerk Dashboard -> Users -> Metadata -> Public.
"""
import json
import os
import secrets
import string
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = os.getenv("CLERK_APP_ID", "app_3MBurWgzOJJfFbfOCYPVtdlm68n")
USERS = [
    ("employee", "Eva", "Employee", {"role": "employee", "employee_id": "EMP-1010"}),
    ("pm", "Paul", "Manager", {"role": "pm", "employee_id": "EMP-1001"}),
    ("hr.staff", "Hana", "Staff", {"role": "hr"}),
    ("hr.manager", "Hugo", "Manager", {"role": "hr", "hr_level": "manager"}),
    ("hr.admin", "Hazel", "Admin", {"role": "hr", "hr_level": "admin"}),
]


def main() -> None:
    create = "--create" in sys.argv
    lines = []
    for slug, first, last, md in USERS:
        email = f"hr360.{slug}+clerk_test@example.com"  # +clerk_test: Clerk dev accepts verification code 424242
        print(f"{'create' if create else 'plan  '}: {email:45} {md}")
        if not create:
            continue
        pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(18)) + "!9x"
        body = {"email_address": [email], "first_name": first, "last_name": last, "password": pw, "public_metadata": md}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(body, f)
        r = subprocess.run(f'npx -y clerk@latest users create --app {APP} --file "{f.name}" --yes --json',
                           shell=True, capture_output=True, text=True, cwd=ROOT)
        os.unlink(f.name)
        if r.returncode:
            print("   FAILED:", (r.stdout + r.stderr)[-300:])
        else:
            lines.append(f"{md['role']}{'/' + md['hr_level'] if 'hr_level' in md else ''}\t{email}\t{pw}")
    if lines:
        (ROOT / "test-users.local.txt").write_text("role\temail\tpassword\n" + "\n".join(lines) +
                                                    "\nVerification code (dev): 424242\n")
        print("Credentials written to test-users.local.txt (gitignored)")


if __name__ == "__main__":
    main()
