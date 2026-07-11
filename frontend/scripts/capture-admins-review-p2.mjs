/**
 * П.2 screenshots: owner admins review overview page.
 * SCREENSHOT_TOKEN = owner JWT (tenant=1)
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const dir = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.join(dir, '..', 'screenshots', 'admins-review-p2')
const TOKEN = process.env.SCREENSHOT_TOKEN
const BASE = process.env.SCREENSHOT_BASE || 'http://localhost:3000'

if (!TOKEN) {
  console.error('Set SCREENSHOT_TOKEN')
  process.exit(1)
}

fs.mkdirSync(OUT, { recursive: true })

async function authContext(browser) {
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } })
  await context.route('http://127.0.0.1:8000/**', async (route) => {
    const url = route.request().url().replace('127.0.0.1:8000', '127.0.0.1:8001')
    await route.continue({ url })
  })
  await context.route('http://localhost:8000/**', async (route) => {
    const url = route.request().url().replace('localhost:8000', '127.0.0.1:8001')
    await route.continue({ url })
  })
  await context.addCookies([
    { name: 'user_role', value: 'owner', domain: 'localhost', path: '/' },
    { name: 'is_admin', value: '0', domain: 'localhost', path: '/' },
  ])
  await context.addInitScript((t) => {
    localStorage.setItem('token', t)
    localStorage.setItem('user_role', 'owner')
    localStorage.setItem('is_admin', '0')
  }, TOKEN)
  return context
}

async function main() {
  const browser = await chromium.launch({ headless: true })

  // HR page still works
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(`${BASE}/dashboard/admins`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForSelector('text=Управление администраторами', { timeout: 20000 })
    await page.waitForTimeout(1500)
    await page.screenshot({ path: path.join(OUT, '01-hr-admins-page.png'), fullPage: true })
    await ctx.close()
    console.log('01 hr admins')
  }

  // Main overview + sidebar active
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(`${BASE}/dashboard/admins-review`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForSelector('text=Обзор админов', { timeout: 20000 })
    await page.waitForTimeout(2000)
    await page.screenshot({ path: path.join(OUT, '02-overview-table.png'), fullPage: true })
    await page.screenshot({ path: path.join(OUT, '06-sidebar-overview-active.png') })
    console.log('02 overview + 06 sidebar overview')
    await ctx.close()
  }

  // Recalc loading
  {
    const ctx = await authContext(browser)
    await ctx.route('**/api/v1/dashboard/admins-review/recalc-snapshots', async (route) => {
      await new Promise((r) => setTimeout(r, 2500))
      await route.continue()
    })
    const page = await ctx.newPage()
    await page.goto(`${BASE}/dashboard/admins-review`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForSelector('text=Пересчитать сейчас', { timeout: 20000 })
    const btn = page.getByRole('button', { name: 'Пересчитать сейчас' })
    await btn.click()
    await page.waitForTimeout(400)
    await page.screenshot({ path: path.join(OUT, '03-recalc-loading.png'), fullPage: true })
    console.log('03 recalc loading')
    await ctx.close()
  }

  // Recalc toast
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(`${BASE}/dashboard/admins-review`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForSelector('text=Пересчитать сейчас', { timeout: 20000 })
    await page.getByRole('button', { name: 'Пересчитать сейчас' }).click()
    await page.waitForSelector('text=/Пересчитано/', { timeout: 15000 })
    await page.waitForTimeout(500)
    await page.screenshot({ path: path.join(OUT, '04-recalc-toast.png'), fullPage: true })
    console.log('04 recalc toast')
    await ctx.close()
  }

  // Pending page — На оценке active
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(`${BASE}/dashboard/admins-review/pending`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForSelector('text=Качественные кейсы на оценке', { timeout: 20000 })
    await page.waitForTimeout(1500)
    await page.screenshot({ path: path.join(OUT, '05-sidebar-pending-active.png') })
    console.log('05 pending sidebar')
    await ctx.close()
  }

  await browser.close()
  console.log('Done:', OUT)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
