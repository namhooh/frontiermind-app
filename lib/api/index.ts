/**
 * API Client Module
 *
 * Re-exports all API client functionality for convenient imports.
 *
 * @example
 * ```typescript
 * import { APIClient, ContractsAPIError, type Contract } from '@/lib/api'
 *
 * const client = new APIClient({
 *   getAuthToken: async () => session?.access_token
 * })
 *
 * const contract = await client.getContract(123)
 * ```
 */

export {
  // Main API Client Class
  APIClient,

  // Error Class
  ContractsAPIError,

  // Standalone Functions (backward compatibility)
  parseContract,
  getContract,
  getContractClauses,
  evaluateRules,
  getDefaults,

  // Types - Entities
  type PIIEntity,
  type ExtractedClause,
  type Clause,
  type Contract,
  type DefaultEvent,
  type RuleResult,

  // Types - Requests/Responses
  type ParseContractOptions,
  type UploadProgress,
  type ContractParseResult,
  type RuleEvaluationResult,
  type EvaluateRulesRequest,
  type DefaultFilters,
  type CureDefaultResult,
  type APIClientConfig,
} from './contractsClient'
