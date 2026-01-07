<!--
  SYNC IMPACT REPORT
  ==================
  Version: Initial → v1.0.0
  Change Type: MAJOR - Initial constitution creation
  Date: 2025-12-13

  Principles Defined:
  - I. Test-First Development (NON-NEGOTIABLE)
  - II. Component-First Architecture
  - III. Database Schema Discipline
  - IV. Security-First
  - V. Simplicity & YAGNI

  Sections Added:
  - Core Principles (5 principles)
  - Development Workflow
  - Quality Gates
  - Governance

  Templates Requiring Updates:
  ✅ plan-template.md - Constitution Check section aligns
  ✅ spec-template.md - Requirements structure aligns
  ✅ tasks-template.md - Test-first workflow aligns

  Follow-up TODOs:
  - None - all placeholders resolved
-->

# FrontierMind Constitution

## Core Principles

### I. Test-First Development (NON-NEGOTIABLE)

Test-Driven Development is mandatory for all feature work. Tests MUST be written before implementation, verified to fail, then implementation proceeds to make them pass. The Red-Green-Refactor cycle is strictly enforced.

**Rules**:
- Write acceptance tests that capture user requirements first
- Verify tests fail (Red phase)
- Implement minimal code to pass tests (Green phase)
- Refactor for quality while keeping tests passing
- No implementation without failing tests

**Rationale**: TDD ensures we build what's specified, provides living documentation, catches regressions early, and forces clear requirements before coding.

### II. Component-First Architecture

Every UI feature must be built as reusable, isolated components with clear boundaries. Components should be independently testable and composable.

**Rules**:
- Components MUST have a single, clear responsibility
- Props interface defines component contract
- No direct dependencies on global state unless explicitly managed
- Components should work in isolation (Storybook-style)
- Shared components live in `/components`, feature-specific in feature directories

**Rationale**: Isolation enables reusability, testability, and maintainability. Clear boundaries prevent tangled dependencies and enable parallel development.

### III. Database Schema Discipline

All database schema changes MUST go through formal migration processes. Schema is versioned, reviewed, and cannot be modified directly in production.

**Rules**:
- Schema changes MUST be via migration files (no manual SQL execution)
- Migrations MUST be reversible (up/down scripts)
- Breaking schema changes require deprecation period (backwards compatibility phase)
- Schema changes require peer review before merge
- Production migrations MUST be tested in staging first

**Rationale**: Uncontrolled schema changes cause data loss, application crashes, and deployment failures. Formal migrations provide audit trail, rollback capability, and team coordination.

### IV. Security-First

Security is not optional. All user input MUST be validated, authenticated endpoints MUST verify authorization, and security vulnerabilities MUST be addressed before feature completion.

**Rules**:
- Input validation at system boundaries (API endpoints, form submissions)
- Authentication required for protected routes (use Supabase Auth)
- Authorization checks on every protected resource access
- Sensitive data (tokens, API keys) MUST never be committed to version control
- SQL injection, XSS, CSRF protections MUST be in place
- Security reviews required for authentication, payment, or data export features

**Rationale**: Security breaches damage user trust, violate privacy, and create legal liability. Security must be built-in from the start, not added later.

### V. Simplicity & YAGNI

Start with the simplest solution that solves the current requirement. Do not build for hypothetical future needs. Avoid premature abstractions and over-engineering.

**Rules**:
- Implement only what is specified in current requirements
- Three instances of duplication before considering abstraction
- No architectural patterns (Repository, Factory, etc.) unless complexity demands it
- No feature flags or configuration for single-use cases
- Question any dependency addition - prefer built-in solutions first

**Rationale**: Over-engineering wastes time, adds bugs, and creates maintenance burden. Simple code is easier to understand, modify, and debug. Requirements change - building for uncertain futures is waste.

## Development Workflow

### Feature Development Process

1. **Specification Phase**: Feature requirements documented in `spec.md` with user stories and acceptance criteria
2. **Planning Phase**: Implementation plan created in `plan.md` with technical approach and architecture decisions
3. **Test Phase**: Acceptance tests written based on spec, verified to fail
4. **Implementation Phase**: Code written to pass tests, following constitution principles
5. **Review Phase**: Peer review verifying constitution compliance and test coverage
6. **Integration Phase**: Merged to main after all checks pass

### Branch Strategy

- `main` branch is production-ready at all times
- Feature branches: `###-feature-name` format (numbered)
- Commit frequently with descriptive messages
- Pull requests require review and passing tests before merge

### Code Review Requirements

All pull requests MUST:
- Have passing tests (no failing tests allowed)
- Include test coverage for new code paths
- Follow established patterns in codebase
- Have clear commit messages explaining "why" not just "what"
- Address all review feedback before merge

## Quality Gates

### Pre-Implementation Gates

- [ ] Requirements documented in spec.md with acceptance criteria
- [ ] Technical approach documented in plan.md
- [ ] Tests written and verified to fail (Red phase)
- [ ] Constitution compliance verified (no violations or justified exceptions)

### Pre-Merge Gates

- [ ] All tests passing (Green phase)
- [ ] Type checking passes (`npm run build` with no errors)
- [ ] Linting passes (`npm run lint` with no errors)
- [ ] Code review completed and approved
- [ ] Constitution principles followed (or exceptions documented)

### Production Deployment Gates

- [ ] Staging deployment successful
- [ ] Manual QA completed on staging
- [ ] Database migrations tested in staging
- [ ] Rollback plan documented
- [ ] Security review completed (if security-sensitive feature)

## Governance

### Constitution Authority

This constitution supersedes all other development practices and guidelines. When conflicts arise, constitution principles take precedence.

### Amendment Process

Constitution amendments require:
1. Documented proposal with rationale for change
2. Team discussion and consensus
3. Version increment following semantic versioning (MAJOR.MINOR.PATCH)
4. Update of dependent templates and documentation
5. Commit documenting the amendment with sync impact report

### Versioning Policy

- **MAJOR**: Backward-incompatible changes, principle removal or redefinition
- **MINOR**: New principle added or materially expanded guidance
- **PATCH**: Clarifications, wording improvements, non-semantic refinements

### Compliance Review

All pull requests MUST verify compliance with this constitution. Violations are acceptable ONLY when:
- Clearly documented with justification in plan.md Complexity Tracking section
- Simpler alternatives are evaluated and rejected with reasoning
- Temporary violation with migration plan to compliance

### Complexity Justification

If a feature violates Simplicity & YAGNI or requires architectural patterns, document in plan.md:
- Which principle is violated
- Why the complexity is necessary for current (not future) requirements
- What simpler alternatives were considered and why they're insufficient

**Version**: 1.0.0 | **Ratified**: 2025-12-13 | **Last Amended**: 2025-12-13
