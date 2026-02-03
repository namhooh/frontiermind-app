/**
 * OAuth API Client
 *
 * Provides secure OAuth flow helpers. MUST be used before initiating
 * any OAuth redirect to external providers (Enphase, SMA).
 *
 * Security: The OAuth state parameter is HMAC-signed by the backend
 * to prevent CSRF attacks. Never generate state client-side.
 */

const BACKEND_URL = process.env.NEXT_PUBLIC_PYTHON_BACKEND_URL;

export interface OAuthStateResponse {
  state: string;
}

export interface OAuthProviderConfig {
  authUrl: string;
  clientId: string | undefined;
}

export type OAuthProvider = 'enphase' | 'sma';

/**
 * Generate a secure HMAC-signed OAuth state parameter.
 *
 * CRITICAL: Always call this before redirecting to OAuth providers.
 * The state parameter prevents CSRF attacks during OAuth flows.
 *
 * @param organizationId - The organization initiating the OAuth flow
 * @returns URL-safe base64-encoded signed state (valid for 10 minutes)
 *
 * @example
 * ```typescript
 * const { state } = await generateOAuthState(orgId);
 * const authUrl = `https://api.enphase.com/oauth/authorize?state=${state}&...`;
 * window.location.href = authUrl;
 * ```
 */
export async function generateOAuthState(
  organizationId: number
): Promise<OAuthStateResponse> {
  if (!BACKEND_URL) {
    throw new Error('NEXT_PUBLIC_PYTHON_BACKEND_URL is not configured');
  }

  const response = await fetch(`${BACKEND_URL}/api/oauth/state`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ organization_id: organizationId }),
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => response.statusText);
    throw new Error(`Failed to generate OAuth state: ${errorText}`);
  }

  return response.json();
}

/**
 * Get OAuth provider configuration.
 *
 * @param provider - The OAuth provider ('enphase' | 'sma')
 * @returns Provider-specific OAuth configuration
 */
export function getOAuthProviderConfig(provider: OAuthProvider): OAuthProviderConfig {
  const configs: Record<OAuthProvider, OAuthProviderConfig> = {
    enphase: {
      authUrl: 'https://api.enphaseenergy.com/oauth/authorize',
      clientId: process.env.NEXT_PUBLIC_ENPHASE_CLIENT_ID,
    },
    sma: {
      authUrl: 'https://auth.sma.de/oauth2/authorize',
      clientId: process.env.NEXT_PUBLIC_SMA_CLIENT_ID,
    },
  };

  return configs[provider];
}

/**
 * Build OAuth authorization URL with required parameters.
 *
 * This function handles:
 * 1. Generating a secure HMAC-signed state parameter via the backend
 * 2. Constructing the full authorization URL with all required params
 *
 * @param provider - 'enphase' | 'sma'
 * @param organizationId - Organization ID initiating the OAuth flow
 * @param redirectUri - Callback URL after authorization
 * @returns Complete authorization URL to redirect user to
 *
 * @example
 * ```typescript
 * const authUrl = await buildOAuthUrl('enphase', orgId, callbackUrl);
 * window.location.href = authUrl;
 * ```
 */
export async function buildOAuthUrl(
  provider: OAuthProvider,
  organizationId: number,
  redirectUri: string
): Promise<string> {
  const { state } = await generateOAuthState(organizationId);
  const config = getOAuthProviderConfig(provider);

  if (!config.clientId) {
    throw new Error(`OAuth client ID not configured for provider: ${provider}`);
  }

  const params = new URLSearchParams({
    response_type: 'code',
    client_id: config.clientId,
    redirect_uri: redirectUri,
    state,
  });

  return `${config.authUrl}?${params.toString()}`;
}
