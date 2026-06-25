import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'

export default async function HomePage() {
  const cookieStore = await cookies()
  const role = cookieStore.get('user_role')?.value

  if (role === 'chatter') redirect('/portal')
  if (role === 'owner') redirect('/dashboard')
  redirect('/login')
}
