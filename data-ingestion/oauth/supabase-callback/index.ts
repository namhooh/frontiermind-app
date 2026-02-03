/**
 * OAuth Callback Edge Function
 *
 * Handles OAuth 2.0 authorization code exchange for inverter integrations.
 * Supports: Enphase, SMA
 *
 * Flow:
 * 1. Frontend initiates OAuth flow, receives authorization code
 * 2. Frontend calls this function with code and state
 * 3. This function exchanges code for tokens
 * 4. Tokens are encrypted and stored in integration_credential table
 */

import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.39.0";
import * as base64 from "https://deno.land/std@0.168.0/encoding/base64.ts";
import { corsHeaders } from "../_shared/cors.ts";

// Provider configurations
const PROVIDERS: Record<
  string,
  {
    tokenUrl: string;
    clientIdEnvVar: string;
    clientSecretEnvVar: string;
  }
> = {
  enphase: {
    tokenUrl: "https://api.enphaseenergy.com/oauth/token",
    clientIdEnvVar: "ENPHASE_CLIENT_ID",
    clientSecretEnvVar: "ENPHASE_CLIENT_SECRET",
  },
  sma: {
    tokenUrl: "https://auth.sma.de/oauth2/token",
    clientIdEnvVar: "SMA_CLIENT_ID",
    clientSecretEnvVar: "SMA_CLIENT_SECRET",
  },
};

interface OAuthRequest {
  provider: string;
  code: string;
  state: string;
  redirect_uri: string;
  organization_id: number;
  credential_name?: string;
}

interface TokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  token_type: string;
  scope?: string;
}

/**
 * Encrypt credentials using AES-256-GCM (authenticated encryption).
 * Format: [IV_12_BYTES][CIPHERTEXT][AUTH_TAG_16_BYTES] → base64
 * Compatible with Python decrypt in base_fetcher.py
 */
async function encryptCredentials(
  data: Record<string, unknown>,
  encryptionKey: string
): Promise<string> {
  const key = base64.decode(encryptionKey);
  if (key.length < 32) {
    throw new Error("Encryption key must be at least 32 bytes");
  }

  // AES-GCM uses 12-byte IV (NIST recommendation)
  const iv = crypto.getRandomValues(new Uint8Array(12));

  const encoder = new TextEncoder();
  const dataBytes = encoder.encode(JSON.stringify(data));

  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    key.slice(0, 32),
    { name: "AES-GCM" },
    false,
    ["encrypt"]
  );

  // GCM automatically appends 16-byte auth tag to ciphertext
  const encrypted = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    cryptoKey,
    dataBytes
  );

  // Combine: IV (12) + ciphertext + auth tag (16)
  const combined = new Uint8Array(iv.length + encrypted.byteLength);
  combined.set(iv, 0);
  combined.set(new Uint8Array(encrypted), iv.length);

  return base64.encode(combined);
}

/**
 * Create HMAC-signed state parameter for CSRF protection.
 * Returns URL-safe base64 encoding to survive OAuth redirects.
 *
 * @param orgId - Organization ID to embed in state
 * @param secret - Secret key for HMAC signing
 * @returns URL-safe base64-encoded signed state
 *
 * Usage (frontend):
 *   const state = await createState(orgId, OAUTH_STATE_SECRET);
 *   window.location.href = `${authUrl}?state=${state}&...`;
 */
async function createState(orgId: number, secret: string): Promise<string> {
  const payload = { organization_id: orgId, ts: Date.now() };
  const data = JSON.stringify(payload);

  const encoder = new TextEncoder();
  const keyData = encoder.encode(secret);
  const messageData = encoder.encode(data);

  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    keyData,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );

  const signature = await crypto.subtle.sign("HMAC", cryptoKey, messageData);
  const sig = base64.encode(new Uint8Array(signature));

  // Use URL-safe base64 encoding (replace +/= with URL-safe chars)
  const base64State = btoa(JSON.stringify({ data, sig }));
  return base64State.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/**
 * Validate state parameter to prevent CSRF attacks.
 *
 * Strict HMAC enforcement - requires signed state format: { data: JSON, sig: HMAC }
 * Legacy unsigned states are rejected for security.
 *
 * @param state - Base64-encoded state from OAuth callback
 * @param expectedOrgId - Expected organization ID
 * @param secret - Secret key for HMAC verification (required)
 * @returns true if state is valid
 */
async function validateState(
  state: string,
  expectedOrgId: number,
  secret: string
): Promise<boolean> {
  try {
    // Restore URL-safe base64 padding before decode
    let standardBase64 = state.replace(/-/g, "+").replace(/_/g, "/");
    while (standardBase64.length % 4) {
      standardBase64 += "=";
    }

    const decoded = JSON.parse(atob(standardBase64));

    // Require HMAC-signed format - no legacy fallback
    if (!decoded.data || !decoded.sig) {
      console.error("State missing required HMAC fields");
      return false;
    }

    // Verify HMAC signature
    const encoder = new TextEncoder();
    const keyData = encoder.encode(secret);
    const messageData = encoder.encode(decoded.data);

    const cryptoKey = await crypto.subtle.importKey(
      "raw",
      keyData,
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["verify"]
    );

    const expectedSig = base64.decode(decoded.sig);
    const isValid = await crypto.subtle.verify(
      "HMAC",
      cryptoKey,
      expectedSig,
      messageData
    );

    if (!isValid) {
      console.error("State HMAC verification failed");
      return false;
    }

    const payload = JSON.parse(decoded.data);

    // Check expiry (10 minutes)
    const age = Date.now() - payload.ts;
    if (age > 600000) {
      console.error("State expired:", age, "ms old");
      return false;
    }

    return payload.organization_id === expectedOrgId;
  } catch (err) {
    console.error("State validation error:", err);
    return false;
  }
}

