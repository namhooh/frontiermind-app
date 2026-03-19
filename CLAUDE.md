# FrontierMind App

Contract Compliance & Invoicing Verification Engine for renewable energy projects.

## Tech Stack

- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind CSS v4
- **UI Components:** Radix UI, Lucide React icons, Recharts
- **Backend:** Python (FastAPI) in `/python-backend`
- **Database:** Supabase (PostgreSQL)
- **Deployment:** Railway (compute), AWS (S3, SES, SNS)

## Documentation

| Guide | Description |
|-------|-------------|
| **FRONTEND_ARCHITECTURE_GUIDE.md** | Frontend structure, components, state, API clients, Vercel deployment, Figma MCP |
| **DATABASE_GUIDE.md** | Database schema and migrations |
| **IMPLEMENTATION_GUIDE_REPORT_GENERATION.md** | Report generation system |
| **IMPLEMENTATION_GUIDE_EMAIL_NOTIFICATIONS.md** | Email & notification engine, inbound ingestion, dev auth bypass |
| **.claude/skills/sync-figma.md** | Detailed Figma-to-code workflow |

## Commands

```bash
npm run dev      # Start Next.js dev server
npm run build    # Production build
npm run lint     # ESLint
```

### Dev Auth Bypass

Backend endpoints behind `require_supabase_auth` need a valid JWT. For local dev, set `DEV_AUTH_BYPASS=true` in `python-backend/.env` to skip JWT validation (blocked in production by `ENVIRONMENT != production` guard). The frontend auto-falls back to `organizationId=1` when `NODE_ENV=development`. See **IMPLEMENTATION_GUIDE_EMAIL_NOTIFICATIONS.md § Local Development** for details.

## Project Structure

```
app/
├── dashboard/           # Main dashboard UI
│   ├── components/      # Shell, Sidebar, MainContent
│   └── sections/        # Feature sections (Overview, Contracts, etc.)
├── components/ui/       # Shared UI components
lib/                     # Utilities and Supabase client
python-backend/          # FastAPI backend services
database/                # Migrations and schema
```

## Design Assets

