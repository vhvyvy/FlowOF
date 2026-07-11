/**
 * Baseline preview in Create Case modal — 3 states.
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const dir = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.join(dir, '..', 'screenshots', 'baseline-preview-modal')
const TOKEN = process.env.SCREENSHOT_TOKEN
const BASE = process.env.SCREENSHOT_BASE || 'http://localhost:3000'

if (!TOKEN) {
  console.error('Set SCREENSHOT_TOKEN (admin JWT, TENANT_ID=1)')
  process.exit(1)
}

fs.mkdirSync(OUT, { recursive: true })

async function authContext(browser, extraRoutes) {
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } })
  await context.route('http://127.0.0.1:8000/**', async (route) => {
    const url = route.request().url().replace('127.0.0.1:8000', '127.0.0.1:8001')
    await route.continue({ url })
  })
  await context.route('http://localhost:8000/**', async (route) => {
    const url = route.request().url().replace('localhost:8000', '127.0.0.1:8001')
    await route.continue({ url })
  })
  if (extraRoutes) await extraRoutes(context)
  await context.addCookies([
    { name: 'user_role', value: 'owner', domain: 'localhost', path: '/' },
    { name: 'is_admin', value: '1', domain: 'localhost', path: '/' },
  ])
  await context.addInitScript((t) => {
    localStorage.setItem('token', t)
    localStorage.setItem('user_role', 'owner')
    localStorage.setItem('is_admin', '1')
  }, TOKEN)
  return context
}

async function openCaseModal(page) {
  await page.goto(`${BASE}/admin-portal/chatters`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('text=Активные чаттеры', { timeout: 30000 })
  const row = page.locator('tr', { hasText: '@Baby_W0rker' }).first()
  await row.locator('button:has-text("Кейс")').click()
  await page.waitForSelector('text=Открыть кейс', { timeout: 15000 })
  await page.waitForTimeout(800)
}

async function main() {
  const browser = await chromium.launch({ headless: true })

  // a) available=true
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await openCaseModal(page)
    await page.waitForSelector('[data-testid="baseline-preview"]:has-text("Baseline:")', { timeout: 20000 })
    await page.screenshot({ path: path.join(OUT, '01-baseline-available.png') })
    console.log('01 available')
    await ctx.close()
  }

  // b) available=false (mock API — no mapped chatter without daily in active list)
  {
    const ctx = await authContext(browser, async (context) => {
      await context.route('**/baseline-preview**', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ available: false, lookback_days: 30 }),
        })
      })
    })
    const page = await ctx.newPage()
    await openCaseModal(page)
    await page.waitForSelector('text=Недостаточно данных за 30 дней', { timeout: 20000 })
    const submit = page.getByRole('button', { name: 'Создать кейс' })
    await page.waitForTimeout(300)
    await page.screenshot({ path: path.join(OUT, '02-baseline-unavailable.png') })
    console.log('02 unavailable, submit disabled:', await submit.isDisabled())
    await ctx.close()
  }

  // c) tooltip on month badge
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await openCaseModal(page)
    await page.waitForSelector('[data-testid="month-metric-badge"]', { timeout: 15000 })
    const badge = page.locator('[data-testid="month-metric-badge"]')
    await badge.hover()
    await page.waitForTimeout(500)
    await page.screenshot({ path: path.join(OUT, '03-month-badge-tooltip.png') })
    console.log('03 tooltip')
    await ctx.close()
  }

  await browser.close()
  console.log('Done:', OUT)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
