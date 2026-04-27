<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { onClickOutside } from '@vueuse/core'

interface Project {
  id: number
  path_with_namespace: string
}

interface ConfiguredProject {
  project_id: number
  name: string
  path_with_namespace: string
  web_url: string
  hook_url: string
  branch_filter: string
  hook_id: number
  updated_at: string
}

interface LogEvent {
  step: string
  status: string
  message: string
  output: string
  timestamp: string
}

// State
const currentTab = ref<'config' | 'monitor'>('config')

const projects = ref<Project[]>([])
const configuredProjects = ref<ConfiguredProject[]>([])
const selectedProject = ref<string>('')
const hookUrl = ref<string>('')
const hookToken = ref<string>('')
const branchMode = ref<'any'|'specific'>('any')
const branchTags = ref<string[]>([])
const currentTagInput = ref<string>('')
const configStatusText = ref<string>('✦ 准备就绪')
const configStatusType = ref<'normal'|'error'>('normal')

// Project Dropdown State
const isProjectDropdownOpen = ref(false)
const projectSearchQuery = ref('')
const projectDropdownRef = ref<HTMLElement | null>(null)

onClickOutside(projectDropdownRef, () => {
  isProjectDropdownOpen.value = false
})

const filteredProjects = computed(() => {
  if (!projectSearchQuery.value) return projects.value
  const q = projectSearchQuery.value.toLowerCase()
  return projects.value.filter(p => p.path_with_namespace.toLowerCase().includes(q))
})

const selectProject = (id: number) => {
  selectedProject.value = id.toString()
  isProjectDropdownOpen.value = false
  projectSearchQuery.value = ''
}

const displayProjectName = computed(() => {
  if (!selectedProject.value) return ''
  const p = projects.value.find(p => p.id.toString() === selectedProject.value)
  return p ? p.path_with_namespace : ''
})

const taskId = ref<string>('')
const streamStatusText = ref<string>('✦ 尚未连接')
const streamStatusState = ref<'idle'|'connecting'|'connected'|'error'>('idle')

const steps = ["accepted", "checkout", "build", "release", "health_check", "deploy"]
const stepStates = ref<Record<string, string>>(
  steps.reduce((acc, step) => ({ ...acc, [step]: 'pending' }), {})
)

const logs = ref<LogEvent[]>([])
const terminalEl = ref<HTMLElement | null>(null)

let es: EventSource | null = null

const setConfigStatus = (msg: string, isError = false) => {
  configStatusText.value = msg
  configStatusType.value = isError ? 'error' : 'normal'
}

const fetchProjects = async () => {
  setConfigStatus('✦ 加载项目中...')
  try {
    const res = await fetch('/api/gitlab/projects?per_page=100')
    const data = await res.json()
    if (!data.projects?.length) {
      setConfigStatus('✦ 未找到项目', true)
      return
    }
    projects.value = data.projects
    setConfigStatus(`✦ 已加载 ${data.projects.length} 个项目`)
  } catch (err: any) {
    setConfigStatus(`✦ 加载失败: ${err.message}`, true)
  }
}

const fetchConfiguredProjects = async () => {
  try {
    const res = await fetch('/api/gitlab/configured-projects')
    const data = await res.json()
    configuredProjects.value = data.projects || []
  } catch (err) {
    console.error('Failed to fetch configured projects', err)
  }
}

const applyConfig = async () => {
  if (!selectedProject.value) return setConfigStatus('✦ 请先选择项目', true)
  if (!hookUrl.value) return setConfigStatus('✦ Hook URL 不能为空', true)

  const branch_filter = branchMode.value === 'specific' ? branchTags.value.join(',') : ''

  const payload = {
    hook_url: hookUrl.value.trim(),
    hook_token: hookToken.value.trim(),
    branch_filter,
    enable_ssl_verification: true,
  }

  setConfigStatus('✦ 正在配置 Hook...')
  try {
    const res = await fetch(`/api/gitlab/projects/${selectedProject.value}/hook`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || '配置失败')
    setConfigStatus('✦ 配置成功!')
    await fetchConfiguredProjects()
  } catch (err: any) {
    setConfigStatus(`✦ 配置失败: ${err.message}`, true)
  }
}

