import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl
  const role = request.cookies.get('user_role')?.value

  const isDashboard = pathname.startsWith('/dashboard')
  const isPortal = pathname.startsWith('/portal')

  if (role === 'chatter' && isDashboard) {
    return NextResponse.redirect(new URL('/portal', request.url))
  }

  if (role === 'owner' && isPortal) {
    return NextResponse.redirect(new URL('/dashboard', request.url))
  }

  return NextResponse.next()
}

export const config = {
  matcher: ['/dashboard/:path*', '/portal/:path*'],
}
