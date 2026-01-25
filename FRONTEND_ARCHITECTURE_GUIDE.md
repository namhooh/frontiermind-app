# FrontierMind Frontend Architecture Guide

Comprehensive documentation for the Next.js frontend application structure, components, state management, API integration, and deployment.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Directory Structure](#2-directory-structure)
3. [Component Architecture](#3-component-architecture)
4. [State Management](#4-state-management)
5. [API Client Architecture](#5-api-client-architecture)
6. [Routing & Pages](#6-routing--pages)
7. [Styling System](#7-styling-system)
8. [Environment Variables](#8-environment-variables)
9. [Deployment (Vercel)](#9-deployment-vercel)
10. [Development Workflow](#10-development-workflow)
11. [Figma MCP Integration](#11-figma-mcp-integration)

---

## 1. Overview

### Tech Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| **Next.js** | 16 | React framework with App Router |
| **React** | 19 | UI library |
| **TypeScript** | Strict mode | Type safety |
| **Tailwind CSS** | v4 | Utility-first styling |
| **Radix UI** | Latest | Accessible component primitives |
| **Lucide React** | Latest | Icons |

### Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│                    FRONTEND (Vercel)                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Pages     │  │ Components  │  │   lib/ (shared)     │  │
│  │  (routes)   │──│  (UI/feat)  │──│  api/, workflow/    │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│         │                                    │               │
│         └───────────────┬────────────────────┘               │
│                         ▼                                    │
│              ┌─────────────────────┐                         │
│              │    API Clients      │                         │
│              │ (contracts, reports,│                         │
│              │  ingest)            │                         │
│              └──────────┬──────────┘                         │
└─────────────────────────│───────────────────────────────────┘
                          ▼
              ┌─────────────────────┐
              │  Python Backend     │
              │  (AWS ECS Fargate)  │
              └─────────────────────┘
```

---

## 2. Directory Structure

```
frontiermind-app/
├── app/                              # Next.js App Router
│   ├── page.tsx                      # Home → WorkflowDashboard
│   ├── layout.tsx                    # Root layout with providers
│   │
│   ├── reports/                      # /reports route
│   │   ├── page.tsx                  # Reports management page
│   │   └── components/
│   │       ├── ReportsList.tsx       # Filterable reports table
│   │       ├── ReportCard.tsx        # Individual report row
│   │       ├── GenerateReportDialog.tsx  # Modal for new reports
│   │       └── ReportStatusBadge.tsx # Status indicator
│   │
│   ├── workflow/                     # Workflow feature module
│   │   ├── components/
│   │   │   ├── index.ts              # Barrel exports
│   │   │   ├── WorkflowDashboard.tsx # Main 5-step orchestrator
│   │   │   ├── WorkflowStepper.tsx   # Visual progress indicator
│   │   │   ├── InvoicePreview.tsx    # Invoice display component
│   │   │   └── steps/
│   │   │       ├── ContractUploadStep.tsx    # Step 1: Upload PDF/DOCX
│   │   │       ├── ClauseReviewStep.tsx      # Step 2: Review clauses
│   │   │       ├── MeterDataStep.tsx         # Step 3: Meter data
│   │   │       ├── InvoiceGenerationStep.tsx # Step 4: Invoice preview
│   │   │       └── ReportGenerationStep.tsx  # Step 5: Generate reports
│   │
│   └── components/
│       └── ui/                       # Shared Radix UI components
│           ├── cn.ts                 # Class merge utility
│           ├── button.tsx            # Button with variants
│           ├── card.tsx              # Card compound component
│           ├── badge.tsx             # Status badges
│           ├── input.tsx             # Form input
│           ├── label.tsx             # Form label
│           ├── select.tsx            # Dropdown select
│           ├── tabs.tsx              # Tab navigation
│           ├── switch.tsx            # Toggle switch
│           └── progress.tsx          # Progress indicator
│
├── lib/                              # Shared utilities & state
│   ├── api/                          # API client layer
│   │   ├── index.ts                  # Barrel exports
│   │   ├── contractsClient.ts        # Contracts API (350+ lines)
│   │   ├── reportsClient.ts          # Reports API
│   │   └── ingestClient.ts           # Data ingestion API
│   │
│   ├── workflow/                     # Workflow state management
│   │   ├── index.ts                  # Barrel exports
│   │   ├── types.ts                  # WorkflowState, actions
│   │   ├── workflowContext.tsx       # React context + reducer
│   │   └── invoiceGenerator.ts       # Client-side invoice logic
│   │
│   └── supabase/                     # Supabase client setup
│       ├── client.ts                 # Browser client
│       ├── server.ts                 # Server client
│       └── middleware.ts             # Auth middleware
│
├── .claude/                          # Claude Code configuration
│   ├── settings.local.json           # Permissions & preferences
│   └── skills/
│       └── sync-figma.md             # Figma MCP workflow skill
│
├── figma_dashboard_design/           # Figma Make export reference
│
└── public/                           # Static assets
```

---

## 3. Component Architecture

### Component Layers

```
┌─────────────────────────────────────────────────────────────┐
│                      Page Components                         │
│         app/page.tsx, app/reports/page.tsx                  │
│         (Route entry points, minimal logic)                 │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                   Feature Components                         │
│         WorkflowDashboard, ReportsList, etc.                │
│         (Business logic, state orchestration)               │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                    UI Components                             │
│         app/components/ui/* (Button, Card, Badge...)        │
│         (Presentational, reusable, Radix-based)             │
└─────────────────────────────────────────────────────────────┘
```

### Component Patterns

**UI Component Pattern (Radix + Variants):**

```typescript
"use client"
import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "./cn"

const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-lg font-medium transition-all",
  {
    variants: {
      variant: {
        default: "bg-blue-600 text-white hover:bg-blue-700",
        outline: "border border-slate-300 hover:bg-slate-50",
        emerald: "bg-emerald-600 text-white hover:bg-emerald-700",
      },
      size: {
        default: "h-10 px-4",
        sm: "h-8 px-3 text-sm",
        lg: "h-12 px-6",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
)
Button.displayName = "Button"
```

**Feature Component Pattern:**

```typescript
'use client'

import { useState, useMemo } from 'react'
import { useWorkflow } from '@/lib/workflow'
import { ReportsClient } from '@/lib/api'
import { Button } from '@/app/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/app/components/ui/card'

export function FeatureComponent() {
  const { state, setStep } = useWorkflow()
  const [isLoading, setIsLoading] = useState(false)

  const apiClient = useMemo(
    () => new ReportsClient({ enableLogging: process.env.NODE_ENV === 'development' }),
    []
  )

  // Component logic...
}
```

---

## 4. State Management

### WorkflowContext

The application uses React Context + useReducer for the 5-step workflow state.

**State Structure (`lib/workflow/types.ts`):**

```typescript
export type WorkflowStep = 1 | 2 | 3 | 4 | 5

export interface WorkflowState {
  currentStep: WorkflowStep

  // Step 1: Contract Upload
  contractFile: File | null
  parseResult: ContractParseResult | null
  isUploading: boolean
  uploadError: string | null

  // Step 2: Clause Review
  clauseValidation: ClauseValidation

  // Step 3: Meter Data
  meterDataStatus: MeterDataStatus
  meterDataSummary: MeterDataSummary | null
  meterDataError: string | null
  useDummyData: boolean

  // Step 4: Invoice Generation
  invoicePreview: InvoicePreview | null
  ruleEvaluationResult: RuleEvaluationResult | null
  isGeneratingInvoice: boolean

  // Step 5: Report Generation
  reportData: GeneratedReport | null
  isGeneratingReport: boolean
  reportError: string | null
  selectedReportFormat: FileFormat
  selectedReportType: InvoiceReportType
}
```

**Context Usage:**

```typescript
// In a component
import { useWorkflow } from '@/lib/workflow'

function MyComponent() {
  const {
    state,                    // Current state
    setStep,                  // Navigate to step
    goToNextStep,             // Go to next step
    goToPreviousStep,         // Go to previous step
    canProceedToStep,         // Check if step is accessible
    setParseResult,           // Update parse result
    setReportData,            // Update report data
    resetWorkflow,            // Reset all state
  } = useWorkflow()

  // Access state
  const { currentStep, invoicePreview, isGeneratingReport } = state
}
```

**Provider Setup (`app/page.tsx`):**

```typescript
import { WorkflowProvider } from '@/lib/workflow'
import { WorkflowDashboard } from './workflow/components'

export default function Home() {
  return (
    <WorkflowProvider>
      <WorkflowDashboard />
    </WorkflowProvider>
  )
}
```

---

## 5. API Client Architecture

### Client Pattern

All API clients follow a consistent pattern with retry logic, logging, and typed errors.

**Base Pattern:**

```typescript
export class ReportsClient {
  private baseUrl: string
  private retryCount: number
  private retryDelayMs: number
  private enableLogging: boolean
  private getAuthToken?: () => Promise<string | null>

  constructor(config: ReportsClientConfig = {}) {
    this.baseUrl = config.baseUrl || process.env.NEXT_PUBLIC_PYTHON_BACKEND_URL
    this.retryCount = config.retryCount ?? 3
    this.retryDelayMs = config.retryDelayMs ?? 1000
    this.enableLogging = config.enableLogging ?? process.env.NODE_ENV === 'development'
    this.getAuthToken = config.getAuthToken
  }

  private async fetchWithRetry<T>(url: string, options: RequestInit): Promise<T> {
    // Retry logic with exponential backoff
  }

  // Public methods
  async generateReport(request: GenerateReportRequest): Promise<{ reportId: number; status: string }>
  async listReports(filters?: ReportFilters): Promise<GeneratedReport[]>
  async getDownloadUrl(reportId: number): Promise<{ url: string; expiresIn: number }>
}
```

### Available Clients

| Client | File | Purpose |
|--------|------|---------|
| `APIClient` | `contractsClient.ts` | Contract parsing, clause extraction, rules evaluation |
| `ReportsClient` | `reportsClient.ts` | Report templates, generation, downloads |
| `IngestClient` | `ingestClient.ts` | Data ingestion, presigned URLs |

### Error Handling

```typescript
import { ReportsClient, ReportsAPIError } from '@/lib/api'

try {
  const result = await reportsClient.generateReport(request)
} catch (err) {
  if (err instanceof ReportsAPIError) {
    console.error(`API Error: ${err.message} (${err.statusCode})`)
    // err.errorType, err.details available
  }
}
```

### Usage Example

```typescript
import { ReportsClient, type GenerateReportRequest } from '@/lib/api'

const client = new ReportsClient({
  enableLogging: true,
  getAuthToken: async () => session?.access_token,
})

// Generate a report
const { reportId } = await client.generateReport({
  billing_period_id: 12,
  report_type: 'invoice_to_client',
  file_format: 'pdf',
})

// Poll for completion
const report = await client.waitForCompletion(reportId)

// Download
const { url } = await client.getDownloadUrl(reportId)
window.open(url, '_blank')
```

---

## 6. Routing & Pages

### Current Routes

| Route | Page Component | Purpose |
|-------|----------------|---------|
| `/` | `app/page.tsx` → `WorkflowDashboard` | 5-step contract compliance workflow |
| `/reports` | `app/reports/page.tsx` | Report history and generation |

### Page Structure

Each page follows this pattern:

```typescript
// app/example/page.tsx
'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/app/components/ui/card'

export default function ExamplePage() {
  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-20">
        {/* Navigation, title */}
      </header>

      {/* Main Content */}
      <main className="max-w-6xl mx-auto px-6 py-8">
        <Card>
          <CardHeader>
            <CardTitle>Page Title</CardTitle>
          </CardHeader>
          <CardContent>
            {/* Page content */}
          </CardContent>
        </Card>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-200 bg-white">
        {/* Footer content */}
      </footer>
    </div>
  )
}
```

---

## 7. Styling System

### Tailwind CSS v4

Configuration in `tailwind.config.ts`:

```typescript
export default {
  content: ['./app/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        serif: ['Libre Baskerville', 'serif'],
      },
    },
  },
}
```

### Class Merge Utility

```typescript
// app/components/ui/cn.ts
import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Usage
<div className={cn("base-class", isActive && "active-class", className)} />
```

### Design Tokens

| Token | Value | Usage |
|-------|-------|-------|
| **Primary** | `blue-600`, `blue-700` | Actions, links |
| **Success** | `emerald-500`, `emerald-600` | Success states |
| **Warning** | `amber-500`, `amber-600` | Warnings |
| **Error** | `red-500`, `red-600` | Errors |
| **Grays** | `slate-50` to `slate-900` | Backgrounds, text |
| **Border radius** | `rounded-lg` (default) | Cards, buttons |
| **Spacing** | `p-6` (cards), `gap-4` (grids) | Consistent spacing |

---

## 8. Environment Variables

### Required Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `NEXT_PUBLIC_PYTHON_BACKEND_URL` | Backend API URL | `http://localhost:8000` or `https://api.frontiermind.com` |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL | `https://xxx.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anonymous key | `eyJhbGci...` |

### Local Development

Create `.env.local`:

```bash
NEXT_PUBLIC_PYTHON_BACKEND_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
```

### Production (Vercel)

Set in Vercel Dashboard → Project → Settings → Environment Variables.

---

## 9. Deployment (Vercel)

### Overview

The frontend is deployed to Vercel with automatic deployments from GitHub.

```
┌─────────────────────────────────────────────────────────────┐
│                    Deployment Flow                           │
│                                                              │
│   GitHub (main)  ──push──►  Vercel  ──build──►  Production  │
│                                                              │
│   GitHub (branch) ──push──► Vercel  ──build──► Preview URL  │
└─────────────────────────────────────────────────────────────┘
```

### Vercel Configuration

- **Framework Preset:** Next.js (auto-detected)
- **Build Command:** `npm run build`
- **Output Directory:** `.next`
- **Install Command:** `npm install`

### Environment Variables in Vercel

1. Go to Vercel Dashboard → Project → Settings → Environment Variables
2. Add all required variables (see Section 8)
3. Select environments (Production, Preview, Development)

### Deployment Commands

```bash
# Automatic: Just push to GitHub
git push origin main  # → Triggers production deploy

git push origin feature/my-branch  # → Triggers preview deploy
```

### Production URL

```
https://frontiermind-app.vercel.app
```

---

## 10. Development Workflow

### Setup

```bash
# Clone repository
git clone https://github.com/your-org/frontiermind-app.git
cd frontiermind-app

# Install dependencies
npm install

# Create environment file
cp .env.example .env.local
# Edit .env.local with your values

# Start development server
npm run dev
```

### Available Commands

| Command | Purpose |
|---------|---------|
| `npm run dev` | Start development server (localhost:3000) |
| `npm run build` | Production build |
| `npm run lint` | Run ESLint |
| `npx tsc --noEmit` | Type check without emitting |

### Code Conventions

1. **TypeScript strict mode** - All code must type-check
2. **Radix UI primitives** - Use for accessible components
3. **Tailwind CSS** - Utility-first styling (no CSS files)
4. **forwardRef** - For components that need DOM access
5. **Barrel exports** - Use index.ts for clean imports

### Git Workflow

```bash
# Create feature branch
git checkout -b feature/my-feature

# Make changes, commit
git add .
git commit -m "Add feature description"

# Push and create PR
git push -u origin feature/my-feature
```

---

## 11. Figma MCP Integration

### Overview

Figma MCP enables direct design-to-code workflow. Claude Code can read Figma designs and generate matching React/Tailwind components.

**Status:** ✓ Connected via `https://mcp.figma.com/mcp`

### Project Figma Files

| Asset | URL |
|-------|-----|
| **Figma Make Dashboard** | https://www.figma.com/make/P2qKkNQJoizkHQUE88QUw4/PPA-and-O-M-Assurance-AI-Dashboard |
| **Figma Design Dashboard** | https://www.figma.com/design/P2qKkNQJoizkHQUE88QUw4/PPA-and-O-M-Assurance-AI-Dashboard |
| **Reference Export** | `/figma_dashboard_design/` |

**File Key:** `P2qKkNQJoizkHQUE88QUw4`

### Available MCP Tools

| Tool | Purpose |
|------|---------|
| `mcp__figma__get_design_context` | Generate UI code for a Figma node |
| `mcp__figma__get_screenshot` | Capture visual reference of a frame |
| `mcp__figma__get_metadata` | Get node structure in XML format |
| `mcp__figma__get_variable_defs` | Get design tokens (colors, fonts, spacing) |
| `mcp__figma__generate_diagram` | Create diagrams in FigJam |

### Design-to-Code Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                 Figma → Code Workflow                        │
│                                                              │
│  1. Design in Figma Make                                     │
│         ▼                                                    │
│  2. Copy frame URL (with node-id)                            │
│         ▼                                                    │
│  3. Share URL with Claude                                    │
│         ▼                                                    │
│  4. Claude uses MCP to:                                      │
│     • get_design_context → Extract styles, layout            │
│     • get_screenshot → Visual reference                      │
│     • get_variable_defs → Design tokens                      │
│         ▼                                                    │
│  5. Claude generates/updates React component                 │
│         ▼                                                    │
│  6. Review, commit, and deploy                               │
└─────────────────────────────────────────────────────────────┘
```

### Usage Examples

**Inspect a specific component:**
```
Share this URL with Claude:
https://www.figma.com/design/P2qKkNQJoizkHQUE88QUw4/PPA-and-O-M-Assurance-AI-Dashboard?node-id=123-456

Claude will:
1. Extract design properties (colors, spacing, typography)
2. Identify component structure
3. Generate matching React/Tailwind code
```

**Browse file structure:**
```
If you only have the Make URL (no node-id):
1. Claude uses get_metadata to browse file structure
2. Identifies relevant frame/component node IDs
3. Then uses get_design_context on specific nodes
```

### Skill File

Detailed Figma workflow instructions are in:
```
.claude/skills/sync-figma.md
```

### Setup / Troubleshooting

```bash
# Check MCP status
claude mcp list

# Re-authenticate if needed
/mcp → figma → Authenticate

# Reset connection
claude mcp remove figma
claude mcp add --transport http figma https://mcp.figma.com/mcp
```

### Component Destination Guide

| Component Type | Location |
|----------------|----------|
| UI primitive (Button, Card) | `app/components/ui/` |
| Workflow step | `app/workflow/components/steps/` |
| Feature component | `app/workflow/components/` or `app/reports/components/` |

---

## Quick Reference

### Import Paths

```typescript
// API clients
import { ReportsClient, APIClient, IngestClient } from '@/lib/api'
import type { GeneratedReport, Contract, ReportFilters } from '@/lib/api'

// Workflow
import { useWorkflow, WorkflowProvider } from '@/lib/workflow'
import type { WorkflowState, WorkflowStep } from '@/lib/workflow'

// UI Components
import { Button } from '@/app/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/app/components/ui/card'
import { Badge } from '@/app/components/ui/badge'
import { cn } from '@/app/components/ui/cn'
```

### File Locations

| Need | Location |
|------|----------|
| Add new page | `app/[route]/page.tsx` |
| Add UI component | `app/components/ui/[name].tsx` |
| Add feature component | `app/[feature]/components/[name].tsx` |
| Add API client | `lib/api/[name]Client.ts` + export from `index.ts` |
| Add workflow action | `lib/workflow/types.ts` + `workflowContext.tsx` |

---

## Related Documentation

- **CLAUDE.md** - Project overview, backend deployment, database
- **DATABASE_GUIDE.md** - Schema and migrations
- **IMPLEMENTATION_GUIDE_REPORTS.md** - Report generation system
- **.claude/skills/sync-figma.md** - Detailed Figma MCP workflow