const scrollToBottom = () => {
  nextTick(() => {
    if (terminalEl.value) {
      terminalEl.value.scrollTop = terminalEl.value.scrollHeight
    }
  })
}

const connectStream = () => {
  if (!taskId.value.trim()) {
    streamStatusText.value = '✦ 请输入 task_id'
    streamStatusState.value = 'error'
    return
  }

  if (es) {
    es.close()
  }
  
  // reset state
  logs.value = []
  stepStates.value = steps.reduce((acc, step) => ({ ...acc, [step]: 'pending' }), {})
  
  streamStatusText.value = '✦ 连接中...'
  streamStatusState.value = 'connecting'
  
  es = new EventSource(`/api/deploy/${encodeURIComponent(taskId.value.trim())}/stream`)
  
  es.onopen = () => {
    streamStatusText.value = '✦ 已连接到实时流'
    streamStatusState.value = 'connected'
  }
  
  es.onmessage = (event) => {
    try {
      const payload: LogEvent = JSON.parse(event.data)
      logs.value.push(payload)
      stepStates.value[payload.step] = payload.status
      scrollToBottom()
    } catch (e) {}
  }
  
  es.addEventListener('end', () => {
    streamStatusText.value = '✦ 任务执行完成'
    streamStatusState.value = 'idle'
    if (es) es.close()
  })
  
  es.onerror = () => {
    streamStatusText.value = '✦ 连接中断'
    streamStatusState.value = 'error'
  }
}

const clearLogs = () => {
  logs.value = []
}

const addTag = (e: KeyboardEvent) => {
  if (e.key === 'Enter' || e.key === ',') {
    e.preventDefault()
    const val = currentTagInput.value.trim().replace(/,$/, '')
    if (val && !branchTags.value.includes(val)) {
      branchTags.value.push(val)
    }
    currentTagInput.value = ''
  } else if (e.key === 'Backspace' && currentTagInput.value === '' && branchTags.value.length > 0) {
    branchTags.value.pop()
  }
}

const removeTag = (index: number) => {
  branchTags.value.splice(index, 1)
}

onMounted(async () => {
  await fetchProjects()
  await fetchConfiguredProjects()
  try {
    const res = await fetch('/api/gitlab/config')
    const data = await res.json()
    hookUrl.value = data.default_hook_url || (window.location.origin + '/api/hook/gitlab')
    if (data.default_hook_branch_filter) {
      branchMode.value = 'specific'
      branchTags.value = data.default_hook_branch_filter.split(',').map((s:string) => s.trim()).filter(Boolean)
    }
  } catch (e) {}

  const urlParams = new URLSearchParams(window.location.search)
  if (urlParams.has('task_id')) {
    taskId.value = urlParams.get('task_id') || ''
    currentTab.value = 'monitor'
    connectStream()
  }
})

// UI Helpers
const getStepClasses = (status: string) => {
  const base = 'bg-slate-900 border rounded-lg p-3 text-center transition-all duration-300 flex flex-col items-center justify-center min-h-[80px] relative overflow-hidden'
  const map: Record<string, string> = {
    pending: `${base} border-slate-800 text-slate-600`,
    running: `${base} border-indigo-500 bg-indigo-500/5 text-indigo-400`,
    success: `${base} border-emerald-500/50 bg-emerald-500/5 text-emerald-400 shadow-[0_0_15px_rgba(16,185,129,0.2)]`,
    failed: `${base} border-red-500/50 bg-red-500/5 text-red-400 shadow-[0_0_15px_rgba(239,68,68,0.2)]`,
    skipped: `${base} border-amber-500/50 bg-amber-500/5 text-amber-400 shadow-[0_0_15px_rgba(245,158,11,0.2)]`
  }
  return map[status] || map.pending
}

const getStepText = (status: string) => {
  const map: Record<string, string> = {
    pending: '等待中',
    running: '执行中',
    success: '已完成',
    failed: '失败',
    skipped: '已跳过'
  }
  return map[status] || '等待中'
}

const getLogColorClass = (status: string) => {
  if (status === 'failed') return 'text-red-400'
  if (status === 'success') return 'text-emerald-400'
  if (status === 'skipped') return 'text-amber-400'
  return 'text-slate-300'
}

const formatTime = (ts: string) => new Date(ts).toLocaleTimeString()
</script>

