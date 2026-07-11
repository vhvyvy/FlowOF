/**
 * Admin portal chatters: two sections + mapping modal + success toast.
 * Requires: frontend :3000, backend :8001 (proxied from :8000), SCREENSHOT_TOKEN (admin JWT).
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const dir = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.join(dir, '..', 'screenshots', 'admin-portal-chatters-mapping')
const TOKEN = process.env.SCREENSHOT_TOKEN
const BASE = process.env.SCREENSHOT_BASE || 'http://localhost:3000'
const TEST_OM_ID = process.env.TEST_OM_ID || '9900719'
const TEST_DISPLAY = process.env.TEST_DISPLAY || '@Zarik0719'

if (!TOKEN) {
  console.error('Set SCREENSHOT_TOKEN (admin JWT)')
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
    { name: 'is_admin', value: '1', domain: 'localhost', path: '/' },
  ])
  await context.addInitScript((t) => {
    localStorage.setItem('token', t)
    localStorage.setItem('user_role', 'owner')
    localStorage.setItem('is_admin', '1')
  }, TOKEN)
  return context
}

async function main() {
  const browser = await chromium.launch({ headless: true })

  // Screenshot 1: two sections with orphans showing revenue + KPI dashes
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(`${BASE}/admin-portal/chatters`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForSelector('text=Активные чаттеры', { timeout: 30000 })
    await page.waitForSelector('text=Требуют маппинга', { timeout: 30000 })
    await page.waitForTimeout(2000)
    await page.screenshot({ path: path.join(OUT, '01-two-sections.png'), fullPage: true })
    console.log('01 two sections')
    await ctx.close()
  }

  // Screenshot 2: mapping modal with prefilled display_name
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(`${BASE}/admin-portal/chatters`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForSelector('text=Требуют маппинга', { timeout: 30000 })
    const mapBtn = page.locator('button:has-text("Смаппить")').first()
    await mapBtn.waitFor({ state: 'visible', timeout: 20000 })
    await mapBtn.click()
    await page.waitForSelector('[data-testid="mapping-modal"]', { timeout: 15000 })
    await page.waitForTimeout(500)
    await page.screenshot({ path: path.join(OUT, '02-mapping-modal.png') })
    console.log('02 mapping modal')
    await ctx.close()
  }

  // Screenshot 3: successful mapping — toast + chatter in top section
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(`${BASE}/admin-portal/chatters`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForSelector('text=Требуют маппинга', { timeout: 30000 })

    const targetRow = page.locator('tr', { hasText: TEST_DISPLAY }).filter({ has: page.locator('button:has-text("Смаппить")') })
    if (await targetRow.count() === 0) {
      const mapBtn = page.locator('button:has-text("Смаппить")').first()
      await mapBtn.click()
    } else {
      await targetRow.locator('button:has-text("Смаппить")').click()
    }

    await page.waitForSelector('[data-testid="mapping-modal"]', { timeout: 15000 })
    await page.locator('[data-testid="mapping-modal"] input').first().fill(TEST_OM_ID)
    await page.getByRole('button', { name: 'Добавить' }).click()
    await page.waitForSelector('text=/Маппинг сохранён/', { timeout: 20000 })
    await page.waitForTimeout(800)
    await page.screenshot({ path: path.join(OUT, '03-mapping-success.png'), fullPage: true })
    console.log('03 mapping success')
    await ctx.close()
  }

  await browser.close()
  console.log('Done:', OUT)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
