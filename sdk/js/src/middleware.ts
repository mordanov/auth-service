/**
 * Express / Next.js request middleware for auth-client SDK.
 */
import { validateToken, TokenPayload } from './validator'
import { AuthError, ERR_NO_GRANT } from './errors'

export interface MiddlewareOptions {
  appName: string
  jwksUrl: string
}

// Extend Express Request type
declare module 'express' {
  interface Request {
    authUser?: TokenPayload
  }
}

/**
 * Create an Express middleware function.
 *
 * Usage:
 *   import { createMiddleware } from '@auth-service/client'
 *   app.use(createMiddleware({ appName: 'reminders-app', jwksUrl: AUTH_JWKS_URL }))
 */
export function createMiddleware(options: MiddlewareOptions) {
  return async function authMiddleware(
    req: { headers: Record<string, string | string[] | undefined>; authUser?: TokenPayload },
    res: { status: (n: number) => { json: (b: object) => void } },
    next: (err?: unknown) => void,
  ): Promise<void> {
    const authHeader = req.headers['authorization']
    const token = typeof authHeader === 'string' && authHeader.startsWith('Bearer ')
      ? authHeader.slice(7)
      : null

    if (!token) {
      res.status(401).json({ error: 'missing_token', message: 'Authorization header required' })
      return
    }

    try {
      req.authUser = await validateToken(token, options.appName, options.jwksUrl)
      next()
    } catch (err) {
      if (err instanceof AuthError) {
        const status = err.code === ERR_NO_GRANT ? 403 : 401
        res.status(status).json({ error: err.code, message: err.message })
      } else {
        next(err)
      }
    }
  }
}