<template>
  <div class="min-h-screen bg-slate-950 text-slate-300 p-4 md:p-8 font-sans" style="background: linear-gradient(135deg, #0f172a, #1e293b)">
    <div class="max-w-7xl mx-auto space-y-6">
      
      <!-- Header -->
      <header class="flex flex-col sm:flex-row items-start sm:items-center justify-between pb-6 border-b border-slate-800 gap-4">
        <div>
          <h1 class="text-3xl font-bold bg-gradient-to-r from-blue-400 to-indigo-400 bg-clip-text text-transparent">GitLab 自动化部署</h1>
          <p class="mt-1 text-sm text-slate-500">配置项目 Webhook 并实时监控部署流水线</p>
        </div>
      </header>

      <!-- Tab Navigation -->
      <div class="flex items-center gap-4 mb-8">
        <button 
          @click="currentTab = 'config'" 
          class="px-5 py-2.5 rounded-lg font-medium transition-all duration-300 flex items-center gap-2"
          :class="currentTab === 'config' ? 'bg-indigo-500/20 text-indigo-300 shadow-[0_0_15px_rgba(99,102,241,0.2)] ring-1 ring-indigo-500/50' : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'"
        >
          <div class="i-carbon-settings w-5 h-5"></div>
          Webhook 管理
        </button>
        <button 
          @click="currentTab = 'monitor'" 
          class="px-5 py-2.5 rounded-lg font-medium transition-all duration-300 flex items-center gap-2"
          :class="currentTab === 'monitor' ? 'bg-emerald-500/20 text-emerald-300 shadow-[0_0_15px_rgba(16,185,129,0.2)] ring-1 ring-emerald-500/50' : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'"
        >
          <div class="i-carbon-terminal w-5 h-5"></div>
          部署流监控
        </button>
      </div>

      <!-- TAB 1: Config & List -->
      <div v-show="currentTab === 'config'" class="animate-fade-in">
        <div class="grid grid-cols-1 xl:grid-cols-12 gap-8">
          
          <!-- Left Column: Settings Form -->
          <div class="xl:col-span-4 space-y-6">
            <section class="bg-white/5 backdrop-blur-md border border-white/10 rounded-2xl p-6 shadow-2xl transition-all duration-300 hover:shadow-indigo-500/10">
              <div class="flex items-center justify-between mb-6">
                <h2 class="text-lg font-semibold text-white">配置 Webhook</h2>
                <span 
                  class="text-xs px-2 py-1 rounded-full border transition-colors"
                  :class="configStatusType === 'error' ? 'bg-red-500/10 text-red-400 border-red-500/20' : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'"
                >
                  {{ configStatusText }}
                </span>
              </div>

              <div class="space-y-5">
                <!-- Project -->
                <div>
                  <label class="block text-sm font-medium text-slate-400 mb-1.5">选择项目</label>
                  <div class="flex gap-2">
                    <div class="relative flex-1" ref="projectDropdownRef">
                      <div 
                        class="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-200 cursor-pointer flex items-center justify-between transition-colors hover:bg-white/5 focus-within:border-indigo-500 focus-within:ring-1 focus-within:ring-indigo-500"
                        @click="isProjectDropdownOpen = !isProjectDropdownOpen"
                      >
                        <span v-if="!selectedProject" class="text-slate-400">请选择项目</span>
                        <span v-else class="truncate">{{ displayProjectName }}</span>
                        <div class="i-carbon-chevron-down w-4 h-4 text-slate-500 transition-transform duration-200" :class="{ 'rotate-180': isProjectDropdownOpen }"></div>
                      </div>

                      <div 
                        v-if="isProjectDropdownOpen" 
                        class="absolute top-full left-0 right-0 mt-1 bg-[#1e293b] border border-white/10 rounded-lg shadow-xl z-50 overflow-hidden"
                      >
                        <div class="p-2 border-b border-white/5">
                          <div class="relative">
                            <div class="i-carbon-search absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400"></div>
                            <input 
                              v-model="projectSearchQuery" 
                              type="text" 
                              class="w-full bg-black/30 border border-white/5 rounded pl-8 pr-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500/50" 
                              placeholder="搜索项目..." 
                              @click.stop
                            />
                          </div>
                        </div>
                        <ul class="max-h-60 overflow-y-auto scrollbar-custom py-1">
                          <li v-if="projects.length === 0" class="px-3 py-4 text-center text-xs text-slate-500 flex justify-center items-center gap-2">
                            <div class="i-carbon-progress-bar-round animate-spin"></div>
                            正在加载项目...
                          </li>
                          <li v-else-if="filteredProjects.length === 0" class="px-3 py-4 text-center text-xs text-slate-500">
                            未找到匹配的项目
                          </li>
                          <li 
                            v-for="p in filteredProjects" 
                            :key="p.id" 
                            class="px-3 py-2 text-sm text-slate-300 hover:bg-indigo-500/20 hover:text-indigo-200 cursor-pointer transition-colors truncate"
                            :class="{ 'bg-indigo-500/10 text-indigo-300': selectedProject === p.id.toString() }"
                            @click="selectProject(p.id)"
                            :title="p.path_with_namespace"
                          >
                            {{ p.path_with_namespace }}
                          </li>
                        </ul>
                      </div>
                    </div>
                    <button @click="fetchProjects" class="w-[38px] h-[38px] flex justify-center items-center rounded-lg text-slate-400 hover:text-indigo-400 hover:bg-indigo-500/10 border border-transparent hover:border-indigo-500/20 transition-all shrink-0" title="刷新项目列表">
                      <div class="i-carbon-renew w-4 h-4"></div>
                    </button>
                  </div>
                </div>

                <!-- URL -->
                <div>
                  <label class="block text-sm font-medium text-slate-400 mb-1.5">Hook URL</label>
                  <input v-model="hookUrl" type="text" class="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-colors" placeholder="https://..." />
                </div>

                <!-- Branches -->
                <div>
                  <label class="block text-sm font-medium text-slate-400 mb-2">触发分支</label>
                  <div class="flex items-center gap-4 mb-3">
                    <label class="flex items-center gap-2 cursor-pointer">
                      <input type="radio" v-model="branchMode" value="any" class="text-indigo-500 focus:ring-indigo-500 bg-black/20 border-white/10">
                      <span class="text-sm">任何分支</span>
                    </label>
                    <label class="flex items-center gap-2 cursor-pointer">
                      <input type="radio" v-model="branchMode" value="specific" class="text-indigo-500 focus:ring-indigo-500 bg-black/20 border-white/10">
                      <span class="text-sm">指定分支 (多选)</span>
                    </label>
                  </div>
                  
                  <div v-if="branchMode === 'specific'">
                    <div class="w-full bg-black/20 border border-white/10 rounded-lg p-2 flex flex-wrap gap-2 items-center focus-within:border-indigo-500 focus-within:ring-1 focus-within:ring-indigo-500 transition-colors min-h-[42px]">
                      <div class="flex flex-wrap gap-2">
                        <div v-for="(tag, i) in branchTags" :key="i" class="flex items-center gap-1 bg-indigo-500/20 text-indigo-300 px-2 py-1 rounded text-xs border border-indigo-500/30">
                          <span>{{ tag }}</span>
                          <button type="button" class="text-indigo-400 hover:text-indigo-200" @click="removeTag(i)">
                            <div class="i-carbon-close w-3 h-3"></div>
                          </button>
                        </div>
                      </div>
                      <input 
                        v-model="currentTagInput" 
                        @keydown="addTag" 
                        type="text" 
                        class="flex-1 bg-transparent border-none text-sm text-slate-200 focus:outline-none focus:ring-0 min-w-[120px] px-1" 
                        placeholder="输入分支名按回车添加..." 
                      />
                    </div>
                    <p class="mt-1 text-xs text-slate-500">支持输入多个分支，如 main, release/*</p>
                  </div>
                </div>

                <!-- Token -->
                <div>
                  <label class="block text-sm font-medium text-slate-400 mb-1.5">安全 Token</label>
                  <input v-model="hookToken" type="text" class="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-colors" placeholder="可选" />
                </div>

                <button @click="applyConfig" class="w-full mt-2 bg-indigo-600 hover:bg-indigo-500 text-white font-medium py-2.5 rounded-lg transition-colors shadow-lg shadow-indigo-500/20 flex items-center justify-center gap-2">
                  <div class="i-carbon-rocket"></div> 应用配置
                </button>
              </div>
            </section>
          </div>

          <!-- Right Column: Configured Projects Table -->
          <div class="xl:col-span-8">
            <section class="bg-white/5 backdrop-blur-md border border-white/10 rounded-2xl p-6 shadow-2xl transition-all duration-300 hover:shadow-indigo-500/10 h-full">
              <div class="flex items-center justify-between mb-6">
                <div class="flex items-center gap-2">
                  <div class="i-carbon-list w-5 h-5 text-indigo-400"></div>
                  <h2 class="text-lg font-semibold text-white">已配置项目列表</h2>
                </div>
                <span class="text-xs px-2 py-1 bg-white/10 rounded-full text-slate-300 border border-white/10">
                  共 {{ configuredProjects.length }} 个
                </span>
              </div>

              <div class="overflow-x-auto">
                <table class="w-full text-left text-sm text-slate-300 whitespace-nowrap">
                  <thead class="text-xs uppercase bg-black/20 text-slate-400 border-b border-white/10">
                    <tr>
                      <th scope="col" class="px-4 py-3 rounded-tl-lg">项目信息</th>
                      <th scope="col" class="px-4 py-3">Webhook URL</th>
                      <th scope="col" class="px-4 py-3">触发分支</th>
                      <th scope="col" class="px-4 py-3">更新时间</th>
                      <th scope="col" class="px-4 py-3 rounded-tr-lg">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-if="configuredProjects.length === 0">
                      <td colspan="5" class="px-4 py-12 text-center text-slate-500">
                        <div class="flex flex-col items-center gap-2">
                          <div class="i-carbon-document-unknown w-8 h-8 opacity-50"></div>
                          <p>暂无已配置的 Webhook</p>
                          <p class="text-xs">请在左侧表单中配置后在此处查看</p>
                        </div>
                      </td>
                    </tr>
                    <tr 
                      v-for="proj in configuredProjects" 
                      :key="proj.project_id" 
                      class="border-b border-white/5 hover:bg-white/5 transition-colors"
                    >
                      <td class="px-4 py-3">
                        <div class="flex flex-col gap-0.5">
                          <a :href="proj.web_url" target="_blank" class="font-medium text-slate-200 hover:text-indigo-400 transition-colors flex items-center gap-1">
                            {{ proj.name }}
                            <div class="i-carbon-launch w-3 h-3 opacity-70"></div>
                          </a>
                          <span class="text-xs text-slate-500">{{ proj.path_with_namespace }}</span>
                        </div>
                      </td>
                      <td class="px-4 py-3">
                        <div class="truncate max-w-[200px] text-xs text-slate-400 bg-black/20 px-2 py-1 rounded inline-block" :title="proj.hook_url">
                          {{ proj.hook_url }}
                        </div>
                      </td>
                      <td class="px-4 py-3">
                        <div class="flex flex-wrap gap-1 max-w-[150px]">
                          <span v-if="!proj.branch_filter" class="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-slate-400 border border-white/10">任何分支</span>
                          <template v-else>
                            <span 
                              v-for="branch in proj.branch_filter.split(',')" 
                              :key="branch" 
                              class="px-2 py-0.5 rounded text-[10px] bg-indigo-500/20 text-indigo-300 border border-indigo-500/30"
                            >
                              {{ branch.trim() }}
                            </span>
                          </template>
                        </div>
                      </td>
                      <td class="px-4 py-3 text-xs text-slate-500">
                        {{ new Date(proj.updated_at).toLocaleString() }}
                      </td>
                      <td class="px-4 py-3">
                        <a :href="`${proj.web_url}/-/settings/webhooks`" target="_blank" class="text-xs text-indigo-400 hover:text-indigo-300 transition-colors flex items-center gap-1 px-2 py-1 bg-indigo-500/10 rounded-md inline-flex border border-indigo-500/20">
                          <div class="i-carbon-settings"></div> 管理
                        </a>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </div>
      </div>

      <!-- TAB 2: Monitor -->
      <div v-show="currentTab === 'monitor'" class="animate-fade-in max-w-5xl mx-auto space-y-6">
        <!-- Connect bar -->
        <section class="bg-white/5 backdrop-blur-md border border-white/10 rounded-2xl p-6 shadow-2xl transition-all duration-300 hover:shadow-emerald-500/10">
          <div class="flex flex-col sm:flex-row gap-4 items-end">
            <div class="flex-1 w-full">
              <label class="block text-sm font-medium text-slate-400 mb-1.5">流水线 Task ID</label>
              <input v-model="taskId" @keydown.enter="connectStream" type="text" class="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition-colors" placeholder="例如: d9943662-..." />
            </div>
            <button @click="connectStream" class="w-full sm:w-auto px-8 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded-lg transition-colors shadow-lg shadow-emerald-500/20 whitespace-nowrap flex items-center justify-center gap-2">
              <div class="i-carbon-connection-signal"></div> 建立监控连接
            </button>
          </div>
          <div class="mt-4 flex items-center gap-2 bg-black/20 inline-flex px-3 py-1.5 rounded-full border border-white/5">
            <div 
              class="w-2 h-2 rounded-full shadow-[0_0_8px_currentColor]" 
              :class="{
                'bg-slate-600 text-slate-600': streamStatusState === 'idle',
                'bg-amber-500 text-amber-500 animate-pulse': streamStatusState === 'connecting',
                'bg-emerald-500 text-emerald-500 animate-pulse': streamStatusState === 'connected',
                'bg-red-500 text-red-500': streamStatusState === 'error'
              }"
            ></div>
            <span class="text-xs font-medium text-slate-300">{{ streamStatusText }}</span>
          </div>
        </section>

        <!-- Steps Flow -->
        <section class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <div v-for="step in steps" :key="step" :class="getStepClasses(stepStates[step])">
            <div class="text-[10px] uppercase tracking-wider text-slate-500 mb-1 font-semibold">{{ step.replace('_', ' ') }}</div>
            <div class="text-xs font-medium z-10">{{ getStepText(stepStates[step]) }}</div>
            
            <div v-if="stepStates[step] === 'running'" class="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent -translate-x-full animate-[shimmer_1.5s_infinite_linear]"></div>
          </div>
        </section>

        <!-- Terminal -->
        <section class="bg-[#0a0f18] border border-white/10 rounded-2xl overflow-hidden shadow-2xl flex flex-col h-[500px]">
          <div class="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-white/5 backdrop-blur-sm">
            <div class="flex items-center gap-2">
              <div class="i-carbon-terminal w-4 h-4 text-emerald-400"></div>
              <span class="text-sm font-medium text-slate-200">控制台执行日志</span>
            </div>
            <button @click="clearLogs" class="text-xs px-2 py-1 rounded bg-white/5 text-slate-400 hover:text-slate-200 hover:bg-white/10 transition-colors flex items-center gap-1">
              <div class="i-carbon-trash-can"></div> 清空日志
            </button>
          </div>
          <div class="flex-1 p-5 text-slate-300 font-mono text-[13px] overflow-y-auto space-y-1.5 scrollbar-custom" ref="terminalEl">
            <div v-if="logs.length === 0" class="flex h-full items-center justify-center opacity-30 text-sm">
              [ 等待日志数据流入... ]
            </div>
            <template v-for="(log, i) in logs" :key="i">
              <div>
                <span class="text-slate-600 mr-3">[{{ formatTime(log.timestamp) }}]</span>
                <span class="text-indigo-400 font-medium w-24 inline-block">[{{ log.step }}]</span>
                <span :class="getLogColorClass(log.status)">{{ log.message }}</span>
              </div>
              <div v-if="log.output" class="pl-4 my-2 py-2 border-l-2 border-slate-700/50 bg-white/[0.02] text-slate-400/90 whitespace-pre-wrap leading-relaxed rounded-r-md text-xs">
                {{ log.output }}
              </div>
            </template>
          </div>
        </section>
      </div>

    </div>
  </div>
</template>

<style>
@keyframes shimmer {
  100% { transform: translateX(100%); }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(5px); }
  to { opacity: 1; transform: translateY(0); }
}

.animate-fade-in {
  animation: fadeIn 0.3s ease-out forwards;
}

.scrollbar-custom::-webkit-scrollbar { width: 8px; }
.scrollbar-custom::-webkit-scrollbar-track { background: #0f172a; border-radius: 4px; }
.scrollbar-custom::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
</style>
