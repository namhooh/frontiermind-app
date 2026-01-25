# FrontierMind App

Contract Compliance & Invoicing Verification Engine for renewable energy projects.

## Tech Stack

- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind CSS v4
- **UI Components:** Radix UI, Lucide React icons, Recharts
- **Backend:** Python (FastAPI) in `/python-backend`
- **Database:** Supabase (PostgreSQL)
- **Deployment:** Docker, AWS ECS Fargate

## Documentation

| Guide | Description |
|-------|-------------|
| **FRONTEND_ARCHITECTURE_GUIDE.md** | Frontend structure, components, state, API clients, Vercel deployment, Figma MCP |
| **DATABASE_GUIDE.md** | Database schema and migrations |
| **IMPLEMENTATION_GUIDE_REPORTS.md** | Report generation system |
| **.claude/skills/sync-figma.md** | Detailed Figma-to-code workflow |

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

## Backend Deployment

The Python backend is deployed to AWS ECS Fargate.

### Live Endpoints

| Endpoint | URL |
|----------|-----|
| **Backend API** | `http://frontiermind-alb-210161978.us-east-1.elb.amazonaws.com` |
| **Health Check** | `http://frontiermind-alb-210161978.us-east-1.elb.amazonaws.com/health` |
| **API Docs** | `http://frontiermind-alb-210161978.us-east-1.elb.amazonaws.com/docs` |

### AWS Infrastructure

| Resource | Value |
|----------|-------|
| **Region** | us-east-1 |
| **ECS Cluster** | frontiermind-cluster |
| **ECS Service** | frontiermind-backend |
| **Load Balancer** | frontiermind-alb |
| **ECR Repository** | frontiermind-backend |
| **Log Group** | /ecs/frontiermind-backend |

### AWS ECS Fargate

**Why ECS Fargate:**
- No request timeout limit (Cloud Run limited to 300s)
- True scale-to-zero capability
- Better networking control (VPC, security groups)
- Consolidates infrastructure on AWS (S3 is already AWS)

**Prerequisites:**
- AWS CLI v2: `brew install awscli`
- Docker installed and running
- AWS credentials configured: `aws configure`

**One-time Infrastructure Setup:**
```bash
cd python-backend
./aws/infrastructure-setup.sh
```

This creates:
- ECR repository
- VPC with public subnets
- Application Load Balancer
- ECS cluster
- IAM roles for task execution and S3 access
- CloudWatch log group

**Create Secrets in AWS Secrets Manager:**
```bash
aws secretsmanager create-secret --region us-east-1 --name frontiermind/backend/anthropic-api-key --secret-string "YOUR_KEY"
aws secretsmanager create-secret --region us-east-1 --name frontiermind/backend/llama-api-key --secret-string "YOUR_KEY"
aws secretsmanager create-secret --region us-east-1 --name frontiermind/backend/database-url --secret-string "YOUR_URL"
aws secretsmanager create-secret --region us-east-1 --name frontiermind/backend/encryption-key --secret-string "YOUR_KEY"
aws secretsmanager create-secret --region us-east-1 --name frontiermind/supabase-url --secret-string "YOUR_URL"
```

**IAM Policy for Secrets Manager Access:**

The ECS task execution role needs permission to read secrets. Add this policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": [
        "arn:aws:secretsmanager:us-east-1:*:secret:frontiermind/*"
      ]
    }
  ]
}
```

**Database Connection (Supabase):**

Use the **Transaction Pooler** connection (port 6543), NOT the Direct Connection (port 5432):

```
postgresql://postgres.[project-ref]:[password]@aws-0-us-east-1.pooler.supabase.com:6543/postgres
```

- Transaction Pooler handles connection pooling automatically
- Direct Connection can exhaust connection limits under load
- Store the Transaction Pooler URL in `frontiermind/backend/database-url` secret

**Deploy:**
```bash
cd python-backend
source aws/infrastructure-config.env  # Load infrastructure variables
./deploy-aws.sh
```

**Cost Management:**
```bash
# Scale down to save costs (~$18/month idle)
aws ecs update-service --cluster frontiermind-cluster --service frontiermind-backend --desired-count 0

# Scale up (30-60 second cold start)
aws ecs update-service --cluster frontiermind-cluster --service frontiermind-backend --desired-count 1
```

**View Logs:**
```bash
aws logs tail /ecs/frontiermind-backend --follow
```

### Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Task fails to start | Missing secrets or IAM permissions | Check `aws logs tail /ecs/frontiermind-backend` for errors; verify secrets exist and IAM policy is attached |
| Database connection refused | Wrong connection string or port | Use Transaction Pooler (port 6543), not Direct Connection (port 5432) |
| 503 Service Unavailable | Task not running or unhealthy | Check `aws ecs describe-services --cluster frontiermind-cluster --services frontiermind-backend` |
| Secrets not found | Wrong region or name | Ensure secrets are in us-east-1 and use exact names (e.g., `frontiermind/backend/database-url`) |
| Image pull fails | ECR authentication expired | Run `aws ecr get-login-password --region us-east-1 \| docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com` |

**Debug Commands:**
```bash
# Check service status
aws ecs describe-services --cluster frontiermind-cluster --services frontiermind-backend

# Check task status
aws ecs list-tasks --cluster frontiermind-cluster --service-name frontiermind-backend
aws ecs describe-tasks --cluster frontiermind-cluster --tasks <task-arn>

# View recent logs
aws logs tail /ecs/frontiermind-backend --since 1h

# Check secrets exist
aws secretsmanager list-secrets --region us-east-1 --filter Key=name,Values=frontiermind
```

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
