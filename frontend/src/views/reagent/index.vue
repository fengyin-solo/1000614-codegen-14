<template>
  <section class="page" data-module="reagent">
    <header class="page-head">
      <div>
        <h2>试剂耗材管理</h2>
        <p class="page-desc">按物料编号整批导入出入库单据，系统按单据重算结存数量，并依据有效期重算临期与耗尽状态。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="importPanelOpen = !importPanelOpen">
          {{ importPanelOpen ? '收起导入面板' : '整批导入出入库单据' }}
        </button>
        <button class="btn" type="button" @click="exportRows">导出试剂耗材清单</button>
      </div>
    </header>

    <div v-if="importPanelOpen" class="import-panel">
      <div class="import-head">
        <strong>出入库单据导入</strong>
        <a class="link" :href="ENDPOINT + '/import-template'" download>下载 CSV 导入模板</a>
      </div>
      <p class="page-desc">
        文件需包含：物料编号、规格纯度、批号、出入数量、有效期至、单据时间（可选：出入库类型，出库填「出库」，留空按入库处理）。
        同一批号在同一单据时间只能入账一次；有任意一行不合规时整批拒写，修正后可直接重试，已入账行不会重复扣减。
      </p>
      <div class="import-controls">
        <input ref="fileInput" type="file" accept=".csv,text/csv" @change="onFilePicked" />
        <button class="btn primary" type="button" :disabled="!pickedFile || importing" @click="submitImport">
          {{ importing ? '导入中…' : '开始导入并重算结存' }}
        </button>
        <button v-if="importResult || importError" class="btn ghost" type="button" @click="resetImport">清空结果</button>
      </div>
      <p v-if="importError" class="error-text">{{ importError }}</p>
      <div v-if="importResult" class="import-result" :class="importResult.ok ? 'ok' : 'fail'">
        <p>
          <strong>{{ importResult.ok ? '导入完成' : '整批未写入' }}：</strong>{{ importResult.message }}
          <template v-if="importResult.ok">（本次入账 {{ importResult.posted }} 张，跳过重复 {{ importResult.skipped }} 张）</template>
        </p>
        <p v-if="!importResult.ok" class="page-desc">请按下表逐条修正后重新选择文件重试，已入账的单据不会被重复扣减。</p>
        <table v-if="importResult.failures.length" class="data-table">
          <thead>
            <tr><th>行号</th><th>物料编号</th><th>批号</th><th>拒绝原因</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in importResult.failures" :key="item.行号 + '-' + item.批号">
              <td>{{ item.行号 }}</td>
              <td>{{ item.物料编号 || '—' }}</td>
              <td>{{ item.批号 || '—' }}</td>
              <td class="error-text">{{ item.原因 }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card" :class="item.tone" @click="filterByStatus(item.status)">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>物料编号</span>
        <input v-model="keyword" placeholder="按物料编号检索" />
      </label>
      <label class="filter-item">
        <span>物料状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">查看明细</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无试剂耗材数据，可先导入出入库单据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条试剂耗材记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal">
        <div class="modal-head">
          <strong>试剂物料明细</strong>
          <button class="link" type="button" @click="detail = null">关闭</button>
        </div>
        <dl class="detail-grid">
          <template v-for="column in detailColumns" :key="column">
            <dt>{{ column }}</dt>
            <dd :class="column === '结存数量' ? 'balance-cell' : ''">{{ detail[column] ?? '—' }}</dd>
          </template>
        </dl>
        <p class="page-desc">明细中的结存数量与列表、临期状态统计同源，刷新后保持一致。</p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Failure = { 行号: number; 物料编号: string | null; 批号: string | null; 原因: string }
type ImportResult = {
  ok: boolean
  message: string
  posted: number
  skipped: number
  failures: Failure[]
  entries: Row[]
}

const ENDPOINT = '/api/reagent'
const columns = ["物料编号", "物料名称", "规格纯度", "批号", "结存数量", "有效期至", "保管人员", "物料状态"]
const detailColumns = ["物料编号", "物料名称", "规格纯度", "批号", "结存数量", "有效期至", "保管人员", "物料状态", "上次结存时间"]
const actions = ["冻结物料", "解冻物料", "登记耗尽"]
const statuses = ["正常可用", "临近有效期", "已冻结", "已耗尽"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const stats = ref([
  { label: '可用物料', value: 0, status: '正常可用', tone: '' },
  { label: '临期物料', value: 0, status: '临近有效期', tone: 'warn' },
  { label: '已冻结物料', value: 0, status: '已冻结', tone: 'frozen' },
  { label: '已耗尽物料', value: 0, status: '已耗尽', tone: 'dead' },
])

const importPanelOpen = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const pickedFile = ref<File | null>(null)
const importing = ref(false)
const importError = ref('')
const importResult = ref<ImportResult | null>(null)

const detail = ref<Row | null>(null)

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function filterByStatus(status: string) {
  statusFilter.value = statusFilter.value === status ? '' : status
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function onFilePicked(event: Event) {
  importError.value = ''
  importResult.value = null
  const target = event.target as HTMLInputElement
  pickedFile.value = target.files?.[0] ?? null
}

function resetImport() {
  importError.value = ''
  importResult.value = null
  pickedFile.value = null
  if (fileInput.value) {
    fileInput.value.value = ''
  }
}

async function submitImport() {
  if (!pickedFile.value) {
    return
  }
  importing.value = true
  importError.value = ''
  importResult.value = null
  try {
    const content = await pickedFile.value.text()
    const response = await request(`${ENDPOINT}/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'text/csv; charset=utf-8' },
      body: content,
    })
    const payload = (await response.json()) as ImportResult & { detail?: string }
    if (!response.ok) {
      throw new Error(payload.detail || '导入失败，请检查文件后重试')
    }
    importResult.value = payload
    // 导入后刷新列表与临期状态统计，结存变化立即体现在试剂台账里
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    importError.value = error instanceof Error ? error.message : '单据导入失败，可直接重试'
  } finally {
    importing.value = false
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('试剂物料明细读取失败')
    }
    detail.value = (await response.json()) as Row
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '试剂物料明细读取失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('试剂耗材动作未生效，请稍后重试')
    }
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '试剂耗材操作失败'
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      return
    }
    const data = (await response.json()) as Record<string, number>
    stats.value.forEach((item) => {
      item.value = data[item.status] ?? 0
    })
  } catch {
    // 统计卡片读取失败不阻塞台账列表
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) {
    query.set('keyword', keyword.value)
  }
  if (statusFilter.value) {
    query.set('status', statusFilter.value)
  }
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('试剂物料列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '试剂耗材列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void reloadStats()
})
</script>
