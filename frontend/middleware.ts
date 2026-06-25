import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl
  const role = request.cookies.get('user_role')?.value  // 'owner' | 'chatter' | undefined

  // ── Root redirect ─────────────────────────────────────────────────────────
  if (pathname === '/') {
    if (!role) return NextResponse.redirect(new URL('/login', request.url))
    if (role === 'chatter') return NextResponse.redirect(new URL('/portal', request.url))
    return NextResponse.redirect(new URL('/dashboard', request.url))
  }

  // ── Protected routes: require a role cookie ───────────────────────────────
  const isDashboard = pathname.startsWith('/dashboard')
  const isPortal    = pathname.startsWith('/portal')

  if (isDashboard || isPortal) {
    // No session at all → login
    if (!role) {
      const loginUrl = new URL('/login', request.url)
      loginUrl.searchParams.set('next', pathname)
      return NextResponse.redirect(loginUrl)
    }

    // Wrong role → correct portal
    if (role === 'chatter' && isDashboard) {
      return NextResponse.redirect(new URL('/portal', request.url))
    }
    if (role === 'owner' && isPortal) {
      return NextResponse.redirect(new URL('/dashboard', request.url))
    }
  }

  return NextResponse.next()
}

export const config = {
  matcher: [
    '/',
    '/dashboard',
    '/dashboard/:path*',
    '/portal',
    '/portal/:path*',
  ],
}
