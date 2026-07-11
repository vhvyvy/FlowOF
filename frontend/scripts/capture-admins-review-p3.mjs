/**
 * П.3 screenshots: owner admin detail page.
 * SCREENSHOT_TOKEN = owner JWT (tenant=1)
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const dir = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.join(dir, '..', 'screenshots', 'admins-review-p3')
const TOKEN = process.env.SCREENSHOT_TOKEN
const BASE = process.env.SCREENSHOT_BASE || 'http://localhost:3000'
const ADMIN_ID = process.env.SCREENSHOT_ADMIN_ID || '53'

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
  const url = `${BASE}/dashboard/admins-review/admins/${ADMIN_ID}`

  // 01 — overview (header + KPI + period switcher)
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForSelector('text=К обзору', { timeout: 20000 })
    await page.waitForTimeout(2000)
    await page.screenshot({ path: path.join(OUT, '01-admin-overview.png'), fullPage: true })
    console.log('01 admin overview')
    await ctx.close()
  }

  // 02 — cases section (current month, scroll to cases)
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForSelector('text=/Кейсы за/', { timeout: 20000 })
    const heading = page.locator('h2', { hasText: /^Кейсы за/ }).first()
    await heading.scrollIntoViewIfNeeded()
    await page.waitForTimeout(800)
    await page.screenshot({ path: path.join(OUT, '02-cases-section.png'), fullPage: false })
    console.log('02 cases section')
    await ctx.close()
  }

  // 03 — ledger section (current month)
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForSelector('text=/Ledger за/', { timeout: 20000 })
    const heading = page.locator('h2', { hasText: /^Ledger за/ }).first()
    await heading.scrollIntoViewIfNeeded()
    await page.waitForTimeout(800)
    await page.screenshot({ path: path.join(OUT, '03-ledger-section.png'), fullPage: false })
    console.log('03 ledger section')
    await ctx.close()
  }

  // 04 — previous month empty state
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForSelector('text=Предыдущий', { timeout: 20000 })
    await page.getByRole('button', { name: 'Предыдущий' }).click()
    await page.waitForSelector('text=Нет кейсов за выбранный период', { timeout: 15000 })
    await page.waitForTimeout(800)
    await page.screenshot({ path: path.join(OUT, '04-previous-month-empty.png'), fullPage: true })
    console.log('04 previous month empty')
    await ctx.close()
  }

  await browser.close()
  console.log('Done:', OUT)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
