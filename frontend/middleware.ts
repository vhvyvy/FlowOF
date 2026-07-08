import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl
  const role    = request.cookies.get('user_role')?.value   // 'owner' | 'chatter' | undefined
  const isAdmin = request.cookies.get('is_admin')?.value === '1'

  // ── Root redirect ─────────────────────────────────────────────────────────
  if (pathname === '/') {
    if (!role) return NextResponse.redirect(new URL('/login', request.url))
    if (isAdmin) return NextResponse.redirect(new URL('/admin-portal', request.url))
    if (role === 'chatter') return NextResponse.redirect(new URL('/portal', request.url))
    return NextResponse.redirect(new URL('/dashboard', request.url))
  }

  // ── Admin Portal ──────────────────────────────────────────────────────────
  if (pathname.startsWith('/admin-portal')) {
    if (!role) {
      const loginUrl = new URL('/login', request.url)
      loginUrl.searchParams.set('next', pathname)
      return NextResponse.redirect(loginUrl)
    }
    if (!isAdmin) {
      // Has a session but not an admin → send to appropriate portal
      return NextResponse.redirect(
        new URL(role === 'chatter' ? '/portal' : '/dashboard', request.url)
      )
    }
    return NextResponse.next()
  }

  // ── Dashboard & Portal ────────────────────────────────────────────────────
  const isDashboard = pathname.startsWith('/dashboard')
  const isPortal    = pathname.startsWith('/portal')

  if (isDashboard || isPortal) {
    if (!role) {
      const loginUrl = new URL('/login', request.url)
      loginUrl.searchParams.set('next', pathname)
      return NextResponse.redirect(loginUrl)
    }
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
    '/admin-portal',
    '/admin-portal/:path*',
  ],
}
