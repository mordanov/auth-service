/**
 * JWT RS256 validator using the `jose` library.
 * Fetches and caches the JWKS public key set.
 */
import { createRemoteJWKSet, jwtVerify, JWTPayload, errors } from 'jose'
import { InvalidTokenError, NoGrantError, TokenExpiredError } from './errors'

export interface TokenPayload extends JWTPayload {
  sub: string
  grants: string[]
}

// Per-URL JWKS key sets (module-level cache via jose's createRemoteJWKSet)
const _keySets = new Map<string, ReturnType<typeof createRemoteJWKSet>>()

function getKeySet(jwksUrl: string): ReturnType<typeof createRemoteJWKSet> {
  if (!_keySets.has(jwksUrl)) {
    _keySets.set(jwksUrl, createRemoteJWKSet(new URL(jwksUrl), {
      cacheMaxAge: 5 * 60 * 1000, // 5 min
    }))
  }
  return _keySets.get(jwksUrl)!
}

/**
 * Validate an RS256 JWT access token and verify the appName grant.
 *
 * @param token     Compact JWT string
 * @param appName   Application name to check in grants[] claim
 * @param jwksUrl   Full URL to /.well-known/jwks.json
 * @returns Decoded TokenPayload on success
 * @throws TokenExpiredError | InvalidTokenError | NoGrantError
 */
export async function validateToken(
  token: string,
  appName: string,
  jwksUrl: string,
): Promise<TokenPayload> {
  const keySet = getKeySet(jwksUrl)

  let payload: TokenPayload
  try {
    const result = await jwtVerify<TokenPayload>(token, keySet, {
      algorithms: ['RS256'],
    })
    payload = result.payload
  } catch (err) {
    if (err instanceof errors.JWTExpired) {
      throw new TokenExpiredError()
    }
    throw new InvalidTokenError(err instanceof Error ? err.message : 'JWT verification failed')
  }

  const grants: string[] = Array.isArray(payload.grants) ? payload.grants : []
  if (!grants.includes(appName)) {
    throw new NoGrantError(appName)
  }

  return payload
}

export { AuthError } from './errors'