- **Figma Dashboard Design:** [https://www.figma.com/make/P2qKkNQJoizkHQUE88QUw4/PPA-and-O-M-Assurance-AI-Dashboard?t=Jha05l0aRfdUPlhd-1]
- **Reference Export:** `/figma_dashboard_design` (Figma Make snapshot)

### Figma MCP Workflow

Figma MCP is configured for direct design-to-code integration using Figma's official OAuth authentication.

#### Setup Options

**Option A: Remote Server (Recommended)**

No API token needed - uses Figma's OAuth authentication.

1. Add the remote MCP server:
   ```bash
   claude mcp add --transport http figma https://mcp.figma.com/mcp
   ```
2. Authenticate:
   - In Claude Code, type `/mcp`
   - Select `figma` from the list
   - Click **Authenticate**
   - Click **Allow Access** in the browser popup
3. Verify:
   ```bash
   claude mcp list
   ```

**Option B: Desktop Server (Alternative)**

Uses the Figma desktop app's local MCP server.

1. Open Figma desktop app → Inspect panel → **Enable desktop MCP server**
2. Add to Claude Code:
   ```bash
   claude mcp add --transport http figma-desktop http://127.0.0.1:3845/mcp
   ```

#### Using Figma MCP

**To update components from Figma:**

1. Make changes in Figma
2. Share the frame/component URL with Claude (e.g., `https://www.figma.com/design/...?node-id=123-456`)
3. Claude will use Figma MCP to:
   - Read design properties (colors, spacing, typography)
   - Inspect component structure and layout
   - Implement or update code to match the design

#### Workflow for GitHub Integration

1. **Make design changes** in Figma
2. **Share frame URL** with Claude in a new branch:
   ```bash
   git checkout -b design/update-component-name
   ```
3. **Claude inspects & implements** using Figma MCP
4. **Review changes** and commit:
   ```bash
   git add .
   git commit -m "Update component based on Figma design"
   ```
5. **Create PR** for review

#### Troubleshooting

- Run `claude mcp list` to verify connection status
- Re-authenticate via `/mcp` → `figma` → **Authenticate** if needed
- Verify token has read access to the file
- Check token hasn't expired
- Ensure the Figma file is accessible (not restricted)
- Try `claude mcp remove figma` and re-add if connection fails

## Key Files

- `app/dashboard/page.tsx` - Dashboard entry point
- `app/dashboard/components/Sidebar.tsx` - Navigation sidebar
- `app/dashboard/components/MainContent.tsx` - Content container
- `lib/supabase/` - Database client configuration
- `.env.local` - Environment variables (Supabase keys)

## Database

- See `DATABASE_GUIDE.md` for schema documentation
- Migrations in `database/migrations/`

## Backend Deployment

The Python backend is deployed to **Railway** (compute). AWS is used for S3, SES, and SNS only.

### Live Endpoints

| Endpoint | URL |
|----------|-----|
| **Backend API** | `https://api.frontiermind.co` |
| **Health Check** | `https://api.frontiermind.co/health` |
| **API Docs** | `https://api.frontiermind.co/docs` |

### Architecture

| Layer | Service |
|-------|---------|
| **Compute** | Railway (auto-builds from `railway.toml`) |
| **File storage** | AWS S3 (us-east-1) |
| **Email sending** | AWS SES |
| **Email ingest** | AWS SNS → webhook |
| **Database** | Supabase (PostgreSQL) |
| **Frontend** | Vercel |

### Railway

Railway auto-detects `railway.toml` at the repo root, which points to `python-backend/Dockerfile`.

**Deploy:** Push to `main` — Railway builds and deploys automatically.

**Custom domain:** `api.frontiermind.co` is configured as a custom domain in Railway with auto-HTTPS.

**Config:** `railway.toml`
```toml
[build]
dockerfilePath = "python-backend/Dockerfile"

[deploy]
healthcheckPath = "/health"
healthcheckTimeout = 30
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 3
```

**Environment variables** are set in the Railway dashboard (not in code). All secrets (API keys, DB URL, AWS credentials) are Railway env vars.

**View logs:** Railway dashboard → Deployments → select deployment → Logs

### AWS Resources (S3 / SES / SNS)

| Resource | Value |
|----------|-------|
| **Region** | us-east-1 |
| **S3 Buckets** | `frontiermind-meter`, `frontiermind-report`, `frontiermind-email`, `frontiermind-mrp` |
| **SES Domain** | `mail.frontiermind.co` |
| **SNS Topic** | `frontiermind-email-ingest` |
| **IAM User** | `railway-backend` (programmatic access for S3 + SES) |

**Database Connection (Supabase):**

Use the **Transaction Pooler** connection (port 6543), NOT the Direct Connection (port 5432):

```
postgresql://postgres.[project-ref]:[password]@aws-0-us-east-1.pooler.supabase.com:6543/postgres
```

- Transaction Pooler handles connection pooling automatically
- Direct Connection can exhaust connection limits under load

### Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Deploy fails | Dockerfile build error | Check Railway build logs |
| Database connection refused | Wrong connection string or port | Use Transaction Pooler (port 6543), not Direct Connection (port 5432) |
| S3 access denied | IAM credentials wrong | Verify `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` in Railway env vars |
| Email not sending | SES still in sandbox | Request production access or verify recipient addresses |
| Health check fails | App crash on startup | Check Railway deployment logs for Python errors |

## Implementation Plan

- See `IMPLEMENTATION_GUIDE.md` for the overall system design, workflow and implementation

## Contract Digitization

- See `contract-digitization/` for contract parsing documentation and examples
- Implementation code lives in `python-backend/` (services, API, models)

## Data Ingestion

- See `data-ingestion/` for data ingestion components and documentation
- Architecture guide: `data-ingestion/docs/IMPLEMENTATION_GUIDE_ARCHITECTURE.md`

## OAuth Integration Security

When implementing OAuth flows for inverter integrations (Enphase, SMA):

### Required Pattern

**ALWAYS** use the backend OAuth state endpoint before redirecting users:

```typescript
import { generateOAuthState, buildOAuthUrl } from '@/lib/api/oauthClient';

// Option 1: Generate state manually
const { state } = await generateOAuthState(organizationId);
const authUrl = `https://api.enphase.com/oauth/authorize?state=${state}&...`;

// Option 2: Use helper to build full URL
const authUrl = await buildOAuthUrl('enphase', organizationId, callbackUrl);
window.location.href = authUrl;
```

### Why This Matters

1. **CSRF Protection**: The state parameter is HMAC-signed and prevents cross-site request forgery
2. **Server-Side Secret**: The HMAC secret never leaves the backend
3. **Time-Limited**: States expire after 10 minutes
4. **Strict Validation**: The OAuth callback rejects unsigned or expired states

### DO NOT

- Generate state client-side (exposes HMAC secret)
- Use simple random strings as state
- Skip state parameter validation
- Store OAuth secrets in frontend environment variables

### Environment Variables

| Variable | Location | Purpose |
|----------|----------|---------|
| `OAUTH_STATE_SECRET` | Backend only | HMAC signing key |
| `ENCRYPTION_KEY` | Backend + Edge Function | Credential encryption (AES-256-GCM) |
| `NEXT_PUBLIC_ENPHASE_CLIENT_ID` | Frontend | OAuth client ID (public) |
| `NEXT_PUBLIC_SMA_CLIENT_ID` | Frontend | OAuth client ID (public) |

## Conventions

- Use Radix UI primitives for accessible components
- Follow existing component patterns in `app/components/ui/`
- Tailwind CSS for styling (v4 syntax)
- TypeScript strict mode enabled

## Documentation Maintenance Rules

When making changes to the codebase, ensure the following documentation stays in sync:

### Database Schema Changes

When creating or modifying database migrations in `database/migrations/`:
1. **Update `database/SCHEMA_CHANGES.md`** - Add a new version entry documenting:
   - Version number and date
   - Migration file names
   - New tables, columns, or enums created
   - Modified tables and what changed
   - Helper functions added
   - Any breaking changes

2. **Update `database/DATABASE_GUIDE.md`** - Update the following sections:
   - Directory structure (add new migration files)
   - Version history summary
   - Any new scripts or workflows

### Contract Digitization Workflow Changes

When modifying the contract parsing pipeline or rules engine in `python-backend/services/`:
- **Update `contract-digitization/docs/IMPLEMENTATION_GUIDE.md`** with:
  - New pipeline steps or modifications
  - New API endpoints
  - New Python files created/modified
  - Updated architecture diagrams if needed

### Data Ingestion Workflow Changes

When modifying data ingestion components in `data-ingestion/`:
- **Update `data-ingestion/docs/IMPLEMENTATION_GUIDE_ARCHITECTURE.md`** with:
  - New data sources or fetchers
  - Infrastructure changes
  - Schema changes related to ingestion
  - Updated architecture diagrams if needed
