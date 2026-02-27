# FrontierMind Marketing Website

## Overview

Static marketing/landing page for [frontiermind.co](https://frontiermind.co). This is a separate Next.js project deployed as its own Vercel project, independent of the product dashboard app.

**Domain architecture:**
- `frontiermind.co` → this project (`website/`)
- `app.frontiermind.co` → product dashboard (root `app/`)

## Tech Stack

- Next.js 16, React 19, TypeScript
- Tailwind CSS v4 (via `@tailwindcss/postcss`)
- Lucide React (icons)
- Deployment: Vercel (free tier)
- No backend — static marketing content only

## Project Structure

```
website/
├── app/
│   ├── layout.tsx              # Root layout (fonts, metadata)
│   ├── page.tsx                # Landing page (composes all sections)
│   ├── globals.css             # Tailwind imports + CSS custom properties
│   ├── favicon.ico
│   └── components/
│       ├── MarketingHeader.tsx  # Sticky nav with mobile menu (client)
│       ├── HeroSection.tsx     # Dark hero with CTAs
│       ├── ValuePropSection.tsx # 3-card value propositions
│       ├── HowItWorksSection.tsx # 3-step flow
│       ├── CTASection.tsx      # Bottom CTA band
│       └── MarketingFooter.tsx # Footer with links
├── public/                     # Static assets
├── package.json
├── next.config.ts
├── tsconfig.json
├── postcss.config.mjs
└── .gitignore
```

## Commands

```bash
cd website
npm install    # Install dependencies
npm run dev    # Dev server at localhost:3000
npm run build  # Production build
npm run lint   # ESLint
```

## Design System

### Colors

| Token | Value | Usage |
|-------|-------|-------|
| Primary dark | `#030213` | Hero, CTA band, footer, header |
| Section light | `#f3f3f5` | How It Works background |
| White | `#ffffff` | Value props background |
| CTA gradient | `from-blue-600 to-indigo-700` | Buttons, icon backgrounds |

### Typography

| Font | Usage |
|------|-------|
| Geist Sans | Body text (loaded via `next/font/google`) |
| Libre Baskerville | Brand name "FrontierMind" only |

### Section Pattern

The page alternates between dark and light sections:
1. **Header** — dark, sticky
2. **Hero** — dark (`#030213`)
3. **Value Props** — white
4. **How It Works** — light gray (`#f3f3f5`)
5. **CTA Band** — dark (`#030213`)
6. **Footer** — dark (`#030213`)

### Spacing

- Section vertical padding: `py-24 sm:py-32`
- Max content width: `max-w-6xl` (1152px)
- Horizontal padding: `px-6`

### Responsive Breakpoints

| Breakpoint | Layout |
|------------|--------|
| Mobile (<640px) | Single column, hamburger nav, stacked cards |
| Tablet (640-1024px) | 2-column value prop cards |
| Desktop (>1024px) | 3-column cards, full nav, horizontal How It Works |

## Page Sections

### MarketingHeader (client component)
- Sticky header with "FrontierMind" logo (Libre Baskerville)
- Desktop: inline nav links + Login button
- Mobile: hamburger menu toggle
- Login links to `app.frontiermind.co/login`

### HeroSection
- Full-width dark section with gradient overlay
- Headline: "AI Copilot for Corporate Energy Projects"
- Primary CTA: "Contact Us" → `mailto:namho@frontiermind.co`
- Secondary CTA: "Learn More" → scrolls to `#value-props`

### ValuePropSection
- 3 cards: Contract Compliance, Payment Verification, Asset Management
- Each card has a Lucide icon, title, and description
- Cards have hover shadow effect

### HowItWorksSection
- 3-step visual flow with numbered badges
- Desktop: horizontal with connector lines
- Mobile: vertical stack

### CTASection
- Dark band with headline and Contact Us button
- Matches hero styling for visual bookending

### MarketingFooter
- Logo, email link, nav links, copyright
- Placeholder nav links for future pages

## Adding New Pages

1. Create `website/app/about/page.tsx` (or any route)
2. Import and use `MarketingHeader` and `MarketingFooter` for consistent chrome
3. Add metadata export for SEO
4. Update nav links in `MarketingHeader.tsx` and `MarketingFooter.tsx`

**Future improvement:** Extract header/footer into a route group layout (`(marketing)/layout.tsx`) when multiple pages share them.

## Deployment

### Vercel Setup

1. Create new Vercel project from this repo
2. Set **Root Directory** to `website/`
3. Framework preset: Next.js (auto-detected)
4. Deploy

### Custom Domain

1. Add `frontiermind.co` as custom domain on the website Vercel project
2. Add `app.frontiermind.co` as custom domain on the existing app Vercel project
3. Update DNS records at domain registrar:
   - `frontiermind.co` → Vercel CNAME for website project
   - `app.frontiermind.co` → Vercel CNAME for app project
4. Cancel Network Solutions website service after DNS propagation
