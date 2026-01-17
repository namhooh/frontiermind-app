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

When updating designs:

1. Make changes in Figma
2. Share the specific frame/node URL with Claude
3. Claude will use Figma MCP to inspect changes and update components

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
