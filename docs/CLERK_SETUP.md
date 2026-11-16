# Clerk setup (3 login types: Employee · HR · Project Manager)

One Clerk application serves all three portals. A user's **role is stored in Clerk `publicMetadata`**, which only
admins (dashboard/Backend API) can edit — users cannot change it. The landing page offers three login buttons; after
sign-in the app compares the chosen portal with the account's real role and blocks mismatches. The FastAPI backend
enforces the role on every request regardless of what the UI shows.

## 1. Create the application
1. <https://dashboard.clerk.com> → **Create application** → enable *Email* (and/or Google).
2. **Configure → Restrictions → Sign-up mode: Restricted** (invitation only) so only people you invite can join.

## 2. Put the role into the session token
**Configure → Sessions → Customize session token**, set:

```json
{
  "metadata": "{{user.public_metadata}}"
}
```

## 3. Assign roles (Users → pick user → *Metadata → Public → Edit*)

| Login type | publicMetadata |
|---|---|
| Employee | `{"role": "employee", "employee_id": "EMP-1010"}` |
| Project Manager | `{"role": "pm", "employee_id": "EMP-1002"}` — sees leave requests of employees whose `manager_id` is this ID |
| HR (staff) | `{"role": "hr"}` — audits, workflows, drafts; cannot approve |
| HR (manager) | `{"role": "hr", "hr_level": "manager"}` — can approve/reject email drafts, sees unmasked employee data |
| HR (admin) | `{"role": "hr", "hr_level": "admin"}` — plus the audit log |

`employee_id` must match an ID in the HR database (synthetic IDs are `EMP-1001`…`EMP-1036`; `EMP-1001` manages most
employees). Users with no `role` get a "No access assigned" screen.

## 4. Keys & environment
Dashboard → **API Keys**. Your *Frontend API URL* (issuer) looks like `https://<name>.clerk.accounts.dev`.

`web/.env.local`
```
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...
```
Backend (shell or `.env`)
```
CLERK_ISSUER=https://<name>.clerk.accounts.dev
CLERK_AUTHORIZED_PARTIES=http://localhost:5173        # comma-separated allowed origins (azp check)
HR360_CORS_ORIGINS=http://localhost:5173
```
The backend verifies the RS256 signature against `<issuer>/.well-known/jwks.json`, plus `exp`, `iss` and `azp`.

## 5. Run
```powershell
# terminal 1 - API
.\.venv\Scripts\uvicorn hr360.api.main:app --port 8000
# terminal 2 - web
cd web; npm install; npm run dev        # http://localhost:5173
```

## Local development without Clerk (API only)
`HR360_AUTH_MODE=dev` makes the API accept `X-Dev-User`, `X-Dev-Role` (`employee|pm|hr`), `X-Dev-Employee`, `X-Dev-Level`
headers instead of a JWT. **Never enable in production.**
```powershell
$env:HR360_AUTH_MODE="dev"; .\.venv\Scripts\uvicorn hr360.api.main:app --port 8000
curl -H "X-Dev-User: me" -H "X-Dev-Role: hr" http://localhost:8000/api/me
```

## Permission matrix

| | Employee | PM | HR staff | HR manager | HR admin |
|---|:-:|:-:|:-:|:-:|:-:|
| Ask policy questions | ✅ | ✅ | ✅ | ✅ | ✅ |
| Leave summary | – | own team | all | all | all |
| Upload docs / audits / onboarding | – | – | ✅ | ✅ | ✅ |
| Employee directory | – | – | masked | full | full |
| Approve email drafts | – | – | – | ✅ | ✅ |
| Audit log | – | – | – | – | ✅ |
