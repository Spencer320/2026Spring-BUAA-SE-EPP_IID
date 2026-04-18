import { createRouter, createWebHistory } from 'vue-router'
import store from '@/store'

const router = createRouter({
    history: createWebHistory(import.meta.env.BASE_URL),
    routes: [
        {
            path: '/',
            redirect: '/home',
            component: () => import(`@/views/layout/LayoutContainer.vue`),
            children: [
                {
                    path: '/home',
                    component: () => import(`@/views/main/HomePage.vue`)
                },
                {
                    path: '/user',
                    component: () => import(`@/views/user/UserManage.vue`)
                },
                {
                    path: '/paper',
                    component: () => import(`@/views/paper/PaperManage.vue`)
                },
                {
                    path: '/hot',
                    component: () => import('@/views/hot/HotManage.vue')
                },
                {
                    path: '/report',
                    redirect: '/report/unhandled',
                    component: () => import(`@/views/report/ReportManage.vue`),
                    children: [
                        {
                            path: '/report/unhandled',
                            component: () => import(`@/views/report/UnhandledReport.vue`)
                        },
                        {
                            path: '/report/handled',
                            component: () => import(`@/views/report/HandledReport.vue`)
                        }
                    ]
                },
                {
                    path: '/system_report',
                    redirect: '/report/unreverted',
                    component: () => import(`@/views/system_report/SystemReportManage.vue`),
                    children: [
                        {
                            path: '/report/unreverted',
                            component: () => import(`@/views/system_report/UnrevertedReport.vue`)
                        },
                        {
                            path: '/report/reverted',
                            component: () => import(`@/views/system_report/RevertedReport.vue`)
                        }
                    ]
                },
                {
                    path: '/access-frequency',
                    redirect: '/access-frequency/rules',
                    component: () => import('@/views/access_frequency/AccessFrequencyManage.vue'),
                    children: [
                        {
                            path: '/access-frequency/rules',
                            component: () => import('@/views/access_frequency/FrequencyRules.vue')
                        },
                        {
                            path: '/access-frequency/overrides',
                            component: () => import('@/views/access_frequency/UserOverrides.vue')
                        },
                        {
                            path: '/access-frequency/stats',
                            component: () => import('@/views/access_frequency/FrequencyStats.vue')
                        }
                    ]
                },
                {
                    path: '/deep-research',
                    redirect: '/deep-research/tasks',
                    component: () => import('@/views/deep_research/DRMonitorManage.vue'),
                    children: [
                        {
                            path: '/deep-research/tasks',
                            component: () => import('@/views/deep_research/DRTaskList.vue')
                        },
                        {
                            path: '/deep-research/audit-logs',
                            component: () => import('@/views/deep_research/DRAuditLogs.vue')
                        }
                    ]
                }
            ]
        },
        {
            path: '/login',
            name: 'login',
            component: () => import(`@/views/login/index.vue`),
            meta: {
                title: '登录页'
            }
        }
    ]
})

router.beforeEach((to) => {
    if (!store.getters.isManagerLogin && to.path !== '/login') return '/login'
})

export default router
