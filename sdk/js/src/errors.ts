/** Error codes — use these constants for comparisons, not inline strings. */
export const ERR_TOKEN_EXPIRED = 'TOKEN_EXPIRED' as const
export const ERR_INVALID_TOKEN = 'INVALID_TOKEN' as const
export const ERR_NO_GRANT = 'NO_GRANT' as const

export class AuthError extends Error {
  constructor(message: string, public readonly code: string) {
    super(message)
    this.name = 'AuthError'
  }
}
export class TokenExpiredError extends AuthError {
  constructor() { super('Token has expired', ERR_TOKEN_EXPIRED) }
}
export class InvalidTokenError extends AuthError {
  constructor(msg = 'Invalid token') { super(msg, ERR_INVALID_TOKEN) }
}
export class NoGrantError extends AuthError {
  constructor(app: string) { super(`No grant for app: ${app}`, ERR_NO_GRANT) }
}
