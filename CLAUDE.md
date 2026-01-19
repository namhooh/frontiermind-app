# FrontierMind App

Contract Compliance & Invoicing Verification Engine for renewable energy projects.

## Tech Stack

- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind CSS v4
- **UI Components:** Radix UI, Lucide React icons, Recharts
- **Backend:** Python (FastAPI) in `/python-backend`
- **Database:** Supabase (PostgreSQL)
- **Deployment:** Docker, Google Cloud Run

## Commands

```bash
npm run dev      # Start Next.js dev server
npm run build    # Production build
npm run lint     # ESLint
```

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

## Implementation Plan

- See `IMPLEMENTATION_GUIDE.md` for the overall system design, workflow and implementation

## Contract Digitization

- See `contract-digitization/` for contract parsing documentation and examples
- Implementation code lives in `python-backend/` (services, API, models)

## Data Ingestion

- See `data-ingestion/` for data ingestion components and documentation
- Architecture guide: `data-ingestion/docs/IMPLEMENTATION_GUIDE_ARCHITECTURE.md`

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
