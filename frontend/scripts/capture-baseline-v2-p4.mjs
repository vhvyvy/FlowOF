/**
 * Baseline v2 P.4 screenshots: modal 4-cards, case page 2 rows, new chatter, v1 control.
 *
 * Prereqs:
 *   - backend on :8001 with ENABLE_BASELINE_V2=1
 *   - frontend on :3000
 *   - SCREENSHOT_TOKEN (admin JWT tenant=1)
 *
 * Optional env:
 *   V2_CASE_ID — existing v2 case in hold/review_due for case page (created by test script)
 *   V1_CASE_ID — v1 case id for control screenshot (default: any v1 quantitative)
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const dir = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.join(dir, '..', 'screenshots', 'baseline-v2-p4')
const TOKEN = process.env.SCREENSHOT_TOKEN
const BASE = process.env.SCREENSHOT_BASE || 'http://localhost:3000'
const API = process.env.SCREENSHOT_API || 'http://127.0.0.1:8002'
const API_PORT = API.replace(/.*:(\d+).*/, '$1') || '8002'

if (!TOKEN) {
  console.error('Set SCREENSHOT_TOKEN (admin JWT)')
  process.exit(1)
}

fs.mkdirSync(OUT, { recursive: true })

async function authContext(browser, extraRoutes) {
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } })
  await context.route('http://127.0.0.1:8000/**', async (route) => {
    const url = route.request().url().replace('127.0.0.1:8000', `127.0.0.1:${API_PORT}`)
    await route.continue({ url })
  })
  await context.route('http://localhost:8000/**', async (route) => {
    const url = route.request().url().replace('localhost:8000', `127.0.0.1:${API_PORT}`)
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

async function openBabyModal(page) {
  await page.goto(`${BASE}/admin-portal/chatters`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('text=Активные чаттеры', { timeout: 30000 })
  const row = page.locator('tr', { hasText: '@Baby_W0rker' }).first()
  await row.locator('button:has-text("Кейс")').click()
  await page.waitForSelector('text=Открыть кейс', { timeout: 15000 })
  await page.waitForTimeout(1200)
}

async function findV1CaseId() {
  const res = await fetch(`${API}/api/v1/admin-portal/cases?include_closed=true`, {
    headers: { Authorization: `Bearer ${TOKEN}` },
  })
  const cases = await res.json()
  const v1 = cases.find(
    (c) => (c.baseline_version ?? 'v1') === 'v1' && c.case_type === 'quantitative' && c.baseline_value != null,
  )
  return v1?.id ?? cases[0]?.id
}

async function findOrphanOm() {
  const res = await fetch(`${API}/api/v1/admin-portal/chatters`, {
    headers: { Authorization: `Bearer ${TOKEN}` },
  })
  const rows = await res.json()
  const orphan = rows.find((r) => !r.is_mapped && r.om_user_id)
  return orphan?.om_user_id ?? '195781'
}

async function cancelOpenCases(metric) {
  const res = await fetch(`${API}/api/v1/admin-portal/cases`, {
    headers: { Authorization: `Bearer ${TOKEN}` },
  })
  const cases = await res.json()
  for (const c of cases) {
    if (c.om_user_id === '84527' && c.metric_type === metric && !['closed', 'cancelled'].includes(c.stage)) {
      await fetch(`${API}/api/v1/admin-portal/cases/${c.id}/transition`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${TOKEN}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ target_stage: 'cancelled', notes: 'screenshot prep' }),
      })
      console.log('cancelled case', c.id)
    }
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true })

  // b) Case page v2 first (before cancel for modal)
  const v2CaseId = process.env.V2_CASE_ID
  if (v2CaseId) {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(`${BASE}/admin-portal/cases/${v2CaseId}`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForSelector('[data-testid="metric-v2-block"]', { timeout: 25000 })
    await page.waitForTimeout(800)
    await page.screenshot({ path: path.join(OUT, '02-case-v2-two-rows.png'), fullPage: true })
    console.log('02 case v2', v2CaseId)
    await ctx.close()
  } else {
    console.log('02 skipped — set V2_CASE_ID for case page screenshot')
  }

  await cancelOpenCases('ppv_open_rate')

  // a) Modal v2 — Baby_W0rker 4 cards
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await openBabyModal(page)
    await page.waitForSelector('[data-testid="baseline-preview-v2"]', { timeout: 25000 })
    await page.screenshot({ path: path.join(OUT, '01-modal-v2-baby-worker.png') })
    console.log('01 modal v2')
    await ctx.close()
  }

  // c) New chatter modal — mock preview
  {
    const orphanOm = await findOrphanOm()
    const ctx = await authContext(browser, async (context) => {
      await context.route('**/baseline-preview**', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            available: true,
            lookback_days: 30,
            baseline_version: 'v2',
            daily_value: 33.3,
            week_avg_value: 25.3,
            month_current_value: null,
            prev_month_value: null,
            is_new_chatter: true,
            is_early_month: false,
            value: 33.3,
            snapshot_date: '2026-07-10',
          }),
        })
      })
    })
    const page = await ctx.newPage()
    await page.goto(`${BASE}/admin-portal/chatters`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForSelector('text=Активные чаттеры', { timeout: 30000 })
    // Open modal on first orphan row if present
    const orphanRow = page.locator('tr', { hasText: 'Сироты' }).locator('..').locator('tr').nth(1)
    const caseBtn = page.locator('button:has-text("Кейс")').first()
    await caseBtn.click()
    await page.waitForSelector('text=Открыть кейс', { timeout: 15000 })
    await page.waitForSelector('[data-testid="flag-new-chatter"]', { timeout: 15000 })
    await page.screenshot({ path: path.join(OUT, '03-modal-new-chatter.png') })
    console.log('03 new chatter flag (orphan om hint:', orphanOm, ')')
    await ctx.close()
  }

  // d) v1 case control
  const v1Id = process.env.V1_CASE_ID || (await findV1CaseId())
  if (v1Id) {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(`${BASE}/admin-portal/cases/${v1Id}`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForSelector('text=Baseline', { timeout: 25000 })
    await page.waitForTimeout(500)
    await page.screenshot({ path: path.join(OUT, '04-case-v1-control.png'), fullPage: true })
    console.log('04 v1 control', v1Id)
    await ctx.close()
  }

  await browser.close()
  console.log('Done:', OUT)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