/**
 * Exchange authorization code for tokens
 */
async function exchangeCodeForTokens(
  provider: string,
  code: string,
  redirectUri: string
): Promise<TokenResponse> {
  const config = PROVIDERS[provider];
  if (!config) {
    throw new Error(`Unknown provider: ${provider}`);
  }

  const clientId = Deno.env.get(config.clientIdEnvVar);
  const clientSecret = Deno.env.get(config.clientSecretEnvVar);

  if (!clientId || !clientSecret) {
    throw new Error(`Missing OAuth credentials for provider: ${provider}`);
  }

  // Build token request
  const params = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    redirect_uri: redirectUri,
    client_id: clientId,
    client_secret: clientSecret,
  });

  const response = await fetch(config.tokenUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: params.toString(),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(
      `Token exchange failed: ${response.status} - ${errorText}`
    );
  }

  return response.json();
}

/**
 * Get data source ID for provider
 * @throws Error if data source not found (requires proper DB seeding)
 */
async function getDataSourceId(
  supabase: ReturnType<typeof createClient>,
  provider: string
): Promise<number> {
  const { data, error } = await supabase
    .from("data_source")
    .select("id")
    .eq("source_type", provider)
    .single();

  if (error || !data) {
    console.error(`Data source lookup failed for ${provider}:`, error);
    throw new Error(
      `Data source not found for provider: ${provider}. Ensure data_source table is seeded correctly.`
    );
  }

  return data.id;
}

serve(async (req) => {
  // Handle CORS preflight
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    // Only accept POST requests
    if (req.method !== "POST") {
      return new Response(JSON.stringify({ error: "Method not allowed" }), {
        status: 405,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      });
    }

    // Parse request body
    const body: OAuthRequest = await req.json();
    const { provider, code, state, redirect_uri, organization_id, credential_name } =
      body;

    // Validate required fields
    if (!provider || !code || !state || !redirect_uri || !organization_id) {
      return new Response(
        JSON.stringify({ error: "Missing required fields" }),
        {
          status: 400,
          headers: { ...corsHeaders, "Content-Type": "application/json" },
        }
      );
    }

    // Validate provider
    if (!PROVIDERS[provider]) {
      return new Response(
        JSON.stringify({ error: `Unknown provider: ${provider}` }),
        {
          status: 400,
          headers: { ...corsHeaders, "Content-Type": "application/json" },
        }
      );
    }

    // Validate state (CSRF protection - strict HMAC enforcement)
    const stateSecret = Deno.env.get("OAUTH_STATE_SECRET");
    if (!stateSecret) {
      throw new Error("OAUTH_STATE_SECRET not configured");
    }

    if (!(await validateState(state, organization_id, stateSecret))) {
      return new Response(
        JSON.stringify({ error: "Invalid or expired state parameter" }),
        {
          status: 400,
          headers: { ...corsHeaders, "Content-Type": "application/json" },
        }
      );
    }

    // Exchange code for tokens
    console.log(`Exchanging code for ${provider} tokens...`);
    const tokens = await exchangeCodeForTokens(provider, code, redirect_uri);

    // Get encryption key
    const encryptionKey = Deno.env.get("ENCRYPTION_KEY");
    if (!encryptionKey) {
      throw new Error("ENCRYPTION_KEY not configured");
    }

    // Encrypt credentials
    const encryptedCredentials = await encryptCredentials(
      {
        access_token: tokens.access_token,
        refresh_token: tokens.refresh_token,
        token_type: tokens.token_type,
        scope: tokens.scope,
      },
      encryptionKey
    );

    // Calculate token expiry
    const now = new Date();
    const expiresAt = new Date(now.getTime() + tokens.expires_in * 1000);

    // Initialize Supabase client
    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const supabase = createClient(supabaseUrl, supabaseKey);

    // Get data source ID
    const dataSourceId = await getDataSourceId(supabase, provider);

    // Store credentials
    const { data: credential, error: insertError } = await supabase
      .from("integration_credential")
      .insert({
        organization_id,
        data_source_id: dataSourceId,
        credential_name: credential_name || `${provider} OAuth Credential`,
        encrypted_credentials: encryptedCredentials,
        auth_type: "oauth2",
        token_expires_at: expiresAt.toISOString(),
        token_refreshed_at: now.toISOString(),
        is_active: true,
      })
      .select()
      .single();

    if (insertError) {
      console.error("Failed to store credentials:", insertError);
      throw new Error(`Failed to store credentials: ${insertError.message}`);
    }

    console.log(`Successfully stored ${provider} credentials for org ${organization_id}`);

    return new Response(
      JSON.stringify({
        success: true,
        credential_id: credential.id,
        expires_at: expiresAt.toISOString(),
      }),
      {
        status: 200,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      }
    );
  } catch (error) {
    console.error("OAuth callback error:", error);

    return new Response(
      JSON.stringify({
        error: error instanceof Error ? error.message : "Unknown error",
      }),
      {
        status: 500,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      }
    );
  }
});
