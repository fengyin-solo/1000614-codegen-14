<template>
  <section class="page" data-module="reagent">
    <header class="page-head">
      <div>
        <h2>试剂耗材管理</h2>
        <p class="page-desc">维护试剂物料，围绕物料编号、物料名称、规格纯度、批号做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="toggleImport">导入出入库单据</button>
        <button class="btn" type="button" @click="openCreate">登记试剂物料</button>
        <button class="btn" type="button" @click="exportRows">导出试剂耗材清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div v-if="importVisible" class="import-panel">
      <p class="import-tip">
        每行一条单据，列顺序：物料编号，规格纯度，批号，出入数量，有效期至，单据时间，出入类型（可省，默认入库）。
        同一批号在同一单据时间重复导入只入账一次；规格纯度不一致、数量为负、单据时间早于上一次结存或物料已冻结的行会被拒绝并列出原因。
      </p>
      <div class="import-controls">
        <input type="file" accept=".csv,.txt" @change="handleFile" />
        <button class="btn ghost" type="button" @click="fillSample">填入示例</button>
      </div>
      <textarea
        v-model="importText"
        class="import-text"
        rows="6"
        placeholder="REAG-0001,分析纯 AR,LOT-2026-101,5,2027-04-01,2026-09-27,入库"
      ></textarea>
      <div class="import-controls">
        <button class="btn primary" type="button" :disabled="importing" @click="submitImport">
          {{ importing ? '导入中…' : '开始导入' }}
        </button>
        <button class="btn ghost" type="button" @click="toggleImport">收起</button>
      </div>
      <div v-if="importResult" class="import-result">
        <p :class="importResult.ok ? 'ok-text' : 'error-text'">{{ importResult.message }}</p>
        <ul v-if="importResult.errors.length" class="error-list">
          <li v-for="error in importResult.errors" :key="error.row">
            第 {{ error.row }} 行（{{ error.values['物料编号'] ?? '—' }} / {{ error.values['批号'] ?? '—' }}）：
            {{ error.reasons.join('；') }}
          </li>
        </ul>
      </div>
      <p v-if="importError" class="error-text">{{ importError }}</p>
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
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无试剂耗材数据，可先登记试剂物料</td>
        </tr>
      </tbody>
    </table>

    <div v-if="detail" class="detail-panel">
      <header class="detail-head">
        <h3>物料明细：{{ detail['物料编号'] }}</h3>
        <button class="btn ghost" type="button" @click="detail = null">关闭</button>
      </header>
      <dl class="detail-grid">
        <template v-for="key in detailFields" :key="key">
          <dt>{{ key }}</dt>
          <dd>{{ detail[key] ?? '—' }}</dd>
        </template>
      </dl>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条试剂耗材记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

type ImportRowError = {
  row: number
  reasons: string[]
  values: Record<string, string | number | null>
}

type ImportResult = {
  ok: boolean
  message: string
  total: number
  posted: number
  duplicated: number
  rejected: number
  errors: ImportRowError[]
}

const ENDPOINT = '/api/reagent'
const columns = ["物料编号", "物料名称", "规格纯度", "批号", "结存数量", "有效期至", "保管人员", "物料状态"]
const actions = ["冻结物料", "解冻物料", "登记耗尽"]
const statuses = ["正常可用", "临近有效期", "已冻结", "已耗尽"]
const detailFields = [...columns, "最近入账时间"]
const IMPORT_HEADERS = ["物料编号", "规格纯度", "批号", "出入数量", "有效期至", "单据时间", "出入类型"]
const SAMPLE_LINE = "REAG-0001,分析纯 AR,LOT-2026-101,5,2027-04-01,2026-09-27,入库"

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const detail = ref<Row | null>(null)

const importVisible = ref(false)
const importText = ref('')
const importing = ref(false)
const importResult = ref<ImportResult | null>(null)
const importError = ref('')

const stats = computed(() => [
  { label: '可用物料', value: rows.value.filter((row) => row['物料状态'] === '正常可用').length },
  { label: '临期物料', value: rows.value.filter((row) => row['物料状态'] === '临近有效期').length },
  { label: '已冻结物料', value: rows.value.filter((row) => row['物料状态'] === '已冻结').length },
])

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '试剂物料登记入口尚未接入审批流'
}

function toggleImport() {
  importVisible.value = !importVisible.value
  importResult.value = null
  importError.value = ''
}

function fillSample() {
  importText.value = `物料编号,规格纯度,批号,出入数量,有效期至,单据时间,出入类型\n${SAMPLE_LINE}`
}

function handleFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) {
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    importText.value = String(reader.result ?? '')
  }
  reader.onerror = () => {
    importError.value = '文件读取失败，请改用粘贴方式导入'
  }
  reader.readAsText(file)
}

function parseImportRows(): Array<Record<string, string>> {
  return importText.value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !line.startsWith('物料编号'))
    .map((line) => {
      const cells = line.split(/[,\t]/).map((cell) => cell.trim())
      const row: Record<string, string> = {}
      IMPORT_HEADERS.forEach((header, index) => {
        if (cells[index]) {
          row[header] = cells[index]
        }
      })
      return row
    })
}

async function submitImport() {
  importResult.value = null
  importError.value = ''
  const payloadRows = parseImportRows()
  if (!payloadRows.length) {
    importError.value = '没有可导入的单据行，请先粘贴或选择文件'
    return
  }
  importing.value = true
  try {
    const response = await request(`${ENDPOINT}/import`, {
      method: 'POST',
      body: JSON.stringify({ rows: payloadRows }),
    })
    if (!response.ok) {
      throw new Error(`导入接口返回 ${response.status}`)
    }
    importResult.value = (await response.json()) as ImportResult
    await reload()
  } catch (error) {
    importError.value = error instanceof Error ? error.message : '出入库单据导入失败'
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
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '试剂耗材操作失败'
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

onMounted(reload)
</script>

<style scoped>
.import-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
}
.import-tip {
  color: var(--muted);
  font-size: 12px;
  margin: 0 0 8px;
}
.import-controls {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 8px 0;
}
.import-text {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px;
  font-family: inherit;
  font-size: 13px;
}
.import-result {
  font-size: 13px;
}
.error-list {
  margin: 4px 0 0;
  padding-left: 18px;
  color: #b42318;
}
.ok-text {
  color: #067647;
}
.detail-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-top: 12px;
}
.detail-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.detail-head h3 {
  margin: 0;
  font-size: 14px;
}
.detail-grid {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 6px 12px;
  margin: 10px 0 0;
  font-size: 13px;
}
.detail-grid dt {
  color: var(--muted);
}
.detail-grid dd {
  margin: 0;
}
</style>
